from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import BARTENDER_TEMPLATES_DIR, TEMPLATES_DIR
from app.db import get_db
from app.models import TemplateMaster
from app.services.bartender_activex_service import BarTenderActiveXError, extract_named_substrings
from app.services.field_config import (
    SUPPORTED_FIELD_NAMES,
    SUPPORTED_FIELDS,
    field_label,
    format_required_fields,
    merge_required_fields,
    parse_required_fields,
)
from app.services.template_folder_service import (
    folder_template_options,
    scan_bartender_template_folder,
    template_path_exists,
)


router = APIRouter(prefix="/templates", tags=["templates"])
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
CATEGORY_CHOICES = [
    {"value": "", "label": "All categories"},
    {"value": "clothes", "label": "Clothes"},
    {"value": "cosmetics", "label": "Cosmetics"},
    {"value": "gifts", "label": "Gifts"},
    {"value": "toys", "label": "Toys"},
]


def _field_badges(required_fields: str | None) -> list[dict[str, str]]:
    return [
        {"name": field, "label": field_label(field)}
        for field in parse_required_fields(required_fields)
    ]


def _template_status(template: TemplateMaster) -> dict[str, str]:
    has_file = template_path_exists(template)
    has_fields = bool(parse_required_fields(template.required_fields))
    if not template.active_status:
        return {"kind": "muted", "label": "inactive", "detail": "Not shown for new labels."}
    if not has_file:
        return {"kind": "warn", "label": "missing file", "detail": "Fix the .btw path on this PC."}
    if not has_fields:
        return {"kind": "warn", "label": "needs fields", "detail": "Extract fields before using it."}
    return {"kind": "ok", "label": "ready", "detail": "Usable in New Stock."}


@router.get("/", response_class=HTMLResponse)
def list_templates(
    request: Request,
    edit_id: int | None = None,
    imported: int | None = None,
    skipped: int | None = None,
    extracted: str | None = None,
    extract_error: str | None = None,
    db: Session = Depends(get_db),
):
    scan_result = scan_bartender_template_folder(db)
    template_rows = db.execute(
        select(TemplateMaster).order_by(TemplateMaster.active_status.desc(), TemplateMaster.template_name)
    ).scalars().all()
    template = db.get(TemplateMaster, edit_id) if edit_id else None
    message = None
    if imported is not None and skipped is not None:
        message = f"Imported {imported} template file(s), skipped {skipped} existing file(s)."
    elif scan_result.imported:
        message = f"Found and imported {scan_result.imported} BarTender template file(s)."
    if extracted:
        message = f"Extracted fields: {extracted}"

    selected_fields = parse_required_fields(template.required_fields if template else "")
    advanced_fields = [
        field for field in selected_fields if field not in SUPPORTED_FIELD_NAMES
    ]
    row_field_maps = {row.id: _field_badges(row.required_fields) for row in template_rows}
    row_status = {row.id: _template_status(row) for row in template_rows}
    folder_options = folder_template_options()
    selected_template_path = template.bartender_file_path if template else ""
    selected_path_in_folder = any(
        option["path"] == selected_template_path for option in folder_options
    )

    return templates.TemplateResponse(
        request,
        "templates.html",
        {
            "request": request,
            "template_rows": template_rows,
            "template": template,
            "bartender_templates_dir": BARTENDER_TEMPLATES_DIR,
            "folder_template_options": folder_options,
            "selected_template_path": selected_template_path,
            "selected_path_in_folder": selected_path_in_folder,
            "category_choices": CATEGORY_CHOICES,
            "message": message,
            "error": extract_error,
            "supported_fields": SUPPORTED_FIELDS,
            "selected_required_fields": selected_fields,
            "advanced_required_fields": ",".join(advanced_fields),
            "row_field_maps": row_field_maps,
            "row_status": row_status,
            "template_path_exists": template_path_exists,
            "ready_count": sum(1 for row in template_rows if _template_status(row)["label"] == "ready"),
            "missing_count": sum(1 for row in template_rows if _template_status(row)["label"] == "missing file"),
            "unmapped_count": sum(1 for row in template_rows if _template_status(row)["label"] == "needs fields"),
        },
    )


