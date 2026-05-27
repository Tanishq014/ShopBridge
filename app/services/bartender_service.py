from __future__ import annotations

import csv
import subprocess
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from sqlalchemy.orm import Session

from app.config import BARTEND_EXE_PATH, PRINT_JOBS_DIR
from app.models import PrintJob
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
    "article_no",
    "size",
    "color",
    "batch_no",
    "season",
    "expiry",
    "mrp",
    "selling_price",
    "coded_price",
    "family_name",
    "tally_stock_item_name",
]


def _money(value: Decimal | None) -> str:
    if value is None:
        return ""
    return f"{value:.2f}"


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
        "family_name": family.family_name,
        "tally_stock_item_name": family.tally_stock_item_name or "",
    }
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
