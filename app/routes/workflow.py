from __future__ import annotations

from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.config import PREVIEWS_DIR, TEMPLATES_DIR
from app.db import get_db
from app.models import LabelVariant, PrintJob, TemplateMaster
from app.services.barcode_service import generate_configured_barcode
from app.services.bartender_activex_service import (
    BarTenderActiveXError,
    export_print_preview_to_image,
)
from app.services.field_config import parse_required_fields
from app.services.settings_service import (
    get_bartender_settings,
    save_barcode_settings,
    save_bartender_settings,
    save_price_code_settings,
    save_pricing_settings,
)
from app.services.template_folder_service import template_path_exists
from app.services.template_preview_service import cached_template_preview_path
from app.services.template_filters import register_template_filters
from app.services.workflow.context_service import workflow_context
from app.services.workflow.form_state_service import variant_template_id as _variant_template_id
from app.services.workflow.preview_service import (
    form_field_values as _form_field_values,
    refresh_cached_preview_error as _refresh_cached_preview_error,
)
from app.services.workflow.page_context_service import (
    item_detail_context,
    recent_prints_context,
    reports_context,
    settings_context,
)
from app.services.workflow.print_orchestration_service import (
    PrintNewStockInput,
    WorkflowPrintError,
    process_new_stock_print,
)
from app.services.workflow.print_service import (
    create_print_job as _create_print_job,
    new_stock_print_redirect_url,
)
from app.services.workflow.template_field_service import extract_and_save_template_fields
from app.services.workflow.validation_service import (
    int_or_none as _int_or_none,
)


router = APIRouter(tags=["workflow"])
templates = register_template_filters(Jinja2Templates(directory=str(TEMPLATES_DIR)))

CATEGORY_CHOICES = [
    {"value": "clothes", "label": "Clothes"},
    {"value": "cosmetics", "label": "Cosmetics"},
    {"value": "gifts", "label": "Gifts"},
    {"value": "toys", "label": "Toys"},
]


def _print_redirect(job: PrintJob, template: TemplateMaster, category: str = "clothes") -> RedirectResponse:
    return RedirectResponse(new_stock_print_redirect_url(job, template, category), status_code=303)


def _phone_print_redirect_url(job: PrintJob, template: TemplateMaster, category: str = "clothes") -> str:
    query: dict[str, object] = {
        "printed": job.id,
        "template_id": template.id,
        "category": category,
        "load_variant_id": job.variant_id,
    }
    if job.status == "failed" and job.error_message:
        query["print_error"] = job.error_message
    return f"/phone-print?{urlencode(query)}"


def _print_status_message(db: Session, printed: int | None) -> str | None:
    if not printed:
        return None
    job = db.get(PrintJob, printed)
    if job and job.status == "printed":
        return f"Print job #{printed} sent to BarTender."
    if job and job.status == "pending":
        return f"CSV print job #{printed} created."
    if job and job.status == "failed":
        return f"Print job #{printed} failed. CSV fallback may be available."
    return f"Print job #{printed} created."


def _workflow_context(
    request: Request,
    db: Session,
    message: str | None = None,
    warning: str | None = None,
    error: str | None = None,
    pricing_fields_visible: bool = True,
    selected_template_id: int | None = None,
    selected_category: str = "clothes",
    initial_variant_id: int | None = None,
    initial_duplicate: bool = False,
    initial_barcode: str = "",
) -> dict[str, object]:
    return workflow_context(
        request,
        db,
        category_choices=CATEGORY_CHOICES,
        message=message,
        warning=warning,
        error=error,
        pricing_fields_visible=pricing_fields_visible,
        selected_template_id=selected_template_id,
        selected_category=selected_category,
        initial_variant_id=initial_variant_id,
        initial_duplicate=initial_duplicate,
        initial_barcode=initial_barcode,
    )


def _phone_print_context(
    request: Request,
    db: Session,
    message: str | None = None,
    warning: str | None = None,
    error: str | None = None,
    pricing_fields_visible: bool = True,
    selected_template_id: int | None = None,
    selected_category: str = "clothes",
    initial_variant_id: int | None = None,
    initial_barcode: str = "",
    submitted_values: dict[str, object] | None = None,
) -> dict[str, object]:
    context = _workflow_context(
        request,
        db,
        message=message,
        warning=warning,
        error=error,
        pricing_fields_visible=pricing_fields_visible,
        selected_template_id=selected_template_id,
        selected_category=selected_category,
        initial_variant_id=initial_variant_id,
        initial_barcode=initial_barcode,
    )
    context["submitted_values"] = submitted_values or {}
    return context


