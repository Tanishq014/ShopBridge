from __future__ import annotations

import json
from decimal import Decimal, InvalidOperation
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import PREVIEWS_DIR, TEMPLATES_DIR
from app.db import get_db
from app.models import LabelVariant, PrintJob, ProductFamily, TemplateMaster
from app.services.barcode_service import assign_barcode, generate_configured_barcode, normalize_barcode
from app.services.bartender_activex_service import (
    BarTenderActiveXError,
    export_print_preview_to_image,
    extract_named_substring_values,
)
from app.services.bartender_service import process_print_job
from app.services.field_config import (
    SUPPORTED_FIELDS,
    field_label,
    format_field_defaults,
    format_required_fields,
    normalize_field_name,
    parse_field_defaults,
    parse_required_fields,
)
from app.services.price_code_service import (
    PriceCodeCandidate,
    extract_price_code_candidates,
    generate_coded_price,
)
from app.services.settings_service import (
    get_barcode_settings,
    get_bartender_settings,
    get_price_code_settings,
    get_pricing_settings,
    save_barcode_settings,
    save_bartender_settings,
    save_price_code_settings,
    save_pricing_settings,
)
from app.services.template_folder_service import scan_bartender_template_folder, template_path_exists
from app.services.template_preview_service import (
    cached_template_preview_path,
    cached_template_preview_url,
    refresh_cached_template_preview,
)


router = APIRouter(tags=["workflow"])
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

CATEGORY_CHOICES = [
    {"value": "clothes", "label": "Clothes"},
    {"value": "cosmetics", "label": "Cosmetics"},
    {"value": "gifts", "label": "Gifts"},
    {"value": "toys", "label": "Toys"},
]


def _decimal_or_none(value: str | None) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _int_or_none(value: str | None) -> int | None:
    if value in (None, ""):
        return None
    return int(value)


def _money(value: Decimal | None) -> str:
    if value is None:
        return ""
    return f"{value:.2f}"


def _parse_extra_field_values(value: str | None) -> dict[str, str]:
    if not value:
        return {}
    try:
        raw_values = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return {}
    if not isinstance(raw_values, dict):
        return {}

    values: dict[str, str] = {}
    for field_name, field_value in raw_values.items():
        clean_name = normalize_field_name(str(field_name))
        if not clean_name or field_value is None:
            continue
        values[clean_name] = str(field_value).strip()
    return values


def _format_extra_field_values(values: dict[str, str]) -> str | None:
    clean_values = {
        normalize_field_name(field_name): str(field_value).strip()
        for field_name, field_value in values.items()
        if normalize_field_name(field_name) and str(field_value).strip()
    }
    if not clean_values:
        return None
    return json.dumps(clean_values, ensure_ascii=True, sort_keys=True)


def _candidate_payload(candidate: PriceCodeCandidate) -> dict[str, str]:
    return {
        "key": candidate.key,
        "source_field": candidate.source_field,
        "raw_value": candidate.raw_value,
        "code": candidate.code,
        "selling_price": candidate.selling_price_text,
        "label": (
            f"{field_label(candidate.source_field)}: {candidate.raw_value} "
            f"-> {candidate.code} -> {candidate.selling_price_text}"
        ),
    }


def _find_candidate_by_key(candidates: list[PriceCodeCandidate], key: str) -> PriceCodeCandidate | None:
    for candidate in candidates:
        if candidate.key == key:
            return candidate
    return None


def _active_templates(db: Session) -> list[TemplateMaster]:
    return db.execute(
        select(TemplateMaster)
        .where(TemplateMaster.active_status == True)  # noqa: E712
        .order_by(TemplateMaster.category, TemplateMaster.template_name)
    ).scalars().all()


def _active_families(db: Session) -> list[ProductFamily]:
    return db.execute(
        select(ProductFamily)
        .where(ProductFamily.active_status == True)  # noqa: E712
        .order_by(ProductFamily.category, ProductFamily.family_name)
    ).scalars().all()


