from __future__ import annotations

from urllib.parse import urlencode

from sqlalchemy.orm import Session

from app.models import LabelVariant, PrintJob, TemplateMaster
from app.services.bartender_service import process_print_job
from app.services.field_config import parse_required_fields
from app.services.settings_service import get_bartender_settings


def create_print_job(
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


def new_stock_print_redirect_url(job: PrintJob, template: TemplateMaster, category: str = "clothes") -> str:
    query: dict[str, object] = {
        "printed": job.id,
        "template_id": template.id,
        "category": category,
        "load_variant_id": job.variant_id,
    }
    if job.status == "failed" and job.error_message:
        query["print_error"] = job.error_message
    return f"/new-stock?{urlencode(query)}"
