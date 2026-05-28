from __future__ import annotations

import csv
import json
import subprocess
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from sqlalchemy.orm import Session

from app.config import BARTEND_EXE_PATH, PRINT_JOBS_DIR
from app.models import PrintJob
from app.services.bartender_activex_service import print_with_activex
from app.services.field_config import parse_required_fields


CSV_FIELDS = [
    "job_id",
    "copies",
    "template_id",
    "template_name",
    "bartender_file_path",
    "printer_name",
    "required_fields_used",
    "barcode",
    "brand",
    "item_display_name",
    "design",
    "article_no",
    "size",
    "color",
    "batch_no",
    "season",
    "expiry",
    "mrp",
    "selling_price",
    "coded_price",
    "billing_price_missing",
    "family_name",
    "tally_stock_item_name",
]


def _money(value: Decimal | None) -> str:
    if value is None:
        return ""
    return f"{value:.2f}"


def _extra_field_values(value: str | None) -> dict[str, str]:
    if not value:
        return {}
    try:
        raw_values = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return {}
    if not isinstance(raw_values, dict):
        return {}
    return {str(field_name): "" if field_value is None else str(field_value) for field_name, field_value in raw_values.items()}


def create_csv_print_job(db: Session, job: PrintJob) -> Path:
    PRINT_JOBS_DIR.mkdir(parents=True, exist_ok=True)
    db.refresh(job)

    variant = job.variant
    template = job.template
    family = variant.family
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    path = PRINT_JOBS_DIR / f"print_job_{job.id}_{timestamp}.csv"
    required_fields = parse_required_fields(template.required_fields)

    row = {
        "job_id": job.id,
        "copies": job.copies,
        "template_id": template.template_id,
        "template_name": template.template_name,
        "bartender_file_path": template.bartender_file_path,
        "printer_name": template.printer_name or "",
        "required_fields_used": ",".join(required_fields),
        "barcode": variant.barcode,
        "brand": variant.brand or "",
        "item_display_name": variant.item_display_name,
        "design": variant.item_display_name,
        "article": variant.article_no or "",
        "article_no": variant.article_no or "",
        "size": variant.size or "",
        "color": variant.color or "",
        "batch_no": variant.batch_no or "",
        "season": variant.season or "",
        "expiry": variant.expiry or "",
        "mrp": _money(variant.mrp),
        "selling_price": _money(variant.selling_price),
        "coded_price": variant.coded_price or "",
        "billing_price_missing": "true" if variant.billing_price_missing else "false",
        "family_name": family.family_name,
        "tally_stock_item_name": family.tally_stock_item_name or "",
    }
    row.update(_extra_field_values(variant.extra_field_values))
    fieldnames = list(CSV_FIELDS)
    for required_field in required_fields:
        if required_field not in fieldnames:
            fieldnames.append(required_field)
        row.setdefault(required_field, "")

    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerow(row)

    job.csv_file_path = str(path)
    job.status = "pending"
    job.error_message = None
    db.add(job)
    db.commit()
    db.refresh(job)
    return path


def _named_substring_values(job: PrintJob) -> dict[str, str]:
    variant = job.variant
    family = variant.family
    field_values = {
        "barcode": variant.barcode,
        "brand": variant.brand or "",
        "item_display_name": variant.item_display_name,
        "design": variant.item_display_name,
        "family_name": family.family_name,
        "article": variant.article_no or "",
        "article_no": variant.article_no or "",
        "size": variant.size or "",
        "batch_no": variant.batch_no or "",
        "expiry": variant.expiry or "",
        "mrp": _money(variant.mrp),
        "selling_price": _money(variant.selling_price),
        "coded_price": variant.coded_price or "",
        "billing_price_missing": "true" if variant.billing_price_missing else "false",
    }
    field_values.update(_extra_field_values(variant.extra_field_values))
    return {
        field_name: field_values.get(field_name, "")
        for field_name in parse_required_fields(job.template.required_fields)
    }


def _mark_failed(db: Session, job: PrintJob, error_message: str) -> PrintJob:
    job.status = "failed"
    job.printed_at = None
    job.error_message = error_message[:1800]
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def process_print_job(
    db: Session,
    job: PrintJob,
    *,
    mode: str,
    show_bartender_window: bool = False,
) -> PrintJob:
    db.refresh(job)
    clean_mode = mode.strip().lower()
    if clean_mode == "csv":
        try:
            create_csv_print_job(db, job)
        except Exception as exc:
            return _mark_failed(db, job, f"CSV print job generation failed: {exc}")
        db.refresh(job)
        return job

    values = _named_substring_values(job)
    try:
        print_with_activex(
            job.template.bartender_file_path,
            values,
            job.copies,
            visible=show_bartender_window,
        )
    except Exception as exc:
        active_x_error = str(exc)
        try:
            fallback_path = create_csv_print_job(db, job)
            fallback_message = f"CSV fallback created: {fallback_path}"
        except Exception as csv_exc:
            fallback_message = f"CSV fallback also failed: {csv_exc}"
        return _mark_failed(
            db,
            job,
            f"ActiveX print failed: {active_x_error}. {fallback_message}",
        )

    job.status = "printed"
    job.printed_at = datetime.utcnow()
    job.error_message = None
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def build_bartend_command(job: PrintJob, bartend_exe_path: str = BARTEND_EXE_PATH) -> list[str]:
    template_path = job.template.bartender_file_path
    if not template_path:
        raise ValueError("Template has no BarTender file path.")
    if not job.csv_file_path:
        raise ValueError("Print job has no CSV file path.")

    return [
        bartend_exe_path,
        f"/F={template_path}",
        f"/D={job.csv_file_path}",
        "/P",
        "/X",
    ]


def run_bartend_exe(job: PrintJob, bartend_exe_path: str = BARTEND_EXE_PATH) -> subprocess.CompletedProcess:
    command = build_bartend_command(job, bartend_exe_path=bartend_exe_path)
    return subprocess.run(command, capture_output=True, text=True, check=False)
