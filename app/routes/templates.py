import re
from pathlib import Path

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import BARTENDER_TEMPLATES_DIR, TEMPLATES_DIR
from app.db import get_db
from app.models import TemplateMaster


router = APIRouter(prefix="/templates", tags=["templates"])
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
DEFAULT_REQUIRED_FIELDS = "brand,item_display_name,article_no,size,mrp,coded_price,barcode"


def _template_id_from_path(path: Path) -> str:
    template_id = re.sub(r"[^A-Za-z0-9]+", "_", path.stem).strip("_").upper()
    return template_id or "TEMPLATE"


def _unique_template_id(db: Session, base_template_id: str) -> str:
    template_id = base_template_id
    counter = 2
    while db.scalar(select(TemplateMaster).where(TemplateMaster.template_id == template_id)):
        template_id = f"{base_template_id}_{counter}"
        counter += 1
    return template_id


def _normalized_path(value: str) -> str:
    return str(Path(value)).lower()


@router.get("/", response_class=HTMLResponse)
def list_templates(
    request: Request,
    edit_id: int | None = None,
    imported: int | None = None,
    skipped: int | None = None,
    db: Session = Depends(get_db),
):
    template_rows = db.execute(
        select(TemplateMaster).order_by(TemplateMaster.active_status.desc(), TemplateMaster.template_name)
    ).scalars().all()
    template = db.get(TemplateMaster, edit_id) if edit_id else None
    message = None
    if imported is not None and skipped is not None:
        message = f"Imported {imported} template file(s), skipped {skipped} existing file(s)."

    return templates.TemplateResponse(
        request,
        "templates.html",
        {
            "request": request,
            "template_rows": template_rows,
            "template": template,
            "bartender_templates_dir": BARTENDER_TEMPLATES_DIR,
            "message": message,
        },
    )


@router.post("/")
def create_template(
    template_id: str = Form(...),
    template_name: str = Form(...),
    label_size: str = Form(""),
    has_logo: bool = Form(False),
    category: str = Form(""),
    bartender_file_path: str = Form(...),
    printer_name: str = Form(""),
    required_fields: str = Form(""),
    active_status: bool = Form(False),
    db: Session = Depends(get_db),
):
    template = TemplateMaster(
        template_id=template_id.strip(),
        template_name=template_name.strip(),
        label_size=label_size.strip() or None,
        has_logo=has_logo,
        category=category.strip() or None,
        bartender_file_path=bartender_file_path.strip(),
        printer_name=printer_name.strip() or None,
        required_fields=required_fields.strip() or None,
        active_status=active_status,
    )
    db.add(template)
    db.commit()
    return RedirectResponse("/templates", status_code=303)


@router.post("/import-folder")
def import_bartender_templates(db: Session = Depends(get_db)):
    BARTENDER_TEMPLATES_DIR.mkdir(parents=True, exist_ok=True)
    template_files = sorted(BARTENDER_TEMPLATES_DIR.rglob("*.btw"))
    existing_paths = {
        _normalized_path(path)
        for path in db.execute(select(TemplateMaster.bartender_file_path)).scalars().all()
        if path
    }
    imported = 0
    skipped = 0

    for path in template_files:
        full_path = str(path.resolve())
        if _normalized_path(full_path) in existing_paths:
            skipped += 1
            continue

        template_id = _unique_template_id(db, _template_id_from_path(path))
        db.add(
            TemplateMaster(
                template_id=template_id,
                template_name=path.stem.replace("_", " ").replace("-", " ").title(),
                label_size="",
                has_logo=False,
                category="Imported",
                bartender_file_path=full_path,
                printer_name="",
                required_fields=DEFAULT_REQUIRED_FIELDS,
                active_status=True,
            )
        )
        existing_paths.add(_normalized_path(full_path))
        imported += 1

    db.commit()
    return RedirectResponse(
        f"/templates?imported={imported}&skipped={skipped}",
        status_code=303,
    )


@router.post("/{template_pk}")
def update_template(
    template_pk: int,
    template_id: str = Form(...),
    template_name: str = Form(...),
    label_size: str = Form(""),
    has_logo: bool = Form(False),
    category: str = Form(""),
    bartender_file_path: str = Form(...),
    printer_name: str = Form(""),
    required_fields: str = Form(""),
    active_status: bool = Form(False),
    db: Session = Depends(get_db),
):
    template = db.get(TemplateMaster, template_pk)
    if not template:
        return RedirectResponse("/templates", status_code=303)

    template.template_id = template_id.strip()
    template.template_name = template_name.strip()
    template.label_size = label_size.strip() or None
    template.has_logo = has_logo
    template.category = category.strip() or None
    template.bartender_file_path = bartender_file_path.strip()
    template.printer_name = printer_name.strip() or None
    template.required_fields = required_fields.strip() or None
    template.active_status = active_status
    db.add(template)
    db.commit()
    return RedirectResponse("/templates", status_code=303)


@router.post("/{template_pk}/deactivate")
def deactivate_template(template_pk: int, db: Session = Depends(get_db)):
    template = db.get(TemplateMaster, template_pk)
    if template:
        template.active_status = False
        db.add(template)
        db.commit()
    return RedirectResponse("/templates", status_code=303)


@router.post("/{template_pk}/activate")
def activate_template(template_pk: int, db: Session = Depends(get_db)):
    template = db.get(TemplateMaster, template_pk)
    if template:
        template.active_status = True
        db.add(template)
        db.commit()
    return RedirectResponse("/templates", status_code=303)