@router.get("/new-stock", response_class=HTMLResponse)
def new_stock(
    request: Request,
    printed: int | None = None,
    template_id: int | None = None,
    category: str = "clothes",
    extracted: str | None = None,
    extract_error: str | None = None,
    preview_warning: str | None = None,
    print_error: str | None = None,
    open_error: str | None = None,
    load_variant_id: int | None = None,
    duplicate_variant_id: int | None = None,
    barcode: str = "",
    db: Session = Depends(get_db),
):
    message = None
    if printed:
        job = db.get(PrintJob, printed)
        if job and job.status == "printed":
            message = f"Print job #{printed} sent to BarTender."
        elif job and job.status == "pending":
            message = f"CSV print job #{printed} created."
        elif job and job.status == "failed":
            message = f"Print job #{printed} failed. CSV fallback may be available."
        else:
            message = f"Print job #{printed} created."
    if extracted:
        message = f"Extracted fields: {extracted}"
    return templates.TemplateResponse(
        request,
        "workflow.html",
        _workflow_context(
            request,
            db,
            message=message,
            warning=preview_warning,
            error=print_error or extract_error or open_error,
            selected_template_id=template_id,
            selected_category=category,
            initial_variant_id=duplicate_variant_id or load_variant_id,
            initial_duplicate=bool(duplicate_variant_id),
            initial_barcode=barcode,
        ),
    )


@router.get("/phone-print", response_class=HTMLResponse)
def phone_print(
    request: Request,
    printed: int | None = None,
    template_id: int | None = None,
    category: str = "clothes",
    print_error: str | None = None,
    load_variant_id: int | None = None,
    barcode: str = "",
    db: Session = Depends(get_db),
):
    return templates.TemplateResponse(
        request,
        "phone_print.html",
        _phone_print_context(
            request,
            db,
            message=_print_status_message(db, printed),
            error=print_error,
            selected_template_id=template_id,
            selected_category=category,
            initial_variant_id=load_variant_id,
            initial_barcode=barcode,
        ),
    )


@router.post("/new-stock/extract-fields")
def extract_workflow_template_fields(
    template_id: int = Form(...),
    category: str = Form("clothes"),
    db: Session = Depends(get_db),
):
    template = db.get(TemplateMaster, template_id)
    if not template:
        return RedirectResponse(
            f"/new-stock?{urlencode({'category': category, 'extract_error': 'Template was not found.'})}",
            status_code=303,
        )

    try:
        extracted = extract_and_save_template_fields(db, template)
    except BarTenderActiveXError as exc:
        return RedirectResponse(
            f"/new-stock?{urlencode({'template_id': template.id, 'category': category, 'extract_error': str(exc)})}",
            status_code=303,
        )

    query = {"template_id": template.id, "category": category, "extracted": extracted}
    preview_error = _refresh_cached_preview_error(template)
    if preview_error:
        query["preview_warning"] = preview_error
    return RedirectResponse(
        f"/new-stock?{urlencode(query)}",
        status_code=303,
    )


@router.get("/new-stock/template-preview/{template_id}")
def cached_template_preview_image(template_id: int, db: Session = Depends(get_db)):
    template = db.get(TemplateMaster, template_id)
    if not template or not template.active_status:
        return JSONResponse({"error": "Template preview was not found."}, status_code=404)
    path = cached_template_preview_path(template)
    if not path.is_file():
        return JSONResponse({"error": "Template preview has not been cached yet."}, status_code=404)
    return FileResponse(path, media_type="image/png", filename=path.name)


