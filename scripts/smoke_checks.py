from __future__ import annotations

import asyncio
from decimal import Decimal
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
from app.models import LabelVariant, PosCartItem, PrintJob, TemplateMaster  # noqa: E402
from app.routes import pos, templates as template_routes, workflow  # noqa: E402
from app.services.workflow import print_orchestration_service, print_service  # noqa: E402
from app.services.barcode_service import assign_barcode  # noqa: E402
from app.services.billing_service import lookup_saved_price_by_barcode  # noqa: E402
from app.services.price_code_service import extract_candidates_from_field, generate_coded_price  # noqa: E402
from app.services.settings_service import DEFAULT_BARCODE_ALLOWED_CHARS  # noqa: E402
from app.services.settings_service import save_barcode_settings, save_price_code_settings  # noqa: E402
from app.services.template_folder_service import template_file_changed_since_extract  # noqa: E402


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


class DummyRequest:
    class Url:
        path = "/new-stock"

    url = Url()

    def url_for(self, name, **path_params):
        if name == "static":
            return "/static/app.css"
        return "#"


class DummyJsonRequest:
    def __init__(self, payload):
        self.payload = payload

    async def json(self):
        return self.payload


def print_item(db, template, **overrides):
    data = {
        "request": DummyRequest(),
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
        "margin_percent": "",
        "coded_price": "AA",
        "extra_field_values": "",
        "selected_price_code_key": "",
        "print_without_billing_price": False,
        "show_pricing_fields_visible": "1",
        "force_new_barcode": False,
        "coded_price_manual_override": False,
        "template_id": template.id,
        "copies": 1,
        "manual_barcode_override": False,
        "db": db,
    }
    data.update(overrides)
    return workflow.print_new_stock(**data)


def has_consecutive_numbers(value: str) -> bool:
    return any(left.isdigit() and right.isdigit() for left, right in zip(value, value[1:]))