def _recent_variants(db: Session, limit: int = 80) -> list[LabelVariant]:
    return db.execute(
        select(LabelVariant)
        .where(LabelVariant.status == "active")
        .order_by(LabelVariant.updated_at.desc(), LabelVariant.id.desc())
        .limit(limit)
    ).scalars().all()


def _variant_template_id(variant: LabelVariant) -> int | None:
    return variant.template_id or variant.family.default_template_id


def _variant_payload(variant: LabelVariant) -> dict[str, object]:
    template = variant.template or variant.family.default_template
    category = (variant.family.category or "").strip().lower()
    return {
        "id": variant.id,
        "search": " | ".join(
            part
            for part in [
                variant.item_display_name,
                variant.brand,
                variant.article_no,
                variant.size,
                variant.barcode,
            ]
            if part
        ),
        "barcode": variant.barcode,
        "family_id": variant.family_id,
        "family_name": variant.family.family_name,
        "category": category,
        "brand": variant.brand or "",
        "item_display_name": variant.item_display_name,
        "article_no": variant.article_no or "",
        "size": variant.size or "",
        "batch_no": variant.batch_no or "",
        "expiry": variant.expiry or "",
        "mrp": _money(variant.mrp),
        "selling_price": _money(variant.selling_price),
        "coded_price": variant.coded_price or "",
        "billing_price_missing": bool(variant.billing_price_missing),
        "extra_field_values": _parse_extra_field_values(variant.extra_field_values),
        "template_id": _variant_template_id(variant) or "",
        "template_name": template.template_name if template else "",
    }


def _template_payload(template: TemplateMaster) -> dict[str, object]:
    field_defaults = parse_field_defaults(template.default_field_values)
    field_defaults.pop("barcode", None)
    return {
        "id": template.id,
        "template_id": template.template_id,
        "template_name": template.template_name,
        "category": (template.category or "").strip().lower(),
        "label_size": template.label_size or "",
        "required_fields": parse_required_fields(template.required_fields),
        "field_defaults": field_defaults,
        "path_exists": template_path_exists(template),
        "cached_preview_url": cached_template_preview_url(template),
        "recent": False,
    }


def _recent_templates(db: Session, template_rows: list[TemplateMaster]) -> list[TemplateMaster]:
    seen: set[int] = set()
    recent: list[TemplateMaster] = []
    jobs = db.execute(
        select(PrintJob).order_by(PrintJob.created_at.desc(), PrintJob.id.desc()).limit(40)
    ).scalars().all()
    for job in jobs:
        if job.template and job.template.active_status and job.template.id not in seen:
            recent.append(job.template)
            seen.add(job.template.id)
        if len(recent) >= 6:
            return recent

    for template in template_rows:
        if template.id not in seen:
            recent.append(template)
            seen.add(template.id)
        if len(recent) >= 6:
            break
    return recent


def _size_values(variants: list[LabelVariant]) -> dict[str, list[str]]:
    values: dict[str, set[str]] = {choice["value"]: set() for choice in CATEGORY_CHOICES}
    for variant in variants:
        category = (variant.family.category or "").strip().lower()
        if category in values and variant.size:
            values[category].add(variant.size)
    return {category: sorted(sizes) for category, sizes in values.items()}


def _find_or_create_family(
    db: Session,
    category: str,
    family_id: int | None,
    family_name: str,
    item_display_name: str,
) -> ProductFamily:
    final_name = (family_name or item_display_name).strip()
    if family_id:
        family = db.get(ProductFamily, family_id)
        if family:
            if final_name and family.family_name.strip().lower() != final_name.lower():
                family_id = None
            else:
                if category and family.category != category:
                    family.category = category
                    db.add(family)
                return family

    if not final_name:
        final_name = item_display_name.strip()

    family = db.scalar(
        select(ProductFamily).where(func.lower(ProductFamily.family_name) == final_name.lower())
    )
    if family:
        if category and family.category != category:
            family.category = category
            family.active_status = True
            db.add(family)
        return family

    family = ProductFamily(
        family_name=final_name,
        tally_stock_item_name=None,
        category=category,
        default_tax_rate=0,
        default_unit="PCS",
        active_status=True,
    )
    db.add(family)
    db.flush()
    return family