@router.post("/new-stock/preview-image")
def preview_template_image(
    template_id: int = Form(...),
    barcode: str = Form(""),
    brand: str = Form(""),
    item_display_name: str = Form(""),
    family_name: str = Form(""),
    article_no: str = Form(""),
    size: str = Form(""),
    batch_no: str = Form(""),
    expiry: str = Form(""),
    mrp: str = Form(""),
    selling_price: str = Form(""),
    margin_percent: str = Form(""),
    coded_price: str = Form(""),
    extra_field_values: str = Form(""),
    db: Session = Depends(get_db),
):
    template = db.get(TemplateMaster, template_id)
    if not template or not template.active_status:
        return JSONResponse({"error": "Select an active template."}, status_code=400)
    if not template_path_exists(template):
        return JSONResponse({"error": "Selected template file is missing on this PC."}, status_code=400)
    if not parse_required_fields(template.required_fields):
        return JSONResponse({"error": "Extract fields for this template before generating a preview."}, status_code=400)

    values = _form_field_values(
        db,
        template,
        barcode=barcode,
        brand=brand,
        item_display_name=item_display_name,
        family_name=family_name,
        article_no=article_no,
        size=size,
        batch_no=batch_no,
        expiry=expiry,
        mrp=mrp,
        selling_price=selling_price,
        coded_price=coded_price,
        extra_field_values=extra_field_values,
    )
    try:
        path = export_print_preview_to_image(
            template.bartender_file_path,
            values,
            PREVIEWS_DIR,
            visible=get_bartender_settings().show_bartender_window,
        )
    except BarTenderActiveXError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    return FileResponse(path, media_type="image/png", filename=path.name)


@router.post("/new-stock/generate-barcode")
def generate_new_stock_barcode(
    template_id: int = Form(...),
    db: Session = Depends(get_db),
):
    template = db.get(TemplateMaster, template_id)
    if not template or not template.active_status:
        return JSONResponse({"error": "Select an active template before generating a barcode."}, status_code=400)
    try:
        barcode = generate_configured_barcode(db, template=template)
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    return {"barcode": barcode, "length": len(barcode)}


@router.post("/new-stock/print", response_class=HTMLResponse)
def print_new_stock(
    request: Request,
    workflow_mode: str = Form("print"),
    existing_variant_id: str = Form(""),
    family_id: str = Form(""),
    family_name: str = Form(""),
    category: str = Form("clothes"),
    barcode: str = Form(""),
    brand: str = Form(""),
    item_display_name: str = Form(""),
    article_no: str = Form(""),
    size: str = Form(""),
    batch_no: str = Form(""),
    expiry: str = Form(""),
    mrp: str = Form(""),
    selling_price: str = Form(""),
    margin_percent: str = Form(""),
    coded_price: str = Form(""),
    coded_price_manual_override: bool = Form(False),
    extra_field_values: str = Form(""),
    selected_price_code_key: str = Form(""),
    print_without_billing_price: bool = Form(False),
    show_pricing_fields_visible: str = Form("1"),
    force_new_barcode: bool = Form(False),
    template_id: int = Form(...),
    copies: int = Form(1),
    manual_barcode_override: bool = Form(False),
    db: Session = Depends(get_db),
):
    pricing_fields_visible = str(show_pricing_fields_visible).strip().lower() not in {"0", "false", "off", "no"}
    def workflow_error_response(message: str, status_code: int = 400):
        return templates.TemplateResponse(
            request,
            "workflow.html",
            _workflow_context(
                request,
                db,
                error=message,
                pricing_fields_visible=pricing_fields_visible,
                selected_template_id=template_id,
                selected_category=category,
            ),
            status_code=status_code,
        )

    try:
        result = process_new_stock_print(
            db,
            PrintNewStockInput(
                workflow_mode=workflow_mode,
                existing_variant_id=existing_variant_id,
                family_id=family_id,
                family_name=family_name,
                category=category,
                barcode=barcode,
                brand=brand,
                item_display_name=item_display_name,
                article_no=article_no,
                size=size,
                batch_no=batch_no,
                expiry=expiry,
                mrp=mrp,
                selling_price=selling_price,
                coded_price=coded_price,
                extra_field_values=extra_field_values,
                selected_price_code_key=selected_price_code_key,
                print_without_billing_price=print_without_billing_price,
                force_new_barcode=force_new_barcode,
                template_id=template_id,
                copies=copies,
                manual_barcode_override=manual_barcode_override,
            ),
        )
    except WorkflowPrintError as exc:
        return workflow_error_response(exc.message, status_code=exc.status_code)

    return _print_redirect(result.job, result.template, result.category)


