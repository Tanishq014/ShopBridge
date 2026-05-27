from __future__ import annotations

from decimal import Decimal, InvalidOperation
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import TEMPLATES_DIR
from app.db import get_db
from app.models import LabelVariant, PrintJob, ProductFamily, TemplateMaster
from app.services.barcode_service import assign_barcode
from app.services.bartender_activex_service import BarTenderActiveXError, extract_named_substrings
from app.services.bartender_service import create_csv_print_job
from app.services.field_config import SUPPORTED_FIELDS, field_label, format_required_fields, parse_required_fields
from app.services.price_code_service import generate_coded_price
from app.services.template_folder_service import scan_bartender_template_folder, template_path_exists


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


def _active_templates(db: Session) -> list[TemplateMaster]:
    rows = db.execute(
        select(TemplateMaster)
        .where(TemplateMaster.active_status == True)  # noqa: E712
        .order_by(TemplateMaster.category, TemplateMaster.template_name)
    ).scalars().all()
    return [template for template in rows if template_path_exists(template)]


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
        "template_id": _variant_template_id(variant) or "",
        "template_name": template.template_name if template else "",
    }


def _template_payload(template: TemplateMaster) -> dict[str, object]:
    return {
        "id": template.id,
        "template_id": template.template_id,
        "template_name": template.template_name,
        "category": (template.category or "").strip().lower(),
        "label_size": template.label_size or "",
        "required_fields": parse_required_fields(template.required_fields),
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


def _create_print_job(
    db: Session,
    variant: LabelVariant,
    template: TemplateMaster,
    copies: int,
) -> PrintJob:
    job = PrintJob(
        variant_id=variant.id,
        template_id=template.id,
        copies=max(1, copies),
        status="pending",
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    create_csv_print_job(db, job)
    db.refresh(job)
    return job


def _workflow_context(
    request: Request,
    db: Session,
    message: str | None = None,
    error: str | None = None,
    selected_template_id: int | None = None,
    selected_category: str = "clothes",
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

    return {
        "request": request,
        "message": message,
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
        "template_warning": (
            None
            if template_rows
            else "No usable BarTender .btw template was found. Put .btw files in bartender_templates or fix the template path in Settings."
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
    db: Session = Depends(get_db),
):
    message = f"Print job #{printed} created." if printed else None
    if extracted:
        message = f"Extracted fields: {extracted}"
    return templates.TemplateResponse(
        request,
        "workflow.html",
        _workflow_context(
            request,
            db,
            message=message,
            error=extract_error,
            selected_template_id=template_id,
            selected_category=category,
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
        fields = extract_named_substrings(template.bartender_file_path)
    except BarTenderActiveXError as exc:
        return RedirectResponse(
            f"/new-stock?{urlencode({'template_id': template.id, 'category': category, 'extract_error': str(exc)})}",
            status_code=303,
        )

    template.required_fields = format_required_fields(fields)
    db.add(template)
    db.commit()
    extracted = ", ".join(fields)
    return RedirectResponse(
        f"/new-stock?{urlencode({'template_id': template.id, 'category': category, 'extracted': extracted})}",
        status_code=303,
    )


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
    template_id: int = Form(...),
    copies: int = Form(1),
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
        return RedirectResponse(f"/new-stock?printed={job.id}", status_code=303)

    required_fields = parse_required_fields(template.required_fields)
    required_field_set = set(required_fields)

    def field_is_required(field_name: str) -> bool:
        if field_name == "article_no":
            return "article_no" in required_field_set or "article" in required_field_set
        return field_name in required_field_set

    def value_or_preserved(field_name: str, raw_value: str, attr_name: str | None = None) -> str:
        clean_value = (raw_value or "").strip()
        if clean_value:
            return clean_value
        if source_variant and not field_is_required(field_name):
            stored_value = getattr(source_variant, attr_name or field_name, None)
            return "" if stored_value is None else str(stored_value)
        return ""

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
    coded = coded_price.strip() or generate_coded_price(selling) or value_or_preserved("coded_price", coded_price)

    field_values = {
        "brand": brand_value,
        "item_display_name": item_name_value,
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

    family = _find_or_create_family(
        db=db,
        category=category.strip().lower(),
        family_id=_int_or_none(family_id),
        family_name=final_family_name,
        item_display_name=item_name_value,
    )

    update_existing = source_variant is not None and workflow_mode != "duplicate"
    if update_existing:
        variant = source_variant
        requested_barcode = barcode.strip()
        if requested_barcode and requested_barcode != variant.barcode:
            variant.barcode = assign_barcode(db, requested_barcode, exclude_variant_id=variant.id)
    else:
        try:
            final_barcode = assign_barcode(db, barcode)
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
            _workflow_context(request, db, error=f"Variant saved, but print CSV failed: {exc}"),
            status_code=500,
        )

    return RedirectResponse(f"/new-stock?printed={job.id}", status_code=303)


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

    job = _create_print_job(db, variant, template, copies)
    return RedirectResponse(f"/new-stock?printed={job.id}", status_code=303)


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
        return RedirectResponse(f"/new-stock?printed={job.id}", status_code=303)
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
def settings(request: Request):
    return templates.TemplateResponse(
        request,
        "settings.html",
        {
            "request": request,
        },
    )
