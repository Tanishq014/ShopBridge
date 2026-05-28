from __future__ import annotations

import os
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
TMP_DIR = ROOT / ".tmp"
TMP_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = TMP_DIR / "smoke_checks.db"
if DB_PATH.exists():
    DB_PATH.unlink()

os.environ["SHOPBRIDGE_DATABASE_URL"] = f"sqlite:///{DB_PATH.as_posix()}"
os.environ["SHOPBRIDGE_DATA_DIR"] = str(TMP_DIR / "data")
os.environ["SHOPBRIDGE_PRINT_JOBS_DIR"] = str(TMP_DIR / "print_jobs")
os.environ["SHOPBRIDGE_EXPORTS_DIR"] = str(TMP_DIR / "exports")

from app.db import SessionLocal, init_db  # noqa: E402
from app.models import LabelVariant, PrintJob, TemplateMaster  # noqa: E402
from app.routes import workflow  # noqa: E402
from app.services.barcode_service import assign_barcode  # noqa: E402


def assert_true(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def fake_print_success(db, job, *, mode, show_bartender_window=False):
    job.status = "printed"
    job.error_message = None
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def fake_print_fail(db, job, *, mode, show_bartender_window=False):
    job.status = "failed"
    job.error_message = "forced smoke failure"
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def print_item(db, template, **overrides):
    data = {
        "request": None,
        "workflow_mode": "print",
        "existing_variant_id": "",
        "family_id": "",
        "family_name": "Toy",
        "category": "toys",
        "barcode": "",
        "brand": "",
        "item_display_name": "Toy Car",
        "article_no": "",
        "size": "S",
        "batch_no": "",
        "expiry": "",
        "mrp": "100",
        "selling_price": "",
        "coded_price": "AA",
        "template_id": template.id,
        "copies": 1,
        "db": db,
    }
    data.update(overrides)
    return workflow.print_new_stock(**data)


def main() -> None:
    init_db()
    workflow.template_path_exists = lambda template: True
    workflow.process_print_job = fake_print_success

    db = SessionLocal()
    try:
        template = TemplateMaster(
            template_id="SMOKE_TOY",
            template_name="Smoke Toy",
            category="toys",
            bartender_file_path=str(TMP_DIR / "smoke.btw"),
            required_fields="item_display_name,mrp,coded_price,size,barcode",
            active_status=True,
        )
        db.add(template)
        db.commit()
        db.refresh(template)

        print_item(db, template)
        first = db.query(LabelVariant).filter_by(item_display_name="Toy Car").one()
        first_barcode = first.barcode
        assert_true(bool(first_barcode), "new item did not receive a barcode")
        assert_true(5 <= len(first_barcode) <= 8, "generated barcode is not short")
        assert_true(db.query(PrintJob).filter_by(variant_id=first.id).count() == 1, "new item print job missing")

        print_item(
            db,
            template,
            existing_variant_id=str(first.id),
            item_display_name="Toy Car",
            mrp="100",
            coded_price="AA",
            size="S",
        )
        db.refresh(first)
        assert_true(first.barcode == first_barcode, "existing item did not reuse barcode")
        assert_true(db.query(LabelVariant).filter_by(item_display_name="Toy Car").count() == 1, "existing print duplicated item")

        try:
            assign_barcode(db, first_barcode)
            raise AssertionError("duplicate barcode was not blocked")
        except ValueError:
            pass

        workflow.process_print_job = fake_print_fail
        print_item(
            db,
            template,
            item_display_name="Toy Truck",
            mrp="150",
            coded_price="BB",
            size="M",
        )
        failed_variant = db.query(LabelVariant).filter_by(item_display_name="Toy Truck").one()
        failed_job = db.query(PrintJob).filter_by(variant_id=failed_variant.id).one()
        failed_barcode = failed_variant.barcode
        assert_true(failed_job.status == "failed", "failed print job was not marked failed")
        assert_true(bool(failed_barcode), "failed print did not keep saved item barcode")

        workflow.process_print_job = fake_print_success
        retry_job = workflow._create_print_job(db, failed_variant, template, 1)
        db.refresh(failed_variant)
        assert_true(retry_job.variant_id == failed_variant.id, "retry job linked to wrong item")
        assert_true(failed_variant.barcode == failed_barcode, "retry changed the barcode")

        print("Smoke checks passed")
    finally:
        db.close()


if __name__ == "__main__":
    main()