@router.post("/phone-print/print", response_class=HTMLResponse)
def phone_print_new_stock(
    request: Request,
    workflow_mode: str = Form("print"),
    existing_variant_id: str = Form(""),
    family_id: str = Form(""),
    family_name: str = Form(""),
    category: str = Form("clothes"),
    barcode: str = Form(""),
    brand: str = Form(""),
    item_display_name: str = Form(""),
    article_no: str = Form(""),
    size: str = Form(""),
    batch_no: str = Form(""),
    expiry: str = Form(""),
    mrp: str = Form(""),
    selling_price: str = Form(""),
    margin_percent: str = Form(""),
    coded_price: str = Form(""),
    coded_price_manual_override: bool = Form(False),
    extra_field_values: str = Form(""),
    selected_price_code_key: str = Form(""),
    print_without_billing_price: bool = Form(False),
    show_pricing_fields_visible: str = Form("1"),
    force_new_barcode: bool = Form(False),
    template_id: int = Form(...),
    copies: int = Form(1),
    manual_barcode_override: bool = Form(False),
    db: Session = Depends(get_db),
):
    pricing_fields_visible = str(show_pricing_fields_visible).strip().lower() not in {"0", "false", "off", "no"}
    submitted_values = {
        "workflow_mode": workflow_mode,
        "existing_variant_id": existing_variant_id,
        "family_id": family_id,
        "family_name": family_name,
        "category": category,
        "barcode": barcode,
        "brand": brand,
        "item_display_name": item_display_name,
        "article_no": article_no,
        "size": size,
        "batch_no": batch_no,
        "expiry": expiry,
        "mrp": mrp,
        "selling_price": selling_price,
        "margin_percent": margin_percent,
        "coded_price": coded_price,
        "coded_price_manual_override": coded_price_manual_override,
        "extra_field_values": extra_field_values,
        "selected_price_code_key": selected_price_code_key,
        "print_without_billing_price": print_without_billing_price,
        "show_pricing_fields_visible": show_pricing_fields_visible,
        "force_new_barcode": force_new_barcode,
        "template_id": template_id,
        "copies": copies,
        "manual_barcode_override": manual_barcode_override,
    }
    try:
        result = process_new_stock_print(
            db,
            PrintNewStockInput(
                workflow_mode=workflow_mode,
                existing_variant_id=existing_variant_id,
                family_id=family_id,
                family_name=family_name,
                category=category,
                barcode=barcode,
                brand=brand,
                item_display_name=item_display_name,
                article_no=article_no,
                size=size,
                batch_no=batch_no,
                expiry=expiry,
                mrp=mrp,
                selling_price=selling_price,
                coded_price=coded_price,
                extra_field_values=extra_field_values,
                selected_price_code_key=selected_price_code_key,
                print_without_billing_price=print_without_billing_price,
                force_new_barcode=force_new_barcode,
                template_id=template_id,
                copies=copies,
                manual_barcode_override=manual_barcode_override,
            ),
        )
    except WorkflowPrintError as exc:
        return templates.TemplateResponse(
            request,
            "phone_print.html",
            _phone_print_context(
                request,
                db,
                error=exc.message,
                pricing_fields_visible=pricing_fields_visible,
                selected_template_id=template_id,
                selected_category=category,
                submitted_values=submitted_values,
            ),
            status_code=exc.status_code,
        )

    return RedirectResponse(_phone_print_redirect_url(result.job, result.template, result.category), status_code=303)


@router.post("/new-stock/quick-reprint")
def quick_reprint(
    variant_id: int = Form(...),
    template_id: str = Form(""),
    copies: int = Form(1),
    db: Session = Depends(get_db),
):
    variant = db.get(LabelVariant, variant_id)
    if not variant:
        return RedirectResponse("/new-stock", status_code=303)

    selected_template_id = _int_or_none(template_id) or _variant_template_id(variant)
    template = db.get(TemplateMaster, selected_template_id) if selected_template_id else None
    if not template or not template.active_status:
        return RedirectResponse("/new-stock", status_code=303)
    if not template_path_exists(template) or not parse_required_fields(template.required_fields):
        return RedirectResponse("/new-stock", status_code=303)

    job = _create_print_job(db, variant, template, copies)
    return _print_redirect(job, template, variant.family.category or "clothes")


