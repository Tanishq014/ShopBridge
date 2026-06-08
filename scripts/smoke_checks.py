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
from app.models import LabelVariant, PosCartItem, PrintJob, ProductFamily, Sale, SaleItem, TemplateMaster  # noqa: E402
from app.routes import pos, sales, templates as template_routes, workflow  # noqa: E402
from app.services.workflow import print_orchestration_service, print_service  # noqa: E402
from app.services.bartender_service import _named_substring_values  # noqa: E402
from app.services.barcode_service import assign_barcode  # noqa: E402
from app.services.billing_service import lookup_saved_price_by_barcode  # noqa: E402
from app.services.price_code_service import extract_candidates_from_field, generate_coded_price  # noqa: E402
from app.services.settings_service import DEFAULT_BARCODE_ALLOWED_CHARS  # noqa: E402
from app.services.settings_service import save_barcode_settings, save_price_code_settings  # noqa: E402
from app.services.sales_service import checkout_cart  # noqa: E402
from app.services.template_folder_service import template_file_changed_since_extract  # noqa: E402
from app.services.workflow.form_state_service import variant_payload  # noqa: E402


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
        pos_route_source = (ROOT / "app" / "routes" / "pos.py").read_text(encoding="utf-8")
        model_source = (ROOT / "app" / "models.py").read_text(encoding="utf-8")
        db_source = (ROOT / "app" / "db.py").read_text(encoding="utf-8")
        sales_service_source = (ROOT / "app" / "services" / "sales_service.py").read_text(encoding="utf-8")
        scanner_markup = (ROOT / "app" / "templates" / "scanner.html").read_text(encoding="utf-8")
        phone_print_markup = (ROOT / "app" / "templates" / "phone_print.html").read_text(encoding="utf-8")
        base_markup = (ROOT / "app" / "templates" / "base.html").read_text(encoding="utf-8")
        sales_markup = (ROOT / "app" / "templates" / "sales.html").read_text(encoding="utf-8")
        sale_detail_markup = (ROOT / "app" / "templates" / "sale_detail.html").read_text(encoding="utf-8")
        sale_receipt_markup = (ROOT / "app" / "templates" / "sale_receipt.html").read_text(encoding="utf-8")
        sales_route_source = (ROOT / "app" / "routes" / "sales.py").read_text(encoding="utf-8")
        app_css = (ROOT / "app" / "static" / "app.css").read_text(encoding="utf-8")
        assert_true("focusBillingItem" in workflow_markup and "familyName.focus" in workflow_markup, "/new-stock does not wire Billing Item focus")
        assert_true("familyName.addEventListener(\"click\"" in workflow_markup and "familyName.select();" in workflow_markup, "Billing Item does not select text on click")
        assert_true("form.addEventListener(\"keydown\"" in workflow_markup and "event.key === \"Enter\"" in workflow_markup and "printQuantityInput" in workflow_markup, "Enter does not reuse Tab-style navigation in the workflow")
        assert_true("handleEntryAdvanceNavigation" in workflow_markup and "moveEntryFocus(target, 1)" in workflow_markup, "Enter-to-next workflow navigation is missing")
        assert_true("printQuantityInput" in workflow_markup and "printFromInlineQuantity" in workflow_markup, "inline print quantity flow missing")
        assert_true("printQuantityDialog" in workflow_markup and "printFromDialogQuantity" in workflow_markup, "Ctrl+P print quantity dialog is missing")
        assert_true("openPrintQuantityDialog();" in workflow_markup, "Ctrl+P does not open the print quantity dialog")
        assert_true("Printing..." in workflow_markup and "printSubmissionPending" in workflow_markup, "print double-submit loading guard missing")
        assert_true("event.key === \"Enter\"" in workflow_markup and "printFromInlineQuantity();" in workflow_markup, "Enter on print quantity does not trigger print")
        assert_true("resetPrintSubmissionState" in workflow_markup and "form.addEventListener(\"invalid\"" in workflow_markup, "browser validation can leave print stuck")
        assert_true("restoreVariantForRetry" in workflow_markup and "hasPrintError && initialVariantId" in workflow_markup, "print error retry state is not restored from saved item")
        assert_true("uppercaseVisibleFieldValues" in workflow_markup and "uppercaseFieldValue(field)" in workflow_markup, "laptop inputs should uppercase visible text fields")
        assert_true("scanner_qr_url" not in pos_markup and "phone_print_qr_url" not in pos_markup and "scanner_url" in settings_markup and "phone_print_url" in settings_markup, "POS top QR shortcuts should be removed and URLs should remain in settings")
        assert_true("topbar-menu-toggle" in base_markup and "topbarMenuPanel" in base_markup and "topbar-menu-panel" in base_markup, "shared mobile hamburger menu is missing")
        assert_true("navbar_qr_context(request)" in base_markup and "scanner_qr_url is defined" not in base_markup, "shared navbar QR should come from base context on every page")
        assert_true("topbar-qr-toggle" in base_markup and "Phone QR" in base_markup and "data-navbar-qr-panel" in base_markup and "shopbridge.navbarQrVisible.v1" in base_markup, "shared navbar QR dropdown is missing")
        assert_true("navbarQrStateBadge" in settings_markup and "showNavbarQrButton" in settings_markup and "hideNavbarQrButton" in settings_markup and "scanner-qr" not in settings_markup, "settings should control navbar QR visibility without showing big QR images")
        assert_true('"qr_code"' in scanner_markup and '"data_matrix"' in scanner_markup, "scanner does not request QR/DataMatrix formats")
        assert_true("/phone-print/print" in phone_print_markup and "phoneTemplates" in phone_print_markup and "Uses this laptop's templates" not in phone_print_markup and "Laptop Print" not in phone_print_markup, "phone print page is not wired to laptop print data")
        assert_true("BarcodeDetector" in phone_print_markup and '"qr_code"' in phone_print_markup and '"data_matrix"' in phone_print_markup, "phone print scanner does not request QR/DataMatrix formats")
        assert_true("phoneFields.code.value = candidate.raw_value || candidate.code" in phone_print_markup and "phoneUppercaseVisibleFieldValues" in phone_print_markup, "phone code selection should preserve raw text and uppercase visible fields")
        assert_true("shopbridge.phonePrintState.v1" in phone_print_markup and "phoneRestoreState" in phone_print_markup, "phone print state is not persisted")
        assert_true("phoneShowCachedPreview" in phone_print_markup and "/new-stock/preview-image" in phone_print_markup, "phone print preview is not wired")
        assert_true("phoneActualPreviewIsGenerated" in phone_print_markup and "phoneShowCachedPreview();" not in phone_print_markup.split("phoneFields.code.addEventListener", 1)[-1].split("phoneFields.margin.addEventListener", 1)[0], "phone print field edits should not reset actual preview")
        assert_true("phoneSecondaryTools" in phone_print_markup and "data-copy-count" in phone_print_markup, "phone print compact scan/search or copy chips are missing")
        assert_true("phoneStickyPrintButton" in phone_print_markup and "phonePrintButton.disabled" in phone_print_markup, "phone print sticky button does not share print readiness")
        assert_true("phoneSelectTextOnEdit" in phone_print_markup and "field.select()" in phone_print_markup, "phone print fields do not select text on edit")
        assert_true("phoneCalculateMarginButton" in phone_print_markup and "phoneMarginPreview" in phone_print_markup, "phone print margin calculate/live preview is missing")
        assert_true("phoneRecordDecision" in phone_print_markup and "phoneExactVariant" in phone_print_markup, "phone print automatic barcode decision is missing")
        assert_true("Force New Barcode" in phone_print_markup and "Usually leave this automatic" in phone_print_markup, "phone print force-new barcode is not tucked into advanced tools")
        assert_true("phonePrintCopiesDialog" in phone_print_markup and "phoneOpenCopiesDialog" in phone_print_markup, "phone print does not ask for copies before submit")
        assert_true("phonePrintCopiesConfirmed" in phone_print_markup and "phoneSubmitPrintButton" in phone_print_markup, "phone print copies confirmation does not guard final submit")
        assert_true(".scanner-status span" in app_css and "overflow-wrap: anywhere" in app_css and "max-width: calc(100vw - 16px)" in app_css, "phone error text can overflow the viewport")
        assert_true("Loaded saved item" not in phone_print_markup, "phone print shows the old green loaded saved item status")
        assert_true("min-height: 42px" in app_css and "padding-bottom: 76px" in app_css, "phone sticky print bar height is not the adjusted size")
        assert_true("Printed" in (ROOT / "app" / "templates" / "recent_prints.html").read_text(encoding="utf-8"), "recent prints does not show printed time")
        assert_true("Printed" in (ROOT / "app" / "templates" / "scan.html").read_text(encoding="utf-8"), "scan history does not show printed time")
        assert_true("Created" in (ROOT / "app" / "templates" / "print_jobs.html").read_text(encoding="utf-8") and "Printed" in (ROOT / "app" / "templates" / "print_jobs.html").read_text(encoding="utf-8"), "print jobs admin does not show timestamps")
        assert_true(getattr(workflow.phone_print(DummyRequest(), db=db), "status_code", None) == 200, "/phone-print route did not render")
        assert_true("applyTemplatePlaceholders" in workflow_markup and "setInputPlaceholder" in workflow_markup, "template defaults are not wired into input placeholders")
        assert_true("input.value = defaultValue" not in workflow_markup, "template defaults should not auto-fill submitted values")
        assert_true("variant_search: selectedSearchVariant ? variantLabel(selectedSearchVariant) : \"\"" in workflow_markup, "partial existing-item search text can be persisted")
        assert_true(".combo-option.active" in app_css and "background: #1f6feb" in app_css, "dropdown active row styling is not high contrast")
        assert_true("data-template-path" in workflow_markup and "templateActionStatus" in workflow_markup, "template disabled action reason is not shown")
        assert_true("selectedTemplateOption" in workflow_markup and "option.dataset.pathExists" in workflow_markup, "template path check does not fall back to selected option data")
        assert_true(hasattr(sales, "router"), "sales route module is not importable")
        assert_true("/pos/checkout" in pos_markup and "checkoutButton" in pos_markup, "POS checkout form is not rendered")
        assert_true("pos-billing-grid" in pos_markup and "Item / Article" in pos_markup and "Barcode" in pos_markup, "POS billing grid is not rendered")
        assert_true("Scan / type item" in pos_markup and "pos-add-row" in pos_markup, "POS add-item row is missing")
        assert_true("posSearchInput" in pos_markup and "/pos/search" in pos_markup, "POS grid search input is not wired")
        assert_true("pos-suggestion-dock" not in pos_markup and "pos-suggestion-dock" not in app_css, "old POS top suggestion dock should be gone")
        assert_true("posSearchPanel" in pos_markup and "Search Results" in pos_markup and "pos-search-results" in pos_markup, "POS right-panel search results UI is missing")
        assert_true("posSummaryPanel" in pos_markup and "summaryPanel.hidden = true" in pos_markup and "searchPanel.hidden = false" in pos_markup, "POS right panel does not switch modes for search")
        suggestion_render = pos_markup.split("function renderSuggestions()", 1)[-1].split("async function searchItems", 1)[0]
        assert_true("item.family_name || item.billing_item || item.item_name" in suggestion_render, "POS search result main line should be billing item/family")
        assert_true("Barcode item" not in suggestion_render, "POS search results should keep item labels compact")
        assert_true("Sticker: ${item.sticker_name}" in suggestion_render and "MRP ${money(item.mrp)}" in suggestion_render, "POS search results should show sticker and MRP details")
        assert_true("item.barcode" not in suggestion_render and "item.category" not in suggestion_render and "item.article_no" not in suggestion_render, "POS search results should not display barcode/category/article noise")
        assert_true("pos-item-input" in pos_markup and "pos-mrp-input" in pos_markup and "dataset.cartField = \"item\"" in pos_markup and "dataset.cartField = \"mrp\"" in pos_markup, "POS editable item name and MRP cells are missing")
        assert_true("PgUp/PgDn Bills" in pos_markup and "navigateRecentSale" in pos_markup and "loadSalePreview" in pos_markup, "POS recent bill navigation is missing")
        assert_true("/pos/cart/load-sale/" in pos_markup and "confirmLoadedSaleEdit" in pos_markup and "Save edited bill" in pos_markup, "POS saved bills should load as editable carts with save confirmation")
        assert_true("disabled = state.previewMode" not in pos_markup and "Previewing bill - press Esc to return" not in pos_markup, "POS opened bills should not render as disabled preview-only rows")
        assert_true("pos-total-box" in pos_markup and "cartTotal" in pos_markup and "Checkout - Rs. 0.00" in pos_markup, "POS checkout summary/total is missing")
        assert_true("searchPanelTotal" in pos_markup and "Total:" in pos_markup, "POS search mode should keep total visible")
        assert_true("focusSelectedCartItem" in pos_markup and "focusSelectedCartItem(true);" in pos_markup and "itemInput.select()" in pos_markup, "POS selected line should auto-focus the item name")
        assert_true("moveCartFieldVertical" in pos_markup and "ArrowDown" in pos_markup and "ArrowUp" in pos_markup, "POS editable cells should support up/down row navigation")
        assert_true("state.selectedIndex = items.length - 1" in pos_markup, "POS should default to the last bill line")
        assert_true("pos-rate-input" in pos_markup and "pos-qty-input" in pos_markup and "/pos/cart/items/${itemId}/update" in pos_markup, "POS editable rate/qty cells are missing")
        assert_true("cartEditActive" in pos_markup and "lineEditIsActive()" in pos_markup and "if (silent &&" in pos_markup, "POS polling should pause while editing rate/qty")
        assert_true("pos-qty-button" in pos_markup and "/increase" in pos_markup and "/decrease" in pos_markup, "POS quantity controls are missing")
        assert_true("addTallyItem" in pos_markup and "result_type === \"tally_item\"" in pos_markup, "POS UI does not add local Tally catalog search results")
        assert_true("helpToggleButton" in pos_markup and "shopbridge.posHelpVisible.v1" in pos_markup and "id=\"posHelpBar\" hidden" in pos_markup, "POS help row toggle/default hidden state is missing")
        assert_true("fullscreenPosButton" in pos_markup and "requestFullscreen" in pos_markup, "POS fullscreen button is missing")
        assert_true("Ctrl+Enter Checkout" in pos_markup and "F2 Item" in pos_markup and "Left/Right Cells" in pos_markup, "POS shortcut help bar is missing")
        assert_true("cartStatus" in pos_markup and "pos-top-actions" in pos_markup and "Fullscreen POS" in pos_markup and "Show Help" in pos_markup and "Refresh" in pos_markup, "POS header status/buttons are missing")
        assert_true(".pos-suggestion.active" in app_css and ".pos-billing-row.selected" in app_css, "POS keyboard highlight styling is missing")
        assert_true("pos-line-input" in app_css and "pos-rate-input" in app_css and "pos-qty-input" in app_css and "pos-item-input" in app_css and "pos-mrp-input" in app_css, "POS editable line input styling is missing")
        assert_true("source_type=\"barcode\"" in pos_route_source and "tally_item" in pos_route_source and "/pos/cart/items/{item_id}/update" in pos_route_source and "item_name_snapshot" in pos_route_source, "POS backend snapshot/update routes are missing")
        assert_true("/pos/cart/load-sale/{sale_id}" in pos_route_source and "source_sale_id" in pos_route_source, "POS backend should load saved bills into editable active cart lines")
        assert_true("ProductFamily" in pos_route_source and "tally_stock_item_name" in pos_route_source, "POS search should include locally imported ProductFamily/Tally items")
        assert_true("family_results" in pos_route_source and "results = family_results" in pos_route_source, "POS search should prioritize Tally catalog results")
        assert_true("item_name_snapshot" in model_source and "rate_snapshot" in model_source and "source_type" in model_source, "POS cart snapshot fields are missing")
        assert_true("ALTER TABLE pos_cart_items ADD COLUMN" in db_source and "variant_id" in db_source and "nullable" in model_source, "POS cart snapshot migration is missing")
        assert_true("item.rate_snapshot" in sales_service_source and "item.item_name_snapshot" in sales_service_source, "checkout does not use POS cart snapshots")
        assert_true("tally_voucher" not in pos_route_source and "tally_alias" not in pos_route_source.lower(), "POS route should not add Tally write code")
        assert_true("Bill No" in sales_markup and "/sales/{{ sale.id }}" in sales_markup and "/pos?sale_id={{ sale.id }}" in sales_markup, "sales list template is missing bill links")
        assert_true("Open Receipt" in sale_detail_markup and "Tally Sync Status" in sale_detail_markup and "/pos?sale_id={{ sale.id }}" in sale_detail_markup, "sale detail template is incomplete")
        assert_true("/sales/{sale_id}/data" in sales_route_source and "sale_payload" in sales_route_source, "sales replay data route is missing")
        assert_true("window.print()" in sale_receipt_markup and "Thank you" in sale_receipt_markup, "receipt template is missing browser print UI")
        assert_true("size: 80mm auto" in app_css and ".receipt" in app_css, "80mm receipt print CSS is missing")
        demo_families = db.query(ProductFamily).filter(ProductFamily.tally_stock_item_name.is_not(None)).all()
        assert_true(
            any((family.family_name or "").startswith("Demo Tally") for family in demo_families),
            "demo Tally catalog items were not seeded",
        )

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
        first_job = db.query(PrintJob).filter_by(variant_id=first.id).one()
        assert_true(variant_payload(first)["mrp"] == "100", "MRP payload should not add .00 for whole numbers")
        assert_true(_named_substring_values(first_job)["mrp"] == "100", "BarTender MRP value should not add .00 for whole numbers")
        priority_family = ProductFamily(
            family_name="Priority Tally Item",
            tally_stock_item_name="Priority Tally Item",
            category="tally",
            active_status=True,
        )
        db.add(priority_family)
        db.commit()
        db.refresh(priority_family)
        priority_variant = LabelVariant(
            barcode="PRIORITY1",
            family_id=priority_family.id,
            item_display_name="Priority Tally Variant",
            template_id=template.id,
            status="active",
        )
        db.add(priority_variant)
        db.commit()
        db.refresh(priority_variant)
        priority_search = pos.pos_search(q="Priority Tally Item", db=db)
        assert_true(priority_search["items"] and priority_search["items"][0]["result_type"] == "tally_item", "POS search does not prioritize Tally catalog items")

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

        save_price_code_settings(
            digit_to_code={
                "0": "A",
                "1": "B",
                "2": "C",
                "3": "D",
                "4": "E",
                "5": "P",
                "6": "F",
                "7": "S",
                "8": "H",
                "9": "J",
            },
            allow_extraction=True,
        )
        print_item(
            db,
            priority_template,
            item_display_name="Prefixed Code",
            coded_price="QSPA",
            selling_price="",
            mrp="",
            size="",
        )
        prefixed_item = db.query(LabelVariant).filter_by(item_display_name="Prefixed Code").one()
        assert_true(prefixed_item.coded_price == "QSPA", "prefixed code should preserve the raw text")
        assert_true(str(prefixed_item.selling_price) in {"750.00", "750"}, "prefixed code should still decode the selling price")

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
        assert_true(add_response["item"]["billing_item"] == add_response["item"]["item_name"], "POS cart payload should use billing item as the primary item name")
        search_response = pos.pos_search(q=first_barcode, db=db)
        assert_true(search_response["items"] and search_response["items"][0]["barcode"] == first_barcode, "POS search did not find saved barcode")
        item_search_response = pos.pos_search(q="Toy", db=db)
        assert_true(item_search_response["items"], "POS search did not find saved item by name")
        tally_family = ProductFamily(
            family_name="Imported Socks",
            tally_stock_item_name="Tally Imported Socks",
            category="tally",
            active_status=True,
        )
        db.add(tally_family)
        db.commit()
        db.refresh(tally_family)
        tally_search_response = pos.pos_search(q="Imported Socks", db=db)
        assert_true(
            any(item.get("result_type") == "tally_item" and item.get("id") == tally_family.id for item in tally_search_response["items"]),
            "POS search did not include local ProductFamily/Tally catalog items",
        )
        lookup_response = asyncio.run(
            pos.pos_lookup_barcodes(DummyJsonRequest({"candidates": [first_barcode, "NOTREAL"]}), db)
        )
        assert_true(len(lookup_response["matches"]) == 1, "POS OCR lookup did not return exactly one saved barcode")
        assert_true(lookup_response["matches"][0]["barcode"] == first_barcode, "POS OCR lookup returned wrong barcode")
        add_again = asyncio.run(pos.pos_scan(DummyJsonRequest({"barcode": first_barcode}), db))
        assert_true(add_again["cart"]["count"] >= 2, "POS scan did not increment quantity")
        scanned_cart_item = db.query(PosCartItem).filter_by(variant_id=first.id).one()
        edited_cart = asyncio.run(pos.update_pos_item(scanned_cart_item.id, DummyJsonRequest({"qty": "3", "rate": "77"}), db))
        assert_true(edited_cart["items"][0]["qty"] == 3 and edited_cart["items"][0]["selling_price"] == "77.00", "POS cart update did not edit qty/rate")
        db.refresh(first)
        assert_true(str(first.selling_price) in {"11.00", "11"}, "POS rate edit changed LabelVariant master selling price")
        tally_add_response = pos.add_tally_item_to_cart(tally_family.id, db=db)
        assert_true(tally_add_response["ok"] and tally_add_response["item"]["source_type"] == "tally_item", "POS did not add local Tally catalog item")
        tally_cart_item = db.query(PosCartItem).filter_by(source_type="tally_item").one()
        assert_true(tally_cart_item.variant_id is None and tally_cart_item.barcode_snapshot == "", "Tally catalog cart line should not require a barcode variant")
        tally_update = asyncio.run(pos.update_pos_item(tally_cart_item.id, DummyJsonRequest({"qty": "2", "rate": "125"}), db))
        assert_true(tally_update["items"][-1]["selling_price"] == "125.00", "Tally catalog cart line rate was not editable")

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

        sale_scan = asyncio.run(pos.pos_scan(DummyJsonRequest({"barcode": first_barcode}), db))
        assert_true(sale_scan["ok"], "POS scan did not add item before checkout")
        active_scan_item = db.query(PosCartItem).filter_by(variant_id=first.id).one()
        asyncio.run(pos.update_pos_item(active_scan_item.id, DummyJsonRequest({"qty": "2", "rate": "88"}), db))
        sale_tally_add = pos.add_tally_item_to_cart(tally_family.id, db=db)
        assert_true(sale_tally_add["ok"], "POS did not add Tally item before checkout")
        sale_tally_item = db.query(PosCartItem).filter_by(source_type="tally_item").one()
        asyncio.run(pos.update_pos_item(sale_tally_item.id, DummyJsonRequest({"qty": "1", "rate": "125"}), db))
        active_cart = pos._find_active_cart(db)
        sale = checkout_cart(db, active_cart, payment_mode="cash")
        assert_true(sale.bill_number.startswith("SB-"), "sale bill number was not generated")
        assert_true(db.query(Sale).count() == 1, "checkout did not save exactly one sale")
        assert_true(db.query(SaleItem).filter_by(sale_id=sale.id).count() == 2, "checkout did not save all sale items")
        edited_sale_item = db.query(SaleItem).filter_by(sale_id=sale.id, label_variant_id=first.id).one()
        assert_true(str(edited_sale_item.rate) in {"88.00", "88"} and edited_sale_item.qty == 2, "checkout did not use edited barcode-line rate/qty")
        tally_sale_item = db.query(SaleItem).filter_by(sale_id=sale.id, tally_stock_item_name="Tally Imported Socks").one()
        assert_true(tally_sale_item.label_variant_id is None and tally_sale_item.barcode == "" and str(tally_sale_item.rate) in {"125.00", "125"}, "checkout did not save Tally catalog line snapshot")
        assert_true(pos._find_active_cart(db) is None, "checkout did not close the active cart")
        duplicate_checkout = pos.pos_checkout(payment_mode="cash", notes="", db=db)
        assert_true(getattr(duplicate_checkout, "status_code", None) == 303, "duplicate checkout did not redirect safely")
        assert_true(db.query(Sale).count() == 1, "duplicate checkout created another sale")

        print("Smoke checks passed")
    finally:
        db.close()


if __name__ == "__main__":
    main()