def main() -> None:
    init_db()
    workflow.template_path_exists = lambda template: True
    workflow.process_print_job = fake_print_success
    print_orchestration_service.template_path_exists = lambda template: True
    print_service.process_print_job = fake_print_success
    save_barcode_settings(
        generation_mode="template_length_safe_alphanumeric",
        default_length=7,
        allowed_chars=DEFAULT_BARCODE_ALLOWED_CHARS,
    )
    save_price_code_settings(
        digit_to_code={
            "0": "Z",
            "1": "A",
            "2": "D",
            "3": "C",
            "4": "E",
            "5": "F",
            "6": "G",
            "7": "J",
            "8": "K",
            "9": "L",
        },
        allow_extraction=True,
    )

    db = SessionLocal()
    try:
        workflow_template_dir = ROOT / "app" / "templates"
        workflow_markup = (workflow_template_dir / "workflow.html").read_text(encoding="utf-8")
        workflow_partials_dir = workflow_template_dir / "workflow_partials"
        if workflow_partials_dir.exists():
            workflow_markup += "\n".join(
                path.read_text(encoding="utf-8")
                for path in sorted(workflow_partials_dir.glob("*.html"))
            )
        settings_markup = (ROOT / "app" / "templates" / "settings.html").read_text(encoding="utf-8")
        pos_markup = (ROOT / "app" / "templates" / "pos.html").read_text(encoding="utf-8")
        assert_true("focusBillingItem" in workflow_markup and "familyName.focus" in workflow_markup, "/new-stock does not wire Billing Item focus")
        assert_true("printQuantityInput" in workflow_markup and "printFromInlineQuantity" in workflow_markup, "inline print quantity flow missing")
        assert_true("Printing..." in workflow_markup and "printSubmissionPending" in workflow_markup, "print double-submit loading guard missing")
        assert_true("event.key === \"Enter\"" in workflow_markup and "printFromInlineQuantity();" in workflow_markup, "Enter on print quantity does not trigger print")
        assert_true("scanner_qr_url" in pos_markup and "scanner_url" in settings_markup, "scanner QR URL is not rendered")

        alias_settings = save_price_code_settings(
            digit_to_code={
                "0": "Z",
                "1": "A",
                "2": "D,d",
                "3": "C",
                "4": "E",
                "5": "F,V",
                "6": "G",
                "7": "J",
                "8": "K",
                "9": "L",
            },
            allow_extraction=True,
        )
        alias_candidates = extract_candidates_from_field("coded_price", "xDv", alias_settings, priority=True)
        assert_true(alias_candidates and str(alias_candidates[0].selling_price) in {"25", "25.00"}, "comma-separated aliases did not decode")
        assert_true(generate_coded_price("25", alias_settings) == "DF", "code generation did not use first alias")
        try:
            save_price_code_settings(
                digit_to_code={"0": "Z", "1": "A", "2": "D", "3": "D"},
                allow_extraction=True,
            )
            raise AssertionError("duplicate price-code alias was not rejected")
        except ValueError:
            pass

        save_price_code_settings(
            digit_to_code={
                "0": "Z",
                "1": "A",
                "2": "D",
                "3": "C",
                "4": "E",
                "5": "F",
                "6": "G",
                "7": "J",
                "8": "K",
                "9": "L",
            },
            allow_extraction=True,
        )

        template = TemplateMaster(
            template_id="SMOKE_TOY",
            template_name="Smoke Toy",
            category="toys",
            bartender_file_path=str(TMP_DIR / "smoke.btw"),
            required_fields="item_display_name,mrp,coded_price,size,barcode",
            barcode_sample_value="13HPX",
            active_status=True,
        )
        db.add(template)
        db.commit()
        db.refresh(template)

        template_file = TMP_DIR / "changed_template.btw"
        template_file.write_text("old", encoding="utf-8")
        changed_template = TemplateMaster(
            template_id="SMOKE_CHANGED",
            template_name="Smoke Changed",
            bartender_file_path=str(template_file),
            required_fields="item_display_name,barcode",
            fields_extracted_file_mtime="1.000000",
            active_status=True,
        )
        db.add(changed_template)
        db.commit()
        db.refresh(changed_template)
        assert_true(template_file_changed_since_extract(changed_template), "template modified timestamp warning did not trigger")

        missing_template = TemplateMaster(
            template_id="SMOKE_MISSING_OPEN",
            template_name="Smoke Missing Open",
            bartender_file_path=str(TMP_DIR / "missing-open.btw"),
            active_status=True,
        )
        db.add(missing_template)
        db.commit()
        db.refresh(missing_template)
        open_missing = template_routes.open_template_file(missing_template.id, db=db)
        assert_true(open_missing.status_code == 303, "open template missing file did not redirect cleanly")

        print_item(db, template)
        first = db.query(LabelVariant).filter_by(item_display_name="Toy Car").one()
        first_barcode = first.barcode
        assert_true(bool(first_barcode), "new item did not receive a barcode")
        assert_true(len(first_barcode) == 5, "generated barcode did not use template sample length")
        assert_true(set(first_barcode) <= set(DEFAULT_BARCODE_ALLOWED_CHARS), "generated barcode used disallowed characters")
        assert_true(not has_consecutive_numbers(first_barcode), "generated barcode has consecutive numbers")
        assert_true(db.query(PrintJob).filter_by(variant_id=first.id).count() == 1, "new item print job missing")
        assert_true(str(first.selling_price) in {"11.00", "11"}, "code field did not set selling price")

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

        print_item(
            db,
            template,
            existing_variant_id="",
            item_display_name="Toy Car",
            mrp="100",
            coded_price="AA",
            size="S",
        )
        db.refresh(first)
        assert_true(first.barcode == first_barcode, "exact duplicate did not reuse existing barcode")
        assert_true(db.query(LabelVariant).filter_by(item_display_name="Toy Car").count() == 1, "exact duplicate created a second item")

        print_item(
            db,
            template,
            workflow_mode="new_barcode",
            force_new_barcode=False,
            existing_variant_id="",
            item_display_name="Toy Car",
            mrp="100",
            coded_price="AA",
            size="S",
        )
        db.refresh(first)
        assert_true(first.barcode == first_barcode, "automatic new-barcode mode did not yield to exact match")
        assert_true(db.query(LabelVariant).filter_by(item_display_name="Toy Car").count() == 1, "automatic new-barcode exact match duplicated item")

        print_item(
            db,
            template,
            workflow_mode="new_barcode",
            force_new_barcode=True,
            existing_variant_id="",
            item_display_name="Toy Car",
            mrp="100",
            coded_price="AA",
            size="S",
        )
        forced_variants = db.query(LabelVariant).filter_by(item_display_name="Toy Car").all()
        assert_true(len(forced_variants) == 2, "explicit new barcode did not create a separate label record")
        assert_true(any(item.barcode != first_barcode for item in forced_variants), "explicit new barcode reused old barcode")

        print_item(
            db,
            template,
            existing_variant_id=str(first.id),
            item_display_name="Toy Car",
            mrp="100",
            coded_price="AA",
            size="M",
        )
        toy_car_variants = db.query(LabelVariant).filter_by(item_display_name="Toy Car").all()
        assert_true(len(toy_car_variants) == 3, "changed existing item did not create a new label record")
        changed_detail_variant = [item for item in toy_car_variants if item.id != first.id][0]
        assert_true(changed_detail_variant.barcode != first_barcode, "changed existing item reused the old barcode")

        print_item(
            db,
            template,
            existing_variant_id=str(first.id),
            item_display_name="Toy Car",
            mrp="100",
            coded_price="",
            selling_price="222",
            size="S",
        )
        selling_change_variants = db.query(LabelVariant).filter_by(item_display_name="Toy Car").all()
        assert_true(len(selling_change_variants) == 4, "changed selling price did not create a new label record")

        stale_response = print_item(
            db,
            template,
            workflow_mode="new_barcode",
            existing_variant_id="",
            item_display_name="Toy Car",
            barcode=first_barcode,
            mrp="175",
            coded_price="AA",
            size="S",
        )
        assert_true(
            getattr(stale_response, "status_code", None) == 303,
            "stale duplicate barcode print did not redirect: "
            + str(getattr(stale_response, "context", {}).get("error", "")),
        )
        stale_barcode_variant = (
            db.query(LabelVariant)
            .filter_by(item_display_name="Toy Car", mrp=Decimal("175"))
            .one()
        )
        assert_true(
            stale_barcode_variant.barcode != first_barcode,
            "non-manual stale barcode was not replaced for new price",
        )

        priority_template = TemplateMaster(
            template_id="SMOKE_PRIORITY",
            template_name="Smoke Priority",
            category="toys",
            bartender_file_path=str(TMP_DIR / "priority.btw"),
            required_fields="item_display_name,coded_price,barcode",
            barcode_sample_value="13HPX",
            active_status=True,
        )
        fallback_template = TemplateMaster(
            template_id="SMOKE_FALLBACK",
            template_name="Smoke Fallback",
            category="toys",
            bartender_file_path=str(TMP_DIR / "fallback.btw"),
            required_fields="item_display_name,article,batch_no,barcode",
            barcode_sample_value="13HPX",
            active_status=True,
        )
        db.add_all([priority_template, fallback_template])
        db.commit()
        db.refresh(priority_template)
        db.refresh(fallback_template)

        no_sample_template = TemplateMaster(
            template_id="SMOKE_NO_SAMPLE",
            template_name="Smoke No Sample",
            category="toys",
            bartender_file_path=str(TMP_DIR / "no_sample.btw"),
            required_fields="item_display_name,coded_price,barcode",
            active_status=True,
        )
        db.add(no_sample_template)
        db.commit()
        db.refresh(no_sample_template)

        print_item(db, no_sample_template, item_display_name="No Sample", coded_price="DDD", mrp="", size="")
        no_sample_item = db.query(LabelVariant).filter_by(item_display_name="No Sample").one()
        assert_true(len(no_sample_item.barcode) == 7, "missing sample barcode did not use default length 7")

        print_item(db, priority_template, item_display_name="Priority Code", coded_price="DDD", mrp="", size="")
        priority_item = db.query(LabelVariant).filter_by(item_display_name="Priority Code").one()
        assert_true(str(priority_item.selling_price) in {"222.00", "222"}, "code/coded_price field did not take priority")

        missing_price_response = print_item(
            db,
            priority_template,
            item_display_name="Missing Price",
            coded_price="",
            mrp="",
            size="",
        )
        assert_true(getattr(missing_price_response, "status_code", None) == 400, "missing code/selling price did not block print")

        multiple_price_response = print_item(
            db,
            priority_template,
            item_display_name="Multiple Codes",
            coded_price="DDD/FFF",
            mrp="",
            size="",
        )
        assert_true(getattr(multiple_price_response, "status_code", None) == 400, "multiple codes did not require choice")

        print_item(
            db,
            priority_template,
            item_display_name="Manual Selling",
            coded_price="XX",
            selling_price="222",
            mrp="",
            size="",
        )
        manual_item = db.query(LabelVariant).filter_by(item_display_name="Manual Selling").one()
        assert_true(manual_item.coded_price == "XX", "manual selling price did not preserve raw code")
        billing_item = lookup_saved_price_by_barcode(db, manual_item.barcode)
        assert_true(str(billing_item.selling_price) in {"222.00", "222"}, "billing lookup did not use saved selling price")

        print_item(
            db,
            priority_template,
            item_display_name="Default Code",
            coded_price="ZZZ",
            selling_price="222",
            mrp="",
            size="",
        )
        default_code_item = db.query(LabelVariant).filter_by(item_display_name="Default Code").one()
        assert_true(default_code_item.coded_price == "ZZZ", "manual selling price should not overwrite raw code")

        print_item(
            db,
            priority_template,
            item_display_name="Manual Code Override",
            coded_price="GIB",
            coded_price_manual_override=True,
            selling_price="222",
            mrp="",
            size="",
        )
        manual_code_item = db.query(LabelVariant).filter_by(item_display_name="Manual Code Override").one()
        assert_true(manual_code_item.coded_price == "GIB", "manual coded price override was not preserved")

        try:
            assign_barcode(db, first_barcode)
            raise AssertionError("duplicate barcode was not blocked")
        except ValueError:
            pass

        workflow.process_print_job = fake_print_fail
        print_service.process_print_job = fake_print_fail
        print_item(
            db,
            template,
            item_display_name="Toy Truck",
            mrp="150",
            coded_price="DD",
            size="M",
        )
        failed_variant = db.query(LabelVariant).filter_by(item_display_name="Toy Truck").one()
        failed_job = db.query(PrintJob).filter_by(variant_id=failed_variant.id).one()
        failed_barcode = failed_variant.barcode
        assert_true(failed_job.status == "failed", "failed print job was not marked failed")
        assert_true(bool(failed_barcode), "failed print did not keep saved item barcode")

        workflow.process_print_job = fake_print_success
        print_service.process_print_job = fake_print_success
        retry_job = workflow._create_print_job(db, failed_variant, template, 1)
        db.refresh(failed_variant)
        assert_true(retry_job.variant_id == failed_variant.id, "retry job linked to wrong item")
        assert_true(failed_variant.barcode == failed_barcode, "retry changed the barcode")

        add_response = asyncio.run(pos.pos_scan(DummyJsonRequest({"barcode": first_barcode}), db))
        assert_true(add_response["ok"], "POS scan did not add saved barcode")
        lookup_response = asyncio.run(
            pos.pos_lookup_barcodes(DummyJsonRequest({"candidates": [first_barcode, "NOTREAL"]}), db)
        )
        assert_true(len(lookup_response["matches"]) == 1, "POS OCR lookup did not return exactly one saved barcode")
        assert_true(lookup_response["matches"][0]["barcode"] == first_barcode, "POS OCR lookup returned wrong barcode")
        add_again = asyncio.run(pos.pos_scan(DummyJsonRequest({"barcode": first_barcode}), db))
        assert_true(add_again["cart"]["count"] >= 2, "POS scan did not increment quantity")

        no_price_variant = LabelVariant(
            barcode="NOPRICE",
            family_id=first.family_id,
            item_display_name="No Price Item",
            template_id=template.id,
            status="active",
        )
        db.add(no_price_variant)
        db.commit()
        missing_response = asyncio.run(pos.pos_scan(DummyJsonRequest({"barcode": "NOPRICE"}), db))
        assert_true(missing_response.status_code == 409, "POS scan did not block missing selling price")
        confirmed_response = asyncio.run(
            pos.pos_scan(DummyJsonRequest({"barcode": "NOPRICE", "allow_missing_price": True}), db)
        )
        assert_true(confirmed_response["ok"], "POS scan did not allow confirmed missing price item")

        cart_before_clear = pos.pos_cart(db)
        assert_true(cart_before_clear["count"] >= 3, "POS cart did not keep scanned items")
        pos.clear_pos_cart(db)
        assert_true(db.query(PosCartItem).count() == 0, "POS cart clear did not remove items")

        print("Smoke checks passed")
    finally:
        db.close()


if __name__ == "__main__":
    main()