@router.get("/items/{variant_id}", response_class=HTMLResponse)
def item_detail(variant_id: int, request: Request, db: Session = Depends(get_db)):
    variant = db.get(LabelVariant, variant_id)
    if not variant:
        return RedirectResponse("/new-stock", status_code=303)
    return templates.TemplateResponse(
        request,
        "item_detail.html",
        item_detail_context(request, db, variant),
    )


@router.post("/items/{variant_id}/reprint")
def item_reprint(
    variant_id: int,
    copies: int = Form(1),
    db: Session = Depends(get_db),
):
    variant = db.get(LabelVariant, variant_id)
    if not variant:
        return RedirectResponse("/new-stock", status_code=303)
    selected_template_id = _variant_template_id(variant)
    template = db.get(TemplateMaster, selected_template_id) if selected_template_id else None
    if not template or not template.active_status:
        return RedirectResponse(f"/items/{variant.id}", status_code=303)
    job = _create_print_job(db, variant, template, copies)
    return RedirectResponse(f"/items/{variant.id}?printed={job.id}", status_code=303)


@router.get("/recent-prints", response_class=HTMLResponse)
def recent_prints(request: Request, db: Session = Depends(get_db)):
    return templates.TemplateResponse(
        request,
        "recent_prints.html",
        recent_prints_context(request, db),
    )


@router.post("/recent-prints/{job_id}/reprint")
def reprint_job(job_id: int, db: Session = Depends(get_db)):
    old_job = db.get(PrintJob, job_id)
    if old_job and old_job.variant and old_job.template:
        job = _create_print_job(db, old_job.variant, old_job.template, old_job.copies)
        return _print_redirect(job, old_job.template, old_job.variant.family.category or "clothes")
    return RedirectResponse("/recent-prints", status_code=303)


@router.get("/reports", response_class=HTMLResponse)
def reports(request: Request, db: Session = Depends(get_db)):
    return templates.TemplateResponse(
        request,
        "reports.html",
        reports_context(request, db),
    )


@router.get("/settings", response_class=HTMLResponse)
def settings(
    request: Request,
    settings_saved: int | None = None,
    settings_error: str | None = None,
    db: Session = Depends(get_db),
):
    return templates.TemplateResponse(
        request,
        "settings.html",
        settings_context(
            request,
            db,
            settings_saved=settings_saved,
            settings_error=settings_error,
        ),
    )


@router.post("/settings/bartender")
def update_bartender_settings(
    mode: str = Form("activex"),
    show_bartender_window: bool = Form(False),
    barcode_generation_mode: str = Form("template_length_safe_alphanumeric"),
    default_barcode_length: int = Form(7),
    barcode_allowed_chars: str = Form("23456789BFGJKLMQRUVWXY"),
    mrp_rounding: int = Form(9),
    mrp_truncate_decimal: bool = Form(False),
    allow_price_code_extraction: bool = Form(False),
    digit_0_code: str = Form(""),
    digit_1_code: str = Form(""),
    digit_2_code: str = Form(""),
    digit_3_code: str = Form(""),
    digit_4_code: str = Form(""),
    digit_5_code: str = Form(""),
    digit_6_code: str = Form(""),
    digit_7_code: str = Form(""),
    digit_8_code: str = Form(""),
    digit_9_code: str = Form(""),
    db: Session = Depends(get_db),
):
    try:
        save_price_code_settings(
            digit_to_code={
                "0": digit_0_code,
                "1": digit_1_code,
                "2": digit_2_code,
                "3": digit_3_code,
                "4": digit_4_code,
                "5": digit_5_code,
                "6": digit_6_code,
                "7": digit_7_code,
                "8": digit_8_code,
                "9": digit_9_code,
            },
            allow_extraction=allow_price_code_extraction,
        )
    except ValueError as exc:
        return RedirectResponse(f"/settings?{urlencode({'settings_error': str(exc)})}", status_code=303)
    save_bartender_settings(
        mode=mode,
        show_bartender_window=show_bartender_window,
    )
    save_barcode_settings(
        generation_mode=barcode_generation_mode,
        default_length=default_barcode_length,
        allowed_chars=barcode_allowed_chars,
    )
    save_pricing_settings(mrp_rounding=mrp_rounding, mrp_truncate_decimal=mrp_truncate_decimal)
    return RedirectResponse("/settings?settings_saved=1", status_code=303)
