from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import BARTENDER_TEMPLATES_DIR, TEMPLATES_DIR
from app.db import get_db
from app.models import TemplateMaster
from app.services.bartender_activex_service import BarTenderActiveXError, extract_named_substring_values
from app.services.field_config import (
    SUPPORTED_FIELD_NAMES,
    SUPPORTED_FIELDS,
    field_label,
    format_field_defaults,
    format_required_fields,
    merge_required_fields,
    parse_field_defaults,
    parse_required_fields,
)
from app.services.template_folder_service import (
    folder_template_options,
    scan_bartender_template_folder,
    template_path_exists,
)
from app.services.settings_service import get_bartender_settings
from app.services.template_preview_service import (
    cached_template_preview_url,
    refresh_cached_template_preview,
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


def _row_field_default_badges(template: TemplateMaster) -> list[dict[str, str]]:
    active_fields = set(parse_required_fields(template.required_fields))
    if "article" in active_fields:
        active_fields.add("article_no")
    if "article_no" in active_fields:
        active_fields.add("article")
    defaults = parse_field_defaults(template.default_field_values)
    return [
        {"name": field, "label": field_label(field), "value": value}
        for field, value in defaults.items()
        if value and (field in active_fields or (field == "article_no" and "article" in active_fields))
    ]


def _submitted_field_defaults(
    *,
    active_fields: list[str] | None,
    default_brand: str = "",
    default_item_display_name: str = "",
    default_family_name: str = "",
    default_barcode: str = "",
    default_article: str = "",
    default_size: str = "",
    default_batch_no: str = "",
    default_expiry: str = "",
    default_mrp: str = "",
    default_selling_price: str = "",
    default_coded_price: str = "",
    existing_defaults: str | None = None,
) -> str:
    active_field_set = set(active_fields or [])
    if "article" in active_field_set:
        active_field_set.add("article_no")
    if "article_no" in active_field_set:
        active_field_set.add("article")
    values = {
        "brand": default_brand,
        "item_display_name": default_item_display_name,
        "family_name": default_family_name,
        "barcode": default_barcode,
        "article": default_article,
        "size": default_size,
        "batch_no": default_batch_no,
        "expiry": default_expiry,
        "mrp": default_mrp,
        "selling_price": default_selling_price,
        "coded_price": default_coded_price,
    }
    defaults = {
        field: value.strip()
        for field, value in values.items()
        if value.strip() and field in active_field_set
    }
    for field, value in parse_field_defaults(existing_defaults).items():
        if field not in SUPPORTED_FIELD_NAMES and field in active_field_set and value:
            defaults[field] = value
    return format_field_defaults(defaults)


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


def _refresh_cached_preview_error(template: TemplateMaster) -> str | None:
    try:
        refresh_cached_template_preview(
            template,
            visible=get_bartender_settings().show_bartender_window,
        )
    except BarTenderActiveXError as exc:
        return f"Template fields were saved. Raw preview was not cached: {exc}"
    except Exception as exc:
        return f"Template fields were saved. Raw preview was not cached: {exc}"
    return None


@router.get("/", response_class=HTMLResponse)
def list_templates(
    request: Request,
    edit_id: int | None = None,
    imported: int | None = None,
    skipped: int | None = None,
    extracted: str | None = None,
    extract_error: str | None = None,
    preview_warning: str | None = None,
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
    row_default_maps = {row.id: _row_field_default_badges(row) for row in template_rows}
    row_status = {row.id: _template_status(row) for row in template_rows}
    row_preview_urls = {row.id: cached_template_preview_url(row) for row in template_rows}
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
            "warning": preview_warning,
            "error": extract_error,
            "supported_fields": SUPPORTED_FIELDS,
            "selected_required_fields": selected_fields,
            "advanced_required_fields": ",".join(advanced_fields),
            "selected_default_values": parse_field_defaults(template.default_field_values if template else ""),
            "row_field_maps": row_field_maps,
            "row_default_maps": row_default_maps,
            "row_status": row_status,
            "row_preview_urls": row_preview_urls,
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
    default_brand: str = Form(""),
    default_item_display_name: str = Form(""),
    default_family_name: str = Form(""),
    default_barcode: str = Form(""),
    default_article: str = Form(""),
    default_size: str = Form(""),
    default_batch_no: str = Form(""),
    default_expiry: str = Form(""),
    default_mrp: str = Form(""),
    default_selling_price: str = Form(""),
    default_coded_price: str = Form(""),
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
    required_field_list = parse_required_fields(required_fields)
    template = TemplateMaster(
        template_id=template_id.strip(),
        template_name=template_name.strip(),
        label_size=label_size.strip() or None,
        has_logo=has_logo,
        category=category.strip() or None,
        bartender_file_path=final_bartender_file_path,
        printer_name=printer_name.strip() or None,
        required_fields=required_fields.strip() or None,
        default_field_values=_submitted_field_defaults(
            active_fields=required_field_list,
            default_brand=default_brand,
            default_item_display_name=default_item_display_name,
            default_family_name=default_family_name,
            default_barcode=default_barcode,
            default_article=default_article,
            default_size=default_size,
            default_batch_no=default_batch_no,
            default_expiry=default_expiry,
            default_mrp=default_mrp,
            default_selling_price=default_selling_price,
            default_coded_price=default_coded_price,
        )
        or None,
        active_status=active_status,
    )
    db.add(template)
    db.commit()
    db.refresh(template)
    preview_error = _refresh_cached_preview_error(template)
    if preview_error:
        return RedirectResponse(
            f"/templates?{urlencode({'preview_warning': preview_error})}",
            status_code=303,
        )
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
        field_defaults = extract_named_substring_values(template.bartender_file_path)
    except BarTenderActiveXError as exc:
        query = {"extract_error": str(exc)}
        if return_to == "edit":
            query["edit_id"] = str(template.id)
        return RedirectResponse(
            f"/templates?{urlencode(query)}",
            status_code=303,
        )

    fields = list(field_defaults)
    template.required_fields = format_required_fields(fields)
    template.default_field_values = format_field_defaults(field_defaults) or None
    db.add(template)
    db.commit()
    db.refresh(template)
    extracted = ", ".join(fields)
    query = {"extracted": extracted}
    preview_error = _refresh_cached_preview_error(template)
    if preview_error:
        query["preview_warning"] = preview_error
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
    default_brand: str = Form(""),
    default_item_display_name: str = Form(""),
    default_family_name: str = Form(""),
    default_barcode: str = Form(""),
    default_article: str = Form(""),
    default_size: str = Form(""),
    default_batch_no: str = Form(""),
    default_expiry: str = Form(""),
    default_mrp: str = Form(""),
    default_selling_price: str = Form(""),
    default_coded_price: str = Form(""),
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
    required_fields = merge_required_fields(required_field_names, raw_required_fields)
    required_field_list = parse_required_fields(required_fields)
    template.required_fields = required_fields or None
    template.default_field_values = _submitted_field_defaults(
        active_fields=required_field_list,
        default_brand=default_brand,
        default_item_display_name=default_item_display_name,
        default_family_name=default_family_name,
        default_barcode=default_barcode,
        default_article=default_article,
        default_size=default_size,
        default_batch_no=default_batch_no,
        default_expiry=default_expiry,
        default_mrp=default_mrp,
        default_selling_price=default_selling_price,
        default_coded_price=default_coded_price,
        existing_defaults=template.default_field_values,
    ) or None
    template.active_status = active_status
    db.add(template)
    db.commit()
    db.refresh(template)
    preview_error = _refresh_cached_preview_error(template)
    if preview_error:
        return RedirectResponse(
            f"/templates?{urlencode({'edit_id': template.id, 'preview_warning': preview_error})}",
            status_code=303,
        )
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
