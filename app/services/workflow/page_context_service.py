from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import LabelVariant, PrintJob, ProductFamily, TemplateMaster
from app.services.network_service import qr_url_for_scanner, scanner_url
from app.services.settings_service import (
    get_barcode_settings,
    get_bartender_settings,
    get_price_code_settings,
    get_pricing_settings,
)
from app.services.template_folder_service import scan_bartender_template_folder, template_path_exists
from app.services.field_config import parse_required_fields
from app.services.workflow.form_state_service import parse_extra_field_values, variant_template_id


def item_detail_context(request: Any, db: Session, variant: LabelVariant) -> dict[str, object]:
    jobs = db.execute(
        select(PrintJob)
        .where(PrintJob.variant_id == variant.id)
        .order_by(PrintJob.created_at.desc(), PrintJob.id.desc())
    ).scalars().all()
    return {
        "request": request,
        "variant": variant,
        "jobs": jobs,
        "category": variant.family.category or "clothes",
        "template_id": variant_template_id(variant) or "",
        "extra_field_values": parse_extra_field_values(variant.extra_field_values),
    }


def recent_prints_context(request: Any, db: Session) -> dict[str, object]:
    jobs = db.execute(
        select(PrintJob).order_by(PrintJob.created_at.desc(), PrintJob.id.desc()).limit(80)
    ).scalars().all()
    return {
        "request": request,
        "jobs": jobs,
    }


def reports_context(request: Any, db: Session) -> dict[str, object]:
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
    return {
        "request": request,
        "stats": stats,
        "category_rows": category_rows,
    }


def settings_context(
    request: Any,
    db: Session,
    *,
    settings_saved: int | None = None,
    settings_error: str | None = None,
) -> dict[str, object]:
    scanner, scanner_ip_detected = scanner_url(request.headers.get("host"))
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
    return {
        "request": request,
        "stats": stats,
        "ready_to_label": bool(ready_templates),
        "bartender_settings": get_bartender_settings(),
        "barcode_settings": get_barcode_settings(),
        "pricing_settings": get_pricing_settings(),
        "price_code_settings": get_price_code_settings(),
        "settings_saved": bool(settings_saved),
        "settings_error": settings_error,
        "scanner_url": scanner,
        "scanner_qr_url": qr_url_for_scanner(scanner),
        "scanner_ip_detected": scanner_ip_detected,
    }