def _same_text(left: str | None, right: str | None) -> bool:
    return (left or "").strip().lower() == (right or "").strip().lower()


def _same_money(left: Decimal | None, right: Decimal | None) -> bool:
    if left is None and right is None:
        return True
    if left is None or right is None:
        return False
    return left.quantize(Decimal("0.01")) == right.quantize(Decimal("0.01"))


def _price_changed(
    variant: LabelVariant | None,
    *,
    mrp: Decimal | None,
    selling_price: Decimal | None,
    coded_price: str,
) -> bool:
    if not variant:
        return False
    return (
        not _same_money(variant.mrp, mrp)
        or not _same_money(variant.selling_price, selling_price)
        or not _same_text(variant.coded_price, coded_price)
    )


def _label_details_changed(
    variant: LabelVariant | None,
    *,
    category: str,
    family_name: str,
    template: TemplateMaster,
    brand: str,
    item_display_name: str,
    article_no: str,
    size: str,
    batch_no: str,
    expiry: str,
    extra_field_values: dict[str, str],
    mrp: Decimal | None,
    selling_price: Decimal | None,
    coded_price: str,
) -> bool:
    if not variant:
        return False
    family = variant.family
    return (
        not _same_text(family.category if family else "", category)
        or not _same_text(family.family_name if family else "", family_name)
        or _variant_template_id(variant) != template.id
        or not _same_text(variant.brand, brand)
        or not _same_text(variant.item_display_name, item_display_name)
        or not _same_text(variant.article_no, article_no)
        or not _same_text(variant.size, size)
        or not _same_text(variant.batch_no, batch_no)
        or not _same_text(variant.expiry, expiry)
        or _parse_extra_field_values(variant.extra_field_values) != {
            field_name: field_value
            for field_name, field_value in extra_field_values.items()
            if str(field_value).strip()
        }
        or _price_changed(
            variant,
            mrp=mrp,
            selling_price=selling_price,
            coded_price=coded_price,
        )
    )


def _find_exact_variant(
    db: Session,
    *,
    category: str,
    template: TemplateMaster,
    required_fields: list[str],
    family_name: str,
    item_display_name: str,
    brand: str,
    article_no: str,
    size: str,
    batch_no: str,
    expiry: str,
    extra_field_values: dict[str, str],
    mrp: Decimal | None,
    selling_price: Decimal | None,
    coded_price: str,
) -> LabelVariant | None:
    query = (
        select(LabelVariant)
        .join(ProductFamily)
        .where(LabelVariant.status == "active")
        .where(func.lower(LabelVariant.item_display_name) == item_display_name.strip().lower())
        .where(ProductFamily.category == category)
        .where(LabelVariant.template_id == template.id)
    )
    candidates = db.execute(query).scalars().all()
    required = set(required_fields)

    for candidate in candidates:
        if mrp is not None and not _same_money(candidate.mrp, mrp):
            continue
        if selling_price is not None:
            if not _same_money(candidate.selling_price, selling_price):
                continue
        elif candidate.selling_price is not None:
            continue
        if coded_price.strip():
            if not _same_text(candidate.coded_price, coded_price):
                continue
        elif candidate.coded_price:
            continue
        if family_name.strip() and not _same_text(candidate.family.family_name, family_name):
            continue
        if "brand" in required and brand.strip() and not _same_text(candidate.brand, brand):
            continue
        if ("article" in required or "article_no" in required) and article_no.strip() and not _same_text(candidate.article_no, article_no):
            continue
        if "size" in required and size.strip() and not _same_text(candidate.size, size):
            continue
        if "batch_no" in required and batch_no.strip() and not _same_text(candidate.batch_no, batch_no):
            continue
        if "expiry" in required and expiry.strip() and not _same_text(candidate.expiry, expiry):
            continue
        candidate_extras = _parse_extra_field_values(candidate.extra_field_values)
        extra_mismatch = False
        for field_name, field_value in extra_field_values.items():
            if field_name in required and field_value.strip() and not _same_text(candidate_extras.get(field_name), field_value):
                extra_mismatch = True
                break
        if extra_mismatch:
            continue
        return candidate
    return None


