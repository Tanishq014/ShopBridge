from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import TEMPLATES_DIR
from app.db import get_db
from app.models import TemplateMaster


router = APIRouter(prefix="/templates", tags=["templates"])
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


@router.get("/", response_class=HTMLResponse)
def list_templates(
    request: Request,
    edit_id: int | None = None,
    db: Session = Depends(get_db),
):
    template_rows = db.execute(
        select(TemplateMaster).order_by(TemplateMaster.active_status.desc(), TemplateMaster.template_name)
    ).scalars().all()
    template = db.get(TemplateMaster, edit_id) if edit_id else None
    return templates.TemplateResponse(
        request,
        "templates.html",
        {
            "request": request,
            "template_rows": template_rows,
            "template": template,
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