@router.post("/")
def create_template(
    template_id: str = Form(...),
    template_name: str = Form(...),
    label_size: str = Form(""),
    has_logo: bool = Form(False),
    category: str = Form(""),
    bartender_file_path: str = Form(""),
    manual_bartender_file_path: str = Form(""),
    printer_name: str = Form(""),
    required_field_names: list[str] = Form(default=[]),
    raw_required_fields: str = Form(""),
    active_status: bool = Form(False),
    db: Session = Depends(get_db),
):
    final_bartender_file_path = manual_bartender_file_path.strip() or bartender_file_path.strip()
    if not final_bartender_file_path:
        return RedirectResponse(
            f"/templates?{urlencode({'extract_error': 'Choose a BarTender .btw file from the folder, or enter an advanced path.'})}",
            status_code=303,
        )

    required_fields = merge_required_fields(required_field_names, raw_required_fields)
    template = TemplateMaster(
        template_id=template_id.strip(),
        template_name=template_name.strip(),
        label_size=label_size.strip() or None,
        has_logo=has_logo,
        category=category.strip() or None,
        bartender_file_path=final_bartender_file_path,
        printer_name=printer_name.strip() or None,
        required_fields=required_fields.strip() or None,
        active_status=active_status,
    )
    db.add(template)
    db.commit()
    return RedirectResponse("/templates", status_code=303)


@router.post("/import-folder")
def import_bartender_templates(db: Session = Depends(get_db)):
    scan_result = scan_bartender_template_folder(db)
    return RedirectResponse(
        f"/templates?imported={scan_result.imported}&skipped={scan_result.skipped}",
        status_code=303,
    )


@router.post("/{template_pk}/extract-fields")
def extract_template_fields(
    template_pk: int,
    return_to: str = Form("templates"),
    db: Session = Depends(get_db),
):
    template = db.get(TemplateMaster, template_pk)
    if not template:
        return RedirectResponse(
            f"/templates?{urlencode({'extract_error': 'Template was not found.'})}",
            status_code=303,
        )

    try:
        fields = extract_named_substrings(template.bartender_file_path)
    except BarTenderActiveXError as exc:
        query = {"extract_error": str(exc)}
        if return_to == "edit":
            query["edit_id"] = str(template.id)
        return RedirectResponse(
            f"/templates?{urlencode(query)}",
            status_code=303,
        )

    template.required_fields = format_required_fields(fields)
    db.add(template)
    db.commit()
    extracted = ", ".join(fields)
    query = {"extracted": extracted}
    if return_to == "edit":
        query["edit_id"] = str(template.id)
    return RedirectResponse(
        f"/templates?{urlencode(query)}",
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
    bartender_file_path: str = Form(""),
    manual_bartender_file_path: str = Form(""),
    printer_name: str = Form(""),
    required_field_names: list[str] = Form(default=[]),
    raw_required_fields: str = Form(""),
    active_status: bool = Form(False),
    db: Session = Depends(get_db),
):
    template = db.get(TemplateMaster, template_pk)
    if not template:
        return RedirectResponse("/templates", status_code=303)

    final_bartender_file_path = manual_bartender_file_path.strip() or bartender_file_path.strip()
    if not final_bartender_file_path:
        return RedirectResponse(
            f"/templates?{urlencode({'edit_id': template.id, 'extract_error': 'Choose a BarTender .btw file from the folder, or enter an advanced path.'})}",
            status_code=303,
        )

    template.template_id = template_id.strip()
    template.template_name = template_name.strip()
    template.label_size = label_size.strip() or None
    template.has_logo = has_logo
    template.category = category.strip() or None
    template.bartender_file_path = final_bartender_file_path
    template.printer_name = printer_name.strip() or None
    template.required_fields = merge_required_fields(required_field_names, raw_required_fields) or None
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