def _create_print_job(
    db: Session,
    variant: LabelVariant,
    template: TemplateMaster,
    copies: int,
) -> PrintJob:
    if not variant.id:
        raise ValueError("Cannot print before the item is saved.")
    if not (variant.barcode or "").strip():
        raise ValueError("Cannot print an item without a barcode.")
    if not template or not template.id:
        raise ValueError("Cannot print without a saved template.")
    if not parse_required_fields(template.required_fields):
        raise ValueError("Cannot print before extracting template fields.")

    job = PrintJob(
        variant_id=variant.id,
        template_id=template.id,
        copies=max(1, copies),
        status="pending",
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    settings = get_bartender_settings()
    try:
        process_print_job(
            db,
            job,
            mode=settings.mode,
            show_bartender_window=settings.show_bartender_window,
        )
    except Exception as exc:
        job.status = "failed"
        job.error_message = f"Print failed before completion: {exc}"[:1800]
        db.add(job)
        db.commit()
    db.refresh(job)
    return job


def _print_redirect(job: PrintJob, template: TemplateMaster, category: str = "clothes") -> RedirectResponse:
    query: dict[str, object] = {
        "printed": job.id,
        "template_id": template.id,
        "category": category,
        "load_variant_id": job.variant_id,
    }
    if job.status == "failed" and job.error_message:
        query["print_error"] = job.error_message
    return RedirectResponse(f"/new-stock?{urlencode(query)}", status_code=303)


def _refresh_cached_preview_error(template: TemplateMaster) -> str | None:
    try:
        refresh_cached_template_preview(
            template,
            visible=get_bartender_settings().show_bartender_window,
        )
    except BarTenderActiveXError as exc:
        return f"Fields were extracted. Raw preview was not cached: {exc}"
    except Exception as exc:
        return f"Fields were extracted. Raw preview was not cached: {exc}"
    return None


def _form_field_values(
    db: Session,
    template: TemplateMaster,
    *,
    barcode: str,
    brand: str,
    item_display_name: str,
    family_name: str,
    article_no: str,
    size: str,
    batch_no: str,
    expiry: str,
    mrp: str,
    selling_price: str,
    coded_price: str,
    extra_field_values: str = "",
) -> dict[str, str]:
    selling = _decimal_or_none(selling_price)
    mrp_value = _decimal_or_none(mrp)
    extras = _parse_extra_field_values(extra_field_values)
    barcode_value = barcode.strip()
    required_fields = parse_required_fields(template.required_fields)
    if not barcode_value and "barcode" in required_fields:
        try:
            barcode_value = generate_configured_barcode(db, template=template)
        except ValueError:
            barcode_value = "manual"

    article_value = article_no.strip()
    item_name_value = item_display_name.strip() or family_name.strip()
    final_family_name = family_name.strip() or item_name_value
    price_code_settings = get_price_code_settings()
    coded = coded_price.strip() or generate_coded_price(selling, price_code_settings) or ""
    standard_values = {
        "barcode": barcode_value,
        "brand": brand.strip(),
        "item_display_name": item_name_value,
        "design": item_name_value,
        "family_name": final_family_name,
        "article": article_value,
        "article_no": article_value,
        "size": size.strip(),
        "batch_no": batch_no.strip(),
        "expiry": expiry.strip(),
        "mrp": _money(mrp_value),
        "selling_price": _money(selling),
        "coded_price": coded,
    }
    standard_values.update(extras)
    return {
        field_name: standard_values.get(field_name, "")
        for field_name in required_fields
    }


def _workflow_context(
    request: Request,
    db: Session,
    message: str | None = None,
    warning: str | None = None,
    error: str | None = None,
    selected_template_id: int | None = None,
    selected_category: str = "clothes",
    initial_variant_id: int | None = None,
    initial_duplicate: bool = False,
) -> dict[str, object]:
    scan_bartender_template_folder(db)
    families = _active_families(db)
    template_rows = _active_templates(db)
    variants = _recent_variants(db)
    recent_jobs = db.execute(
        select(PrintJob).order_by(PrintJob.created_at.desc(), PrintJob.id.desc()).limit(10)
    ).scalars().all()
    recent_template_rows = _recent_templates(db, template_rows)

    template_payloads = [_template_payload(template) for template in template_rows]
    recent_template_ids = {template.id for template in recent_template_rows}
    for template in template_payloads:
        template["recent"] = template["id"] in recent_template_ids

    price_code_settings = get_price_code_settings()
    return {
        "request": request,
        "message": message,
        "warning": warning,
        "error": error,
        "categories": CATEGORY_CHOICES,
        "families": families,
        "template_rows": template_rows,
        "templates_json": template_payloads,
        "variants_json": [_variant_payload(variant) for variant in variants],
        "recent_items": variants[:12],
        "recent_templates": recent_template_rows,
        "recent_jobs": recent_jobs,
        "size_values_json": _size_values(variants),
        "selected_template_id": selected_template_id,
        "selected_category": selected_category,
        "initial_variant_id": initial_variant_id,
        "initial_duplicate": initial_duplicate,
        "pricing_settings": get_pricing_settings(),
        "price_code_settings": price_code_settings,
        "price_code_settings_json": {
            "digit_to_code": price_code_settings.digit_to_code,
            "code_to_digit": price_code_settings.code_to_digit,
            "price_code_letters": price_code_settings.price_code_letters,
            "allow_extraction": price_code_settings.allow_extraction,
        },
        "template_path_exists": template_path_exists,
        "template_warning": (
            "No active template was found. Add one in Settings -> Templates."
            if not template_rows
            else (
                None
                if any(template_path_exists(template) for template in template_rows)
                else "Templates exist, but their .btw file paths are missing on this PC. Fix the path in Settings before extracting fields or printing."
            )
        ),
    }


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
    load_variant_id: int | None = None,
    duplicate_variant_id: int | None = None,
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
            error=print_error or extract_error,
            selected_template_id=template_id,
            selected_category=category,
            initial_variant_id=duplicate_variant_id or load_variant_id,
            initial_duplicate=bool(duplicate_variant_id),
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
        field_defaults = extract_named_substring_values(template.bartender_file_path)
    except BarTenderActiveXError as exc:
        return RedirectResponse(
            f"/new-stock?{urlencode({'template_id': template.id, 'category': category, 'extract_error': str(exc)})}",
            status_code=303,
        )

    fields = list(field_defaults)
    barcode_sample = field_defaults.get("barcode", "").strip()
    default_values = {field: value for field, value in field_defaults.items() if field != "barcode"}
    template.required_fields = format_required_fields(fields)
    template.default_field_values = format_field_defaults(default_values)
    template.barcode_sample_value = barcode_sample or None
    db.add(template)
    db.commit()
    db.refresh(template)
    extracted = ", ".join(fields)
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
    coded_price: str = Form(""),
    extra_field_values: str = Form(""),
    selected_price_code_key: str = Form(""),
    print_without_billing_price: bool = Form(False),
    template_id: int = Form(...),
    copies: int = Form(1),
    manual_barcode_override: bool = Form(False),
    db: Session = Depends(get_db),
):
    template = db.get(TemplateMaster, template_id)
    if not template or not template.active_status:
        return templates.TemplateResponse(
            request,
            "workflow.html",
            _workflow_context(request, db, error="Select an active template."),
            status_code=400,
        )
    if not template_path_exists(template):
        return templates.TemplateResponse(
            request,
            "workflow.html",
            _workflow_context(request, db, error="Selected template file is missing on this PC. Fix it in Settings -> Templates."),
            status_code=400,
        )
    if not parse_required_fields(template.required_fields):
        return templates.TemplateResponse(
            request,
            "workflow.html",
            _workflow_context(request, db, error="Extract fields for the selected template before printing."),
            status_code=400,
        )

    source_variant = db.get(LabelVariant, _int_or_none(existing_variant_id)) if existing_variant_id else None
    if workflow_mode == "quick_reprint":
        if not source_variant:
            return templates.TemplateResponse(
                request,
                "workflow.html",
                _workflow_context(request, db, error="Select an existing item before quick reprint."),
                status_code=400,
        )
        job = _create_print_job(db, source_variant, template, copies)
        return _print_redirect(job, template, category)

    required_fields = parse_required_fields(template.required_fields)
    required_field_set = set(required_fields)

    def field_is_required(field_name: str) -> bool:
        if field_name == "article_no":
            return "article_no" in required_field_set or "article" in required_field_set
        if field_name == "item_display_name":
            return "item_display_name" in required_field_set or "design" in required_field_set
        return field_name in required_field_set

    def value_or_preserved(field_name: str, raw_value: str, attr_name: str | None = None) -> str:
        clean_value = (raw_value or "").strip()
        if clean_value:
            return clean_value
        if source_variant and not field_is_required(field_name):
            stored_value = getattr(source_variant, attr_name or field_name, None)
            return "" if stored_value is None else str(stored_value)
        return ""

    final_category = category.strip().lower()
    final_family_name = family_name.strip() or item_display_name.strip()
    if not final_family_name:
        return templates.TemplateResponse(
            request,
            "workflow.html",
            _workflow_context(request, db, error="Enter an item name."),
            status_code=400,
        )

    brand_value = value_or_preserved("brand", brand)
    item_name_value = (
        item_display_name.strip()
        or value_or_preserved("item_display_name", "", "item_display_name")
        or final_family_name
    )
    article_value = value_or_preserved("article_no", article_no)
    size_value = value_or_preserved("size", size)
    batch_value = value_or_preserved("batch_no", batch_no)
    expiry_value = value_or_preserved("expiry", expiry)
    mrp_value = _decimal_or_none(value_or_preserved("mrp", mrp))
    selling = _decimal_or_none(value_or_preserved("selling_price", selling_price))
    extra_values = _parse_extra_field_values(extra_field_values)
    source_extra_values = _parse_extra_field_values(source_variant.extra_field_values if source_variant else None)
    for field_name, field_value in source_extra_values.items():
        if field_name not in extra_values and source_variant and not field_is_required(field_name):
            extra_values[field_name] = field_value
    coded = coded_price.strip() or value_or_preserved("coded_price", coded_price)

    field_values = {
        "brand": brand_value,
        "item_display_name": item_name_value,
        "design": item_name_value,
        "family_name": final_family_name,
        "article": article_value,
        "article_no": article_value,
        "size": size_value,
        "batch_no": batch_value,
        "expiry": expiry_value,
        "mrp": _money(mrp_value),
        "selling_price": _money(selling),
        "coded_price": coded,
    }
    field_values.update(extra_values)

    price_code_settings = get_price_code_settings()
    price_code_candidates, _priority_code_found = extract_price_code_candidates(
        field_values,
        required_fields,
        price_code_settings,
    )
    selected_candidate = _find_candidate_by_key(price_code_candidates, selected_price_code_key.strip())
    if selected_candidate:
        selling = selected_candidate.selling_price
        coded = selected_candidate.code
    elif selling is None and price_code_candidates:
        if len(price_code_candidates) == 1:
            selected_candidate = price_code_candidates[0]
            selling = selected_candidate.selling_price
            coded = selected_candidate.code
        elif not print_without_billing_price:
            options = "; ".join(candidate["label"] for candidate in map(_candidate_payload, price_code_candidates))
            return templates.TemplateResponse(
                request,
                "workflow.html",
                _workflow_context(
                    request,
                    db,
                    error="Multiple price codes found. Choose one or enter Selling Price manually. " + options,
                ),
                status_code=400,
            )
    elif selling is None and not print_without_billing_price:
        return templates.TemplateResponse(
            request,
            "workflow.html",
            _workflow_context(
                request,
                db,
                error="Enter Selling Price, detect a valid price code, or choose Print without billing price in Advanced barcode.",
            ),
            status_code=400,
        )

    billing_price_missing = selling is None and print_without_billing_price
    if selling is not None and not coded:
        coded = generate_coded_price(selling, price_code_settings) or ""
    field_values["selling_price"] = _money(selling)
    field_values["coded_price"] = coded
    missing_fields = [
        field_label(field_name)
        for field_name in required_fields
        if field_name != "barcode" and not str(field_values.get(field_name, "")).strip()
    ]
    if missing_fields:
        return templates.TemplateResponse(
            request,
            "workflow.html",
            _workflow_context(
                request,
                db,
                error="Required for selected template: " + ", ".join(missing_fields),
            ),
            status_code=400,
        )

    if not source_variant and workflow_mode not in {"duplicate", "new_barcode"}:
        source_variant = _find_exact_variant(
            db,
            category=final_category,
            template=template,
            required_fields=required_fields,
            family_name=final_family_name,
            item_display_name=item_name_value,
            brand=brand_value,
            article_no=article_value,
            size=size_value,
            batch_no=batch_value,
            expiry=expiry_value,
            extra_field_values=extra_values,
            mrp=mrp_value,
            selling_price=selling,
            coded_price=coded,
        )

    family = _find_or_create_family(
        db=db,
        category=final_category,
        family_id=_int_or_none(family_id),
        family_name=final_family_name,
        item_display_name=item_name_value,
    )

    details_changed = _label_details_changed(
        source_variant,
        category=final_category,
        family_name=final_family_name,
        template=template,
        brand=brand_value,
        item_display_name=item_name_value,
        article_no=article_value,
        size=size_value,
        batch_no=batch_value,
        expiry=expiry_value,
        extra_field_values=extra_values,
        mrp=mrp_value,
        selling_price=selling,
        coded_price=coded,
    )
    create_new_barcode = (
        source_variant is None
        or workflow_mode in {"duplicate", "new_barcode"}
        or (details_changed and workflow_mode != "update_existing")
    )
    update_existing = source_variant is not None and not create_new_barcode

    if update_existing:
        variant = source_variant
        requested_barcode = barcode.strip()
        if manual_barcode_override and requested_barcode and requested_barcode != variant.barcode:
            try:
                variant.barcode = assign_barcode(
                    db,
                    requested_barcode,
                    exclude_variant_id=variant.id,
                    template=template,
                )
            except ValueError as exc:
                return templates.TemplateResponse(
                    request,
                    "workflow.html",
                    _workflow_context(request, db, error=str(exc)),
                    status_code=400,
                )
    else:
        requested_barcode = barcode
        if (
            source_variant
            and details_changed
            and not manual_barcode_override
            and normalize_barcode(requested_barcode) == normalize_barcode(source_variant.barcode)
        ):
            requested_barcode = ""
        try:
            final_barcode = assign_barcode(db, requested_barcode, template=template)
        except ValueError as exc:
            return templates.TemplateResponse(
                request,
                "workflow.html",
                _workflow_context(request, db, error=str(exc)),
                status_code=400,
            )
        variant = LabelVariant(
            barcode=final_barcode,
            family_id=family.id,
            item_display_name=item_name_value,
        )

    variant.family_id = family.id
    variant.brand = brand_value or None
    variant.item_display_name = item_name_value
    variant.article_no = article_value or None
    variant.size = size_value or None
    variant.batch_no = batch_value or None
    variant.expiry = expiry_value or None
    variant.mrp = mrp_value
    variant.selling_price = selling
    variant.coded_price = coded or None
    variant.billing_price_missing = billing_price_missing
    variant.extra_field_values = _format_extra_field_values(extra_values)
    variant.template_id = template.id
    variant.status = "active"
    db.add(variant)
    db.commit()
    db.refresh(variant)

    try:
        job = _create_print_job(db, variant, template, copies)
    except Exception as exc:
        return templates.TemplateResponse(
            request,
            "workflow.html",
            _workflow_context(request, db, error=f"Variant saved, but print job failed: {exc}"),
            status_code=500,
        )

    return _print_redirect(job, template, category)


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
    jobs = db.execute(
        select(PrintJob)
        .where(PrintJob.variant_id == variant.id)
        .order_by(PrintJob.created_at.desc(), PrintJob.id.desc())
    ).scalars().all()
    return templates.TemplateResponse(
        request,
        "item_detail.html",
        {
            "request": request,
            "variant": variant,
            "jobs": jobs,
            "category": variant.family.category or "clothes",
            "template_id": _variant_template_id(variant) or "",
        },
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
    jobs = db.execute(
        select(PrintJob).order_by(PrintJob.created_at.desc(), PrintJob.id.desc()).limit(80)
    ).scalars().all()
    return templates.TemplateResponse(
        request,
        "recent_prints.html",
        {
            "request": request,
            "jobs": jobs,
        },
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
    category_rows = db.execute(
        select(ProductFamily.category, func.count(ProductFamily.id))
        .group_by(ProductFamily.category)
        .order_by(ProductFamily.category)
    ).all()
    stats = {
        "families": db.scalar(select(func.count(ProductFamily.id))) or 0,
        "active_variants": db.scalar(
            select(func.count(LabelVariant.id)).where(LabelVariant.status == "active")
        )
        or 0,
        "templates": db.scalar(select(func.count(TemplateMaster.id))) or 0,
        "print_jobs": db.scalar(select(func.count(PrintJob.id))) or 0,
    }
    return templates.TemplateResponse(
        request,
        "reports.html",
        {
            "request": request,
            "stats": stats,
            "category_rows": category_rows,
        },
    )


@router.get("/settings", response_class=HTMLResponse)
def settings(
    request: Request,
    settings_saved: int | None = None,
    db: Session = Depends(get_db),
):
    scan_bartender_template_folder(db)
    template_rows = db.execute(select(TemplateMaster).order_by(TemplateMaster.template_name)).scalars().all()
    active_templates = [template for template in template_rows if template.active_status]
    ready_templates = [
        template
        for template in active_templates
        if template_path_exists(template) and parse_required_fields(template.required_fields)
    ]
    missing_templates = [template for template in active_templates if not template_path_exists(template)]
    unmapped_templates = [
        template
        for template in active_templates
        if template_path_exists(template) and not parse_required_fields(template.required_fields)
    ]
    stats = {
        "templates_total": len(template_rows),
        "templates_ready": len(ready_templates),
        "templates_missing": len(missing_templates),
        "templates_unmapped": len(unmapped_templates),
        "families": db.scalar(select(func.count(ProductFamily.id))) or 0,
        "variants": db.scalar(select(func.count(LabelVariant.id)).where(LabelVariant.status == "active")) or 0,
        "print_jobs": db.scalar(select(func.count(PrintJob.id))) or 0,
    }
    return templates.TemplateResponse(
        request,
        "settings.html",
        {
            "request": request,
            "stats": stats,
            "ready_to_label": bool(ready_templates),
            "bartender_settings": get_bartender_settings(),
            "barcode_settings": get_barcode_settings(),
            "pricing_settings": get_pricing_settings(),
            "price_code_settings": get_price_code_settings(),
            "settings_saved": bool(settings_saved),
        },
    )


@router.post("/settings/bartender")
def update_bartender_settings(
    mode: str = Form("activex"),
    show_bartender_window: bool = Form(False),
    barcode_generation_mode: str = Form("template_length_safe_alphanumeric"),
    default_barcode_length: int = Form(6),
    barcode_allowed_chars: str = Form("23456789BFGJKLMNQRUVWXY"),
    mrp_rounding: int = Form(5),
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
    save_bartender_settings(
        mode=mode,
        show_bartender_window=show_bartender_window,
    )
    save_barcode_settings(
        generation_mode=barcode_generation_mode,
        default_length=default_barcode_length,
        allowed_chars=barcode_allowed_chars,
    )
    save_pricing_settings(mrp_rounding=mrp_rounding)
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
    return RedirectResponse("/settings?settings_saved=1", status_code=303)
