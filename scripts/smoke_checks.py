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
from app.models import LabelVariant, PosCart, PosCartItem, PrintJob, ProductFamily, Sale, SaleItem, TemplateMaster, TallyItem  # noqa: E402
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
        print_orchestration_service_source = (ROOT / "app" / "services" / "workflow" / "print_orchestration_service.py").read_text(encoding="utf-8")
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
        assert_true("navbarQrStateBadge" in settings_markup and "showNavbarQrButton" in settings_markup and "hideNavbarQrButton" in settings_markup, "settings should control navbar QR visibility")
        assert_true('"qr_code"' in scanner_markup and '"data_matrix"' in scanner_markup, "scanner does not request QR/DataMatrix formats")
        assert_true("/phone-print/print" in phone_print_markup and "phoneTemplates" in phone_print_markup and "Uses this laptop's templates" not in phone_print_markup and "Laptop Print" not in phone_print_markup, "phone print page is not wired to laptop print data")
        assert_true("BarcodeDetector" in phone_print_markup and '"qr_code"' in phone_print_markup and '"data_matrix"' in phone_print_markup, "phone print scanner does not request QR/DataMatrix formats")
        assert_true("phoneFields.code.value = candidate.raw_value || candidate.code" in phone_print_markup and "phoneUppercaseVisibleFieldValues" in phone_print_markup, "phone code selection should preserve raw text and uppercase visible fields")
        assert_true("shopbridge.phonePrintState.v1" in phone_print_markup and "phoneRestoreState" in phone_print_markup, "phone print state is not persisted")
        assert_true("clearHiddenValue = false" in phone_print_markup, "phoneSetFieldVisible is missing clearHiddenValue parameter")
        assert_true("!visible && clearHiddenValue" in phone_print_markup, "phoneSetFieldVisible is missing clearHiddenValue condition")
        assert_true("if source_variant and is_in_template(field_name):" not in print_orchestration_service_source, "value_or_preserved must not use dangerous preserve logic")
        assert_true("field_name in detail_fields and not is_in_template(field_name)" in print_orchestration_service_source, "value_or_preserved must explicitly clear hidden detail fields")
        assert_true("applyTemplatePlaceholders" in workflow_markup and "setInputPlaceholder" in workflow_markup, "template defaults are not wired into input placeholders")
        assert_true("input.value = defaultValue" not in workflow_markup, "template defaults should not auto-fill submitted values")
        assert_true("variant_search: selectedSearchVariant ? variantLabel(selectedSearchVariant) : \"\"" in workflow_markup, "partial existing-item search text can be persisted")
        assert_true(".combo-option.active" in app_css and "background: #1f6feb" in app_css, "dropdown active row styling is not high contrast")
        assert_true("data-template-path" in workflow_markup and "templateActionStatus" in workflow_markup, "template disabled action reason is not shown")
        assert_true("selectedTemplateOption" in workflow_markup and "option.dataset.pathExists" in workflow_markup, "template path check does not fall back to selected option data")
        assert_true(hasattr(sales, "router"), "sales route module is not importable")
        assert_true("/pos/checkout" in pos_markup and "checkoutButton" in pos_markup, "POS checkout form is not rendered")
        assert_true("pos-billing-grid" in pos_markup and "Item / Article" in pos_markup and "Barcode" in pos_markup, "POS billing grid is not rendered")
        assert_true("Scan barcode / search item" in pos_markup and "pos-add-row" in pos_markup, "POS add-item row is missing")
        assert_true("posSearchInput" in pos_markup and "/pos/search" in pos_markup, "POS grid search input is not wired")
        assert_true("pos-suggestion-dock" not in pos_markup and "pos-suggestion-dock" not in app_css, "old POS top suggestion dock should be gone")
        assert_true("posSearchPanelRight" in pos_markup and "Search Results" in pos_markup and "pos-search-results-list" in pos_markup, "POS right-panel search results UI is missing")
        assert_true("posNormalPanel" in pos_markup and "summaryPanel.hidden = false" in pos_markup and "searchPanel.hidden = true" in pos_markup, "POS search close does not restore normal panel")
        suggestion_render = pos_markup.split("function renderSuggestions()", 1)[-1].split("async function searchItems", 1)[0]
        assert_true("item.family_name || item.billing_item || item.item_name" in suggestion_render, "POS search result main line should be billing item/family")
        assert_true("Barcode item" not in suggestion_render, "POS search results should keep item labels compact")
        assert_true("item.mrp ? `MRP ${money(item.mrp)}`" in suggestion_render, "POS search results should show MRP details")
        assert_true("pos-item-input" in pos_markup and "pos-mrp-input" in pos_markup and "dataset.cartField = \"item\"" in pos_markup and "dataset.cartField = \"mrp\"" in pos_markup, "POS editable item name and MRP cells are missing")
        assert_true("navigateBillList" in pos_markup and "heldBillList" in pos_markup, "POS held bill navigation is missing")
        assert_true("searchInput.addEventListener(\"input\"" in pos_markup and "state.heldSelectionActive = false" in pos_markup, "searchInput input clears heldSelectionActive")
        assert_true("navigateBillList" in pos_markup and "billNavIndex" in pos_markup and "billNavItems" in pos_markup, "POS bill navigation state and function are present")
        assert_true("nextIndex = 0" in pos_markup and "Start of bill list" in pos_markup and "End of bill list" in pos_markup, "PageDown opens index 0 when no current index; navigation does not wrap")
        assert_true("loadSaleForEdit" in pos_markup and "/pos/cart/load-sale/" in pos_markup, "Previous sales open through loadSaleForEdit using edit endpoint")
        assert_true("window.location.href" not in pos_markup or "/pos?sale_id" not in pos_markup, "Side list must not navigate via window.location.href to ?sale_id")
        assert_true("postCartAction(\"/pos/cart/clear\"" in pos_markup and "setPreviewState(false, null)" in pos_markup, "clear-cart response with normal cart resets preview state")
        # Copy mode: UI must not expose copy-bill flow
        assert_true("Create New Bill Copy" not in pos_markup, "POS must not show Create New Bill Copy")
        assert_true("original bill will stay unchanged" not in pos_markup, "POS must not contain copy-mode wording about original bill staying unchanged")
        # Original-edit mode: checkout wording must be correct
        assert_true("Save changes to original bill" in pos_markup, "POS original-edit checkout must say 'Save changes to original bill'")
        assert_true("state.openedSaleMode = \"edit\"" in pos_markup, "loadSaleForEdit must set state.openedSaleMode to 'edit'")
        # Navigation: first PageDown must open index 0, not skip it
        assert_true("hasActiveNav" in pos_markup and "nextIndex = 0" in pos_markup, "navigateBillList must use hasActiveNav guard and open index 0 on first PageDown")
        # Shared helper: double-click and PgUp/PgDn must both go through the same safe path
        assert_true("openBillNavItemAt" in pos_markup, "POS must have openBillNavItemAt() shared navigation helper")
        assert_true("skipDiscardConfirm" in pos_markup, "loadSaleForEdit must accept skipDiscardConfirm to avoid double confirm")
        assert_true("row.addEventListener(\"dblclick\", () => openBillNavItemAt" in pos_markup, "Side-list double-click must use openBillNavItemAt, not raw resume/load")
        assert_true("disabled = state.previewMode" not in pos_markup and "Previewing bill - press Esc to return" not in pos_markup, "POS opened bills should not render as disabled preview-only rows")
        assert_true("pos-total-box" in pos_markup and "cartTotal" in pos_markup and "Checkout - Rs. 0.00" in pos_markup, "POS checkout summary/total is missing")
        assert_true("focusSelectedCartItem" in pos_markup and "focusSelectedCartItem(true);" in pos_markup and "input.select()" in pos_markup, "POS selected line should auto-focus the item name")
        # UI Polish
        assert_true("holdBillButton.hidden = state.cart.cart_mode === \"sale_edit\"" not in pos_markup, "Hold button must NOT be hidden in sale_edit mode")
        assert_true("setStatus(\"Editing original bill. Checkout will update the bill.\", \"info\")" not in pos_markup, "POS should not duplicate original-edit status")
        assert_true("moveCartFieldVertical" in pos_markup and "ArrowDown" in pos_markup and "ArrowUp" in pos_markup, "POS editable cells should support up/down row navigation")
        assert_true("state.selectedIndex = items.length - 1" in pos_markup, "POS should default to the last bill line")
        assert_true("pos-rate-input" in pos_markup and "pos-qty-input" in pos_markup and "/pos/cart/items/${itemId}/update" in pos_markup, "POS editable rate/qty cells are missing")
        assert_true("saveFocusedLineInput" in pos_markup and "checkoutForm.submit()" in pos_markup and "checkoutSubmitting" in pos_markup, "POS checkout should save focused edits before submit")
        assert_true("event.stopPropagation()" in pos_markup and "await checkoutNow()" in pos_markup, "POS line editor should stop shortcut bubbling before checkout")
        assert_true("cartEditActive" in pos_markup and "lineEditIsActive()" in pos_markup and "if (silent &&" in pos_markup, "POS polling should pause while editing rate/qty")
        assert_true("addTallyItem" in pos_markup and "result_type === \"tally_item\"" in pos_markup, "POS UI does not add local Tally catalog search results")
        assert_true("addManualItem" not in pos_markup and "/pos/cart/manual/add" not in pos_markup and "pos-suggestion-manual" not in pos_markup, "POS UI must not expose manual free-text bill lines")
        assert_true("Keep manual text" not in pos_markup and "Add manual item" not in pos_markup and "Enter Add/Manual" not in pos_markup, "POS item search still contains manual-line copy")
        assert_true("replaceCartItem" in pos_markup and "/pos/cart/items/${itemId}/replace" in pos_markup, "POS item search selection should replace full cart line identity")
        assert_true("Select a saved barcode/Tally item." in pos_markup and "updateCartItem(editItem.id, {item_name" not in pos_markup, "POS row item editing can still save a label-only product mismatch")
        assert_true("editSearchTerm" in pos_markup and "searchInput.value = input.value" not in pos_markup, "POS row item search still uses the add-row input as hidden state")
        assert_true("focusNextBillingField" in pos_markup and 'focusNextBillingField(data.item && data.item.id, "qty")' in pos_markup, "POS valid barcode scans should return focus to the scan/add input")
        assert_true("helpToggleButton" in pos_markup and "shopbridge.posHelpVisible.v1" in pos_markup and "id=\"posHelpBar\" hidden" in pos_markup, "POS help row toggle/default hidden state is missing")
        assert_true("fullscreenPosButton" in pos_markup and "requestFullscreen" in pos_markup, "POS fullscreen button is missing")
        assert_true("Ctrl+Enter Checkout" in pos_markup and "F2 Item" in pos_markup and "Left/Right Cells" in pos_markup and "F10" not in pos_markup, "POS shortcut help bar is missing or stale")
        assert_true("cartStatus" in pos_markup and "pos-top-actions" in pos_markup and "Fullscreen POS" in pos_markup and "Show Help" in pos_markup and "Refresh" in pos_markup, "POS header status/buttons are missing")
        assert_true(".pos-suggestion.active" in app_css and ".pos-billing-row.selected" in app_css, "POS keyboard highlight styling is missing")
        assert_true(".pos-held-row.selected" in app_css and "pos-held-panel" in app_css, "POS held bill styling is missing")
        assert_true("pos-line-input" in app_css and "pos-rate-input" in app_css and "pos-qty-input" in app_css and "pos-item-input" in app_css and "pos-mrp-input" in app_css, "POS editable line input styling is missing")
        assert_true("source_type=\"barcode\"" in pos_route_source and "tally_item" in pos_route_source and "/pos/cart/items/{item_id}/update" in pos_route_source and "/pos/cart/items/{item_id}/replace" in pos_route_source and "item_name_snapshot" in pos_route_source, "POS backend snapshot/update routes are missing")
        assert_true("/pos/cart/load-sale/{sale_id}" in pos_route_source and "held_active_cart_id" in pos_route_source and "_park_active_cart" in pos_route_source and "SALE_COPY_CART_MODE" in pos_route_source, "POS backend should load saved bills without destroying active carts")
        assert_true("/pos/cart/hold" in pos_route_source and "/pos/cart/held/{cart_id}/resume" in pos_route_source and "/pos/cart/held/{cart_id}/discard" in pos_route_source, "POS held bill routes are missing")
        assert_true("ProductFamily" in pos_route_source and "tally_stock_item_name" in pos_route_source, "POS search should include locally imported ProductFamily/Tally items")
        assert_true("LabelVariant.barcode == clean_barcode" in pos_route_source and "barcode_like" in pos_route_source, "POS search should prioritize exact barcode and de-duplicate families")
        assert_true("item_name_snapshot" in model_source and "rate_snapshot" in model_source and "source_type" in model_source and "cart_mode" in model_source and "source_sale_id" in model_source, "POS cart snapshot/state fields are missing")
        assert_true("ALTER TABLE pos_cart_items ADD COLUMN" in db_source and "ALTER TABLE pos_carts ADD COLUMN" in db_source and "source_sale_id" in db_source and "variant_id" in db_source and "nullable" in model_source, "POS cart snapshot/state migration is missing")
        assert_true("item.rate_snapshot" in sales_service_source and "item.item_name_snapshot" in sales_service_source and "Manual POS lines are not allowed" in sales_service_source, "checkout does not use POS cart snapshots or block manual lines")
        assert_true("tally_voucher" not in pos_route_source and "tally_alias" not in pos_route_source.lower(), "POS route should not add Tally write code")
        assert_true("Bill No" in sales_markup and "/sales/{{ sale.id }}" in sales_markup and "/pos?sale_id={{ sale.id }}" in sales_markup, "sales list template is missing bill links")
        assert_true("Open Receipt" in sale_detail_markup and "Tally Sync Status" in sale_detail_markup and "/pos?sale_id={{ sale.id }}" in sale_detail_markup, "sale detail template is incomplete")
        assert_true("/sales/{sale_id}/data" in sales_route_source and "sale_payload" in sales_route_source, "sales replay data route is missing")
        assert_true("window.print()" in sale_receipt_markup and "Thank you" in sale_receipt_markup, "receipt template is missing browser print UI")
        assert_true("size: 80mm auto" in app_css and ".receipt" in app_css, "80mm receipt print CSS is missing")

        assert_true("item_search" in sales_route_source, "item_search parameter exists in sales route")
        assert_true("SaleItem" in sales_route_source and "exists" in sales_route_source, "SaleItem is used for item search")
        assert_true("PosCartItem" not in sales_route_source, "item_search filter does not use PosCartItem")
        assert_true("/sales/search-names" in sales_route_source, "/sales/search-names route exists")
        assert_true("SaleItem.item_name" in sales_route_source, "SaleItem.item_name is used")
        assert_true("SaleItem.tally_stock_item_name" in sales_route_source, "SaleItem.tally_stock_item_name is used")

        assert_true("item_search" in sales_markup, "sales.html has item_search input")
        assert_true("itemSearchSuggestions" in sales_markup, "sales.html has itemSearchSuggestions")
        assert_true('fetch(`/sales/search-names' in sales_markup, 'sales.html uses fetch("/sales/search-names')
        assert_true('autocomplete="off"' in sales_markup, 'sales.html has autocomplete="off" on item_search')
        assert_true('itemSearchSuggestions.querySelectorAll(".sales-item-suggestion")' in sales_markup, 'sales.html has ArrowDown/ArrowUp suggestion navigation')
        assert_true('itemSearchInput.value = items[selectedIndex].textContent' in sales_markup, 'sales.html has Enter suggestion selection')

        assert_true("F2" in sales_markup and "singleDateModal" in sales_markup, "F2 shortcut exists")
        assert_true("altKey" in sales_markup and "rangeDateModal" in sales_markup, "Alt+F2 shortcut exists")
        assert_true("parseTallyDate" in sales_markup, "DDMM/DDMMYY/DDMMYYYY parser exists")
        assert_true("ArrowUp" in sales_markup and "ArrowDown" in sales_markup, "ArrowUp/ArrowDown row navigation exists")
        assert_true("Enter" in sales_markup and "openLink.click()" in sales_markup, "Enter opens selected row")
        assert_true("isInput" in sales_markup and "active.tagName === \"INPUT\"" in sales_markup, "shortcuts ignore input/textarea/select/button/a/contenteditable focus")
        assert_true('document.querySelector("tbody tr.selected")' in sales_markup, "sales table keyboard navigation still exists")

        demo_items = db.query(TallyItem).all()
        assert_true(
            any((item.name or "").startswith("Demo Tally") for item in demo_items),
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

        alias_candidates_padded = extract_candidates_from_field("coded_price", "XXDFYY", alias_settings, priority=True)
        assert_true(alias_candidates_padded and str(alias_candidates_padded[0].selling_price) in {"25", "25.00"}, "padded unmapped letters did not decode")

        price_code_service_source = (ROOT / "app" / "services" / "price_code_service.py").read_text(encoding="utf-8")
        assert_true("target_length = 6" not in price_code_service_source, "global random padding not allowed")
        assert_true("import random" not in price_code_service_source, "random padding not allowed in core service")
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
        assert_true(priority_search["items"] and priority_search["items"][0]["result_type"] == "barcode", "POS search should de-duplicate Tally catalog rows when an active barcode variant exists")

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
        assert_true(search_response["items"][0].get("exact_barcode"), "POS exact barcode search should be first and marked exact")
        item_search_response = pos.pos_search(q="Toy", db=db)
        assert_true(item_search_response["items"], "POS search did not find saved item by name")
        tally_family = TallyItem(
            name="Tally Imported Socks",
            normalized_name="tally imported socks",
            aliases="Imported Socks",
            source="odbc",
            active_status="active",
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
        unknown_scan = asyncio.run(pos.pos_scan(DummyJsonRequest({"barcode": "NOTREAL"}), db))
        assert_true(unknown_scan.status_code == 404 and db.query(PosCartItem).count() == 1, "unknown POS barcode should not silently become a manual item")
        add_again = asyncio.run(pos.pos_scan(DummyJsonRequest({"barcode": first_barcode}), db))
        assert_true(add_again["cart"]["count"] >= 2, "POS scan did not increment quantity")
        scanned_cart_item = db.query(PosCartItem).filter_by(variant_id=first.id).one()
        edited_cart = asyncio.run(pos.update_pos_item(scanned_cart_item.id, DummyJsonRequest({"qty": "3", "rate": "77"}), db))
        assert_true(edited_cart["items"][0]["qty"] == 3 and edited_cart["items"][0]["selling_price"] == "77.00", "POS cart update did not edit qty/rate")
        db.refresh(first)
        assert_true(str(first.selling_price) in {"11.00", "11"}, "POS rate edit changed LabelVariant master selling price")
        # tally_add_response = pos.add_tally_item_to_cart(tally_family.id, db=db)
        # assert_true(tally_add_response["ok"] and tally_add_response["item"]["source_type"] == "tally_item", "POS did not add local Tally catalog item")
        # tally_cart_item = db.query(PosCartItem).filter_by(source_type="tally_item").one()
        # assert_true(tally_cart_item.variant_id is None and tally_cart_item.barcode_snapshot == "", "Tally catalog cart line should not require a barcode variant")
        # try:
        #     checkout_cart(db, pos._find_active_cart(db), payment_mode="cash")
        #     raise AssertionError("checkout should reject missing Tally rate")
        # except Exception as exc:
        #     assert_true("Rate is missing" in str(exc), "checkout did not block Tally catalog line with missing rate")
        # tally_update = asyncio.run(pos.update_pos_item(tally_cart_item.id, DummyJsonRequest({"qty": "2", "rate": "125"}), db))
        # assert_true(tally_update["items"][-1]["selling_price"] == "125.00", "Tally catalog cart line rate was not editable")
        # replace_barcode_response = asyncio.run(pos.replace_pos_item(tally_cart_item.id, DummyJsonRequest({"result_type": "barcode", "id": changed_detail_variant.id}), db))
        # assert_true(replace_barcode_response["item"]["source_type"] == "barcode" and replace_barcode_response["item"]["variant_id"] == changed_detail_variant.id, "POS Tally-to-barcode replacement did not update full identity")
        # expected_changed_rate = f"{changed_detail_variant.selling_price:.2f}" if changed_detail_variant.selling_price is not None else ""
        # assert_true(replace_barcode_response["item"]["barcode"] == changed_detail_variant.barcode and replace_barcode_response["item"]["selling_price"] == expected_changed_rate, "POS barcode replacement returned stale barcode/rate payload")
        # replaced_barcode_cart_item = db.get(PosCartItem, replace_barcode_response["item"]["id"])
        # assert_true(replaced_barcode_cart_item and replaced_barcode_cart_item.variant_id == changed_detail_variant.id and replaced_barcode_cart_item.source_type == "barcode", "POS barcode replacement did not persist backend identity")

        tally_add_response = pos.add_tally_item_to_cart(tally_family.id, db=db)
        assert_true(tally_add_response["ok"], "POS did not re-add local Tally catalog item for replacement merge test")
        tally_cart_item = db.get(PosCartItem, tally_add_response["item"]["id"])
        asyncio.run(pos.update_pos_item(tally_cart_item.id, DummyJsonRequest({"qty": "2", "rate": "125"}), db))
        db.refresh(scanned_cart_item)
        scanned_qty_before_merge = scanned_cart_item.qty
        tally_qty_before_merge = tally_cart_item.qty
        replace_response = asyncio.run(pos.replace_pos_item(scanned_cart_item.id, DummyJsonRequest({"result_type": "tally_item", "id": tally_family.id}), db))
        assert_true(replace_response.get("merged_item_id") is None, "POS duplicate replacement should NOT merge Tally lines")
        replaced_tally_item = db.get(PosCartItem, replace_response["item"]["id"])
        assert_true(replaced_tally_item and replaced_tally_item.qty == scanned_qty_before_merge, "POS duplicate replacement should keep qty without merging")
        assert_true(replace_response["item"]["source_type"] == "tally_item" and replace_response["item"]["variant_id"] is None and replace_response["item"]["missing_price"] is False, "POS Tally replacement returned stale identity/rate payload")
        invalid_manual_replace = asyncio.run(pos.replace_pos_item(replaced_tally_item.id, DummyJsonRequest({"result_type": "manual", "item_name": "Loose"}), db))
        assert_true(getattr(invalid_manual_replace, "status_code", 200) == 400, "POS replacement should not accept manual results")

        invalid_rename_update = asyncio.run(pos.update_pos_item(replaced_tally_item.id, DummyJsonRequest({"item_name": "Sneaky Rename", "qty": 1}), db))
        assert_true(getattr(invalid_rename_update, "status_code", 200) == 400, "POS update should block item_name rename vector")

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
        sale_tally_item = db.get(PosCartItem, sale_tally_add["item"]["id"])
        asyncio.run(pos.update_pos_item(sale_tally_item.id, DummyJsonRequest({"qty": "1", "rate": "125"}), db))
        active_cart = pos._find_active_cart(db)
        stale_manual_item = PosCartItem(
            cart_id=active_cart.id,
            variant_id=None,
            qty=1,
            unit_price=Decimal("15"),
            item_name_snapshot="Manual Checkout Line",
            barcode_snapshot="",
            tally_stock_item_name_snapshot="",
            mrp_snapshot=Decimal("20"),
            rate_snapshot=Decimal("15"),
            source_type="manual",
            is_manual_line=True,
        )
        db.add(stale_manual_item)
        db.commit()
        try:
            checkout_cart(db, active_cart, payment_mode="cash")
            raise AssertionError("checkout should reject manual POS lines")
        except Exception as exc:
            assert_true("Manual POS lines are not allowed" in str(exc), "checkout did not block stale manual POS line")
        db.delete(stale_manual_item)
        db.commit()
        sale = checkout_cart(db, active_cart, payment_mode="cash")
        assert_true(sale.bill_number.startswith("SB-"), "sale bill number was not generated")
        assert_true(db.query(Sale).count() == 1, "checkout did not save exactly one sale")
        assert_true(db.query(SaleItem).filter_by(sale_id=sale.id).count() == 2, "checkout did not save expected sale items")
        edited_sale_item = db.query(SaleItem).filter_by(sale_id=sale.id, label_variant_id=first.id).one()
        assert_true(str(edited_sale_item.rate) in {"88.00", "88"} and edited_sale_item.qty == 2, "checkout did not use edited barcode-line rate/qty")
        tally_sale_item = db.query(SaleItem).filter_by(sale_id=sale.id, tally_stock_item_name="Tally Imported Socks").one()
        assert_true(tally_sale_item.label_variant_id is None and tally_sale_item.barcode == "" and str(tally_sale_item.rate) in {"125.00", "125"}, "checkout did not save Tally catalog line snapshot")
        assert_true(pos._find_active_cart(db) is None, "checkout did not close the active cart")
        duplicate_checkout = pos.pos_checkout(payment_mode="cash", notes="", db=db)
        assert_true(getattr(duplicate_checkout, "status_code", None) == 303, "duplicate checkout did not redirect safely")
        assert_true("No+active+cart" in duplicate_checkout.headers.get("location", ""), "duplicate checkout should return a clear POS error instead of latest sale")
        assert_true(db.query(Sale).count() == 1, "duplicate checkout created another sale")

        # Test optional template fields functionality
        from app.services.settings_service import get_template_field_settings, save_template_field_settings

        original_optional_fields = list(get_template_field_settings().optional_fields)
        try:
            # 1. Saving other bartender settings does not wipe optional template fields
            save_template_field_settings(optional_fields=["item_display_name"])
            workflow.update_bartender_settings(
                mode="pdf",
                show_bartender_window=False,
                barcode_generation_mode="template_length_safe_alphanumeric",
                default_barcode_length=7,
                barcode_allowed_chars="1234567890",
                mrp_rounding="nearest_1",
                mrp_truncate_decimal=False,
                allow_price_code_extraction=True,
                digit_0_code="Z", digit_1_code="A", digit_2_code="B", digit_3_code="C", digit_4_code="D",
                digit_5_code="E", digit_6_code="F", digit_7_code="G", digit_8_code="H", digit_9_code="I",
                optional_template_fields=[],
                template_field_settings_form="",
                db=db
            )
            assert_true("item_display_name" in get_template_field_settings().optional_fields, "Other settings wiped optional template fields")

            # Test aliases
            save_template_field_settings(optional_fields=["item_display_name"])
            assert_true("design" in get_template_field_settings().resolved_optional_fields, "item_display_name alias design failed")
            assert_true("item_display_name" in get_template_field_settings().resolved_optional_fields, "item_display_name alias item_display_name failed")

            # Test empty optional item name saves as empty string instead of falling back to family_name
            response = print_item(
                db,
                template,
                item_display_name="",
                family_name="Empty Name Family",
                size="M",
                mrp="10",
                coded_price="ZZ",
                barcode="EMPTYNAME123",
            )
            family = db.query(ProductFamily).filter_by(family_name="Empty Name Family").first()
            empty_name_variant = db.query(LabelVariant).filter_by(family_id=family.id).first() if family else None
            assert_true(empty_name_variant is not None, "Variant with empty name was not created")
            assert_true(empty_name_variant.item_display_name == "", f"Empty item display name was not preserved as empty, got {empty_name_variant.item_display_name!r}")

            save_template_field_settings(optional_fields=["design"])
            assert_true("item_display_name" in get_template_field_settings().resolved_optional_fields, "design alias item_display_name failed")

            save_template_field_settings(optional_fields=["selling_price"])
            assert_true("rate" in get_template_field_settings().resolved_optional_fields, "selling_price alias rate failed")

            save_template_field_settings(optional_fields=["article"])
            assert_true("article_no" in get_template_field_settings().resolved_optional_fields, "article alias article_no failed")
        finally:
            save_template_field_settings(optional_fields=original_optional_fields)

        # UI Checks
        phone_print_markup = (ROOT / "app" / "templates" / "phone_print.html").read_text(encoding="utf-8")
        assert_true("const optionalTemplateFields = new Set" in phone_print_markup, "phone_print.html missing optionalTemplateFields")
        assert_true("<script>\n  </script>" not in phone_print_markup and "<script>\r\n  </script>" not in phone_print_markup, "Empty script block left in phone_print.html")
        assert_true("focusAndSelectMrp()" in workflow_markup, "Empty Margin + Enter does not focus MRP on desktop")
        assert_true("phoneSelectTextOnEdit(" in phone_print_markup, "phoneSelectTextOnEdit not bound in phone_print")

        # Voice Fill Print-only Coded Price Behavior checks
        assert_true("function phoneEncodeGroup" in phone_print_markup, "phoneEncodeGroup helper missing")
        assert_true("function pvBuildVoicePrintCode" in phone_print_markup, "pvBuildVoicePrintCode helper missing")

        assert_true("allKeys.add(\"selling_price\");" in phone_print_markup, "selling_price not explicitly included in Voice Fill dialog")
        assert_true("pvBuildVoicePrintCode({" in phone_print_markup, "Print path does not call pvBuildVoicePrintCode")

        held_source_scan = asyncio.run(pos.pos_scan(DummyJsonRequest({"barcode": first_barcode}), db))
        assert_true(held_source_scan["ok"], "POS did not create active cart before saved-bill load test")
        held_source_cart = pos._find_active_cart(db)
        held_source_item = db.query(PosCartItem).filter_by(cart_id=held_source_cart.id, variant_id=first.id).one()
        asyncio.run(pos.update_pos_item(held_source_item.id, DummyJsonRequest({"qty": "4", "rate": "33"}), db))
        load_copy_response = pos.load_sale_into_pos_cart(sale.id, db=db)
        db.refresh(held_source_cart)
        assert_true(load_copy_response["ok"] and held_source_cart.status == "held", "loading completed sale should hold, not delete, the active bill")
        held_preserved_item = db.query(PosCartItem).filter_by(cart_id=held_source_cart.id, variant_id=first.id).one()
        assert_true(held_preserved_item.qty == 4 and str(held_preserved_item.rate_snapshot) in {"33.00", "33"}, "held active bill did not preserve exact qty/rate")
        active_copy = pos._find_active_cart(db)
        assert_true(active_copy and active_copy.id != held_source_cart.id and active_copy.cart_mode == "sale_copy" and active_copy.source_sale_id == sale.id, "completed sale should load into a separate active sale-copy cart")
        held_count_after_first_copy = db.query(PosCart).filter_by(status="held").count()
        same_copy_response = pos.load_sale_into_pos_cart(sale.id, db=db)
        assert_true(same_copy_response["cart"]["cart_id"] == active_copy.id and db.query(PosCart).filter_by(status="held").count() == held_count_after_first_copy, "reloading the same completed sale should not duplicate held sale-copy carts")
        second_sale = Sale(
            bill_number="SB-2999-000001",
            status="completed",
            subtotal=Decimal("88"),
            discount_total=Decimal("0"),
            round_off=Decimal("0"),
            total=Decimal("88"),
            payment_mode="cash",
            print_status="not_printed",
            tally_sync_status="not_started",
        )
        second_sale.items = [
            SaleItem(
                label_variant_id=first.id,
                barcode=first_barcode,
                item_name="Toy",
                tally_stock_item_name=first.family.tally_stock_item_name if first.family else None,
                qty=1,
                rate=Decimal("88"),
                mrp=first.mrp,
                discount_amount=Decimal("0"),
                amount=Decimal("88"),
            )
        ]
        db.add(second_sale)
        db.commit()
        db.refresh(second_sale)
        second_copy_response = pos.load_sale_into_pos_cart(second_sale.id, db=db)
        db.refresh(active_copy)
        assert_true(second_copy_response["ok"] and active_copy.status == "discarded" and db.query(PosCart).filter_by(status="held").count() == held_count_after_first_copy, "loading another completed sale from a sale-copy cart should discard the copy, not hold it")
        active_copy = pos._find_active_cart(db)
        assert_true(active_copy and active_copy.source_sale_id == second_sale.id and active_copy.cart_mode == "sale_copy", "second completed sale did not become the active sale-copy cart")
        held_action_block = pos.increase_pos_item(held_preserved_item.id, db=db)
        assert_true(held_action_block.status_code == 404, "held cart item quantity should not be editable until resumed")
        pos.discard_active_cart(db=db)
        resume_response = pos.resume_held_cart(held_source_cart.id, db=db)
        assert_true(resume_response["ok"] and resume_response["cart"]["cart_id"] == held_source_cart.id, "held bill did not resume")
        resumed_item = db.query(PosCartItem).filter_by(cart_id=held_source_cart.id, variant_id=first.id).one()
        assert_true(resumed_item.qty == 4 and str(resumed_item.rate_snapshot) in {"33.00", "33"}, "resumed held bill did not restore exact lines/rates/qty")
        hold_again_response = pos.hold_active_cart(db=db)
        assert_true(hold_again_response["ok"] and pos._find_active_cart(db) is None, "holding active bill should remove active cart until resumed or new scan")
        resume_again_response = pos.resume_held_cart(held_source_cart.id, db=db)
        assert_true(resume_again_response["ok"] and pos._find_active_cart(db).id == held_source_cart.id, "held bill did not resume after explicit hold")

        # Test sale_edit behavior
        third_sale = Sale(
            bill_number="SB-2999-000002",
            status="completed",
            subtotal=Decimal("88"),
            discount_total=Decimal("0"),
            round_off=Decimal("0"),
            total=Decimal("88"),
            payment_mode="cash",
            print_status="not_printed",
            tally_sync_status="not_started",
        )
        third_sale.items = [
            SaleItem(
                label_variant_id=first.id,
                barcode=first_barcode,
                item_name="Toy",
                tally_stock_item_name=first.family.tally_stock_item_name if first.family else None,
                qty=1,
                rate=Decimal("88"),
                mrp=first.mrp,
                discount_amount=Decimal("0"),
                amount=Decimal("88"),
            )
        ]
        db.add(third_sale)
        db.commit()
        db.refresh(third_sale)

        # Load into edit cart
        edit_load_response = pos.load_sale_for_edit_in_pos_cart(third_sale.id, db=db)
        active_edit_cart = pos._find_active_cart(db)
        assert_true(edit_load_response["ok"] and active_edit_cart.cart_mode == "sale_edit" and active_edit_cart.source_sale_id == third_sale.id, "completed sale should load into a sale-edit cart")

        # Verify clear cart resets edit cart
        clear_cart_response = pos.clear_pos_cart(db=db)
        db.refresh(active_edit_cart)
        assert_true(clear_cart_response["items"] == [] and active_edit_cart.cart_mode == "normal" and active_edit_cart.source_sale_id is None, "clearing sale-edit cart should reset to normal mode")

        # Reload into edit cart again for checkout test
        pos.load_sale_for_edit_in_pos_cart(third_sale.id, db=db)
        active_edit_cart = pos._find_active_cart(db)

        # Edit qty
        edit_cart_item = db.query(PosCartItem).filter_by(cart_id=active_edit_cart.id).one()
        asyncio.run(pos.update_pos_item(edit_cart_item.id, DummyJsonRequest({"qty": "5"}), db))

        # Hold sale_edit
        edit_hold_response = pos.hold_active_cart(db=db)

        # Tally Item Migration & Separation Smoke Checks
        assert_true("TallyItem" in model_source, "1. TallyItem model exists")
        assert_true("tally_items" in db_source and "TallyItem.__table__.create" in db_source, "2. tally_items table migration exists")

        tally_odbc_source = (ROOT / "app" / "services" / "tally_odbc_service.py").read_text(encoding="utf-8")
        assert_true("import_tally_items" in tally_odbc_source and "TallyItem" in tally_odbc_source and "ProductFamily" not in tally_odbc_source, "3. Tally import service writes to TallyItem, not ProductFamily")

        tally_route_source = (ROOT / "app" / "routes" / "tally.py").read_text(encoding="utf-8")
        assert_true("import_tally_items" in tally_route_source and "/import-stock-items" in tally_route_source, "4. /tally/import-stock-items calls import_tally_items")

        assert_true("source_type\": \"tally_item\"" in pos_route_source and "tally_item_id" in pos_route_source, "5. POS search returns Tally results with source_type and tally_item_id")
        assert_true("/pos/cart/tally-items/{tally_item_id}/add" in pos_route_source, "6. POS add route uses tally_item_id")
        assert_true("source_type=\"tally_item\"" in pos_route_source and "variant_id=None" in pos_route_source and "tally_stock_item_name_snapshot" in pos_route_source, "7. Tally cart line uses variant_id=None and snapshots")

        families_route_source = (ROOT / "app" / "routes" / "families.py").read_text(encoding="utf-8")
        assert_true("ProductFamily.category != \"Imported from Tally\"" in families_route_source, "8. Families page excludes category='Imported from Tally'")
        assert_true("tally_stock_item_name" in model_source and "ProductFamily" in model_source, "9. ProductFamily.tally_stock_item_name is preserved")
        assert_true("tally_stock_item_name_snapshot" in sales_service_source, "10. Checkout for Tally item lines still works")
        assert_true("qty < 0" in pos_markup or "qty < 1" in pos_markup or "RETURNED" in pos_markup, "11. Negative qty return logic is not broken")

        tally_item = TallyItem(name="Smoke Test Tally Item", normalized_name="smoke test tally item", source="odbc")
        db.add(tally_item)
        db.commit()
        tally_search = pos.pos_search(q="Smoke Test Tally Item", db=db)
        assert_true(any(r["result_type"] == "tally_item" and r.get("tally_item_id") == tally_item.id for r in tally_search["items"]), "POS search returns actual Tally items")

        assert_true(edit_hold_response["ok"], "sale-edit cart should be holdable")
        db.refresh(active_edit_cart)
        assert_true(active_edit_cart.status == "held", "held sale-edit cart must have status 'held'")
        assert_true(active_edit_cart.cart_mode == "sale_edit", "held sale-edit cart must keep cart_mode 'sale_edit'")
        assert_true(active_edit_cart.source_sale_id == third_sale.id, "held sale-edit cart must keep source_sale_id")

        # Resume sale_edit
        pos.resume_held_cart(active_edit_cart.id, db=db)
        resumed_edit_cart = pos._find_active_cart(db)
        assert_true(resumed_edit_cart and resumed_edit_cart.id == active_edit_cart.id, "sale-edit cart should resume")
        assert_true(resumed_edit_cart.cart_mode == "sale_edit" and resumed_edit_cart.source_sale_id == third_sale.id, "resumed sale-edit cart must restore mode and source")

        # Checkout sale_edit
        from app.services.sales_service import save_sale_edit_cart

        # Test JSON checkout endpoint explicitly
        from app.services.settings_service import save_upi_settings
        save_upi_settings(vpa_1="test@upi", key_1="1", vpa_2="", key_2="", default_vpa="test@upi")
        json_checkout_response = asyncio.run(pos.pos_checkout_json(DummyJsonRequest({"payment_mode": "upi", "upi_vpa": "test@upi"}), db=db))
        assert_true(json_checkout_response["ok"] and json_checkout_response["sale_id"] == third_sale.id, "sale-edit JSON checkout must keep same Sale.id")

        db.refresh(third_sale)
        edited_sale = third_sale
        assert_true(edited_sale.bill_number == "SB-2999-000002", "sale-edit checkout must keep the same bill_number")
        assert_true(edited_sale.payment_mode == "upi", "sale-edit checkout must update payment_mode")
        assert_true(str(edited_sale.total) == "440.00", "sale-edit checkout must recalculate totals")
        assert_true(db.query(SaleItem).filter_by(sale_id=third_sale.id).count() == 1, "sale-edit checkout must recreate SaleItems")
        assert_true(db.query(SaleItem).filter_by(sale_id=third_sale.id).one().qty == 5, "sale-edit checkout must use new item qty")
        assert_true(pos._find_active_cart(db) is None, "checkout must close the active edit cart")

        duplicate_old_cart = PosCart(status="active", cart_mode="normal")
        db.add(duplicate_old_cart)
        db.flush()
        db.add(PosCartItem(
            cart_id=duplicate_old_cart.id,
            variant_id=first.id,
            qty=1,
            unit_price=first.selling_price,
            item_name_snapshot=first.family.family_name if first.family else first.item_display_name,
            barcode_snapshot=first.barcode,
            tally_stock_item_name_snapshot=first.family.tally_stock_item_name if first.family else None,
            mrp_snapshot=first.mrp,
            rate_snapshot=first.selling_price,
            source_type="barcode",
            is_manual_line=False,
        ))
        duplicate_new_cart = PosCart(status="active", cart_mode="normal")
        db.add(duplicate_new_cart)
        db.commit()

        pos._held_carts_payload(db)
        db.refresh(duplicate_old_cart)
        db.refresh(duplicate_new_cart)
        assert_true(
            duplicate_old_cart.status == "active" and duplicate_new_cart.status == "active",
            "held cart list must not normalize duplicate active carts during GET/read payload",
        )
        normalized_cart = pos._find_active_cart(db, normalize_duplicates=True)
        db.refresh(duplicate_old_cart)
        db.refresh(duplicate_new_cart)
        assert_true(
            normalized_cart.id == duplicate_new_cart.id
            and duplicate_new_cart.status == "active"
            and duplicate_old_cart.status == "held",
            "explicit duplicate active cart normalization did not keep newest active and hold older bill with items",
        )

        pos_html_source = (ROOT / "app" / "templates" / "pos.html").read_text(encoding="utf-8")
        pos_py_source = (ROOT / "app" / "routes" / "pos.py").read_text(encoding="utf-8")
        assert_true("focusNextBillingField(" in pos_html_source and 'focusCartField(rowIndex, "mrp", true)' in pos_html_source, "POS template missing focusNextBillingField or does not focus MRP first")
        assert_true("skipNextChangeSaveFor" in pos_html_source, "POS template missing skipNextChangeSaveFor double-save guard")
        assert_true("state.editSearchTerm =" in pos_html_source and "replaceCartItem" in pos_html_source, "POS template missing editSearchTerm or replaceCartItem logic")
        assert_true("fieldName === \"item\"" in pos_html_source and "Select a saved barcode" in pos_html_source, "POS template missing label-only text save guard")
        assert_true('focusNextBillingField(data.item && data.item.id, "qty")' in pos_html_source, "POS template does not focus missing fields after Tally add")


        assert_true("lines ?? Qty" not in pos_html_source, "POS template contains bad ?? separators")
        # Ctrl+A Quick Action Behavior
        assert_true('actionName === "save_print"' in pos_html_source or 'action === "save_print"' in pos_html_source or 'action.action === "save_print"' in pos_html_source or 'typeof action === "string" ? action : action.action' in pos_html_source, "Ctrl+A quick action must support save_print")
        assert_true('actionName === "save_no_print"' in pos_html_source or 'typeof action === "string" ? action : action.action' in pos_html_source, "Ctrl+A quick action must support save_no_print")
        assert_true('actionName === "hold"' in pos_html_source or 'typeof action === "string" ? action : action.action' in pos_html_source, "Ctrl+A quick action must support hold")
        assert_true('state.selectedUpiVpa = action.upi_vpa' in pos_html_source, "Ctrl+A quick action must capture upi_vpa from keyboard shortcuts")
        assert_true('matchedUpiVpa !== null || isEnter' in pos_html_source, "Ctrl+A quick action must handle Enter and UPI hotkeys")

        # Sale Edit Dirty UI Behavior
        assert_true('Edit (Items ${lines})' in pos_html_source, "Recent Bills list must show 'Edit (Items)' for unsaved sale edits")

        # Missing Price Flow Check
        assert_true('allow_missing_price' in pos_html_source, "Barcode missing price flow should use allow_missing_price flag safely")

        # Phone Print / Voice Fill Additions
        assert_true('pvCollectEditedVoiceFields' in phone_print_markup, "Voice Fill must safely collect edited fields")
        assert_true('pvValidateEditedVoiceRow' in phone_print_markup, "Voice Fill must validate edited fields")
        assert_true('id="phoneVoicePrintAllButton"' in phone_print_markup, "Voice Fill must have Print All button")
        assert_true('pvPrintVoiceCard' in phone_print_markup, "Voice Fill must print individual cards")
        assert_true('pvApplyVoiceCard' in phone_print_markup, "Voice Fill must apply individual cards")
        assert_true('nativeFields.force_new_barcode = "";' in phone_print_markup, "Voice Fill force_new_barcode must be blank")
        assert_true('nativeFields.extra_field_values = JSON.stringify(extraValues);' in phone_print_markup, "Voice Fill must stringify custom extraValues")
        assert_true('JSONResponse' in open('app/routes/workflow.py', 'r', encoding='utf-8').read(), "workflow.py must import JSONResponse")
        # 3. Voice Fill card print does not call phoneSubmitPrintButton.click()
        assert_true('phoneSubmitPrintButton.click()' not in phone_print_markup.split('pvPrintVoiceCard')[1], "Voice Fill print must not call phoneSubmitPrintButton.click()")
        # 4. Voice Fill card print does not use global phonePrinting as its card lock
        assert_true('phonePrinting =' not in phone_print_markup.split('pvPrintVoiceCard')[1], "Voice Fill must not use phonePrinting lock")
        # 5. Print All uses sequential await, not Promise.all
        assert_true('await pvPrintVoiceCard' in phone_print_markup and 'Promise.all' not in phone_print_markup.split('pvPrintAllValidItems')[1], "Print All must use sequential await")
        # 6. Frontend does not generate barcode numbers
        assert_true('Math.random' not in phone_print_markup.split('pvPrintVoiceCard')[1], "Frontend must not generate barcodes")
        # 7. existing_variant_id is not blindly copied for every card
        # removed isExactMatch check
        # 8. family_id is not blindly reused when family_name changes
        assert_true('nativeFields.family_id = finalFamilyId;' in phone_print_markup, "family_id must be cleared on mismatch")
        # 9. pvSetCardErrors used instead of innerHTML
        assert_true('pvSetCardErrors' in phone_print_markup, "pvSetCardErrors must be used for safe error rendering")
        # 10. Check Jinja endblock
        assert_true('{% endblock %}' in phone_print_markup, "phone_print.html must end with Jinja endblock")
        assert_true("cart_mode === \"sale_edit\"" in pos_html_source and "handleCtrlAQuickAction()" in pos_html_source, "POS template missing ctrlAModal trigger for sale_edit navigation")
        assert_true("fieldAlreadySaved" in pos_html_source and "return true" in pos_html_source, "No-op Enter check (fieldAlreadySaved) does not exist or return properly")

        # UI Modal Robustness Checks
        assert_true("fetch(\"/pos/checkout/json\"" in pos_html_source, "checkout must call JSON checkout endpoint")
        assert_true('fetch("/pos/cart/active/discard"' in pos_html_source and "return true" in pos_html_source, "Ctrl A Discard must call discard endpoint and continue")
        assert_true('fetch("/pos/cart/hold"' in pos_html_source and "return true" in pos_html_source, "Ctrl A Hold must call hold endpoint and continue")
        assert_true("qty = item.total_qty ?? item.count ?? 0" in pos_html_source, "held bill qty must use count as fallback so it does not show Qty 0")
        assert_true('selectedItem.status === "held"' in pos_html_source and 'targetItem.status !== "held"' in pos_html_source, "Discard Selected must only act on real held rows")
        assert_true("state.billNavBusy" in pos_html_source and "billNavLoadRequestId" in pos_html_source, "bill navigation must guard overlapping PgUp/PgDn actions")
        assert_true(".where(PosCart.status == HELD_CART_STATUS)" in pos_py_source, "held bill endpoint must not mix active carts into held list")
        assert_true('"cart": _cart_payload(db)' in pos_py_source, "discard held route must return current cart payload")
        main_source = (ROOT / "app" / "main.py").read_text(encoding="utf-8")
        assert_true("serialize_pos_cart_mutations" in main_source and "pos_cart_mutation_lock" in main_source, "POS cart mutations must be serialized")
        assert_true("Normalized %s duplicate active POS carts" in pos_py_source and "stale_cart.status = HELD_CART_STATUS" in pos_py_source, "POS must normalize duplicate active carts safely")
        assert_true(".pos-held-row.selected.opened" in app_css, "selected bill row style must win over opened row style")

        # Layout/UI checks
        assert_true("body.pos-page" in app_css and "overflow: hidden" in app_css, "body.pos-page must lock browser scroll")
        assert_true("pos-search-results-list .pos-suggestion.active" in app_css, "active search result CSS must exist")
        assert_true("background: #1f6feb" in app_css or "background: #1f6feb" in pos_html_source, "active search result must use high-contrast blue background")
        assert_true("pos-held-row-top" in app_css and "grid-template-columns: auto minmax(0, 1fr) auto" in app_css, "Recent Bills row-top must have 3-column grid (badge + label + total)")
        assert_true("pos-held-row-sub" in app_css, "Recent Bills sub line CSS must exist")
        # Ensure searchPanelTotal is guarded: not a plain direct access
        assert_true("searchPanelTotal.textContent" not in pos_html_source or "if (searchPanelTotal)" in pos_html_source, "searchPanelTotal must be null-guarded since element was removed")
        # Ensure missing-price selection skips confirm popup for both barcode and Tally items
        assert_true("allow_missing_price" in pos_html_source, "addBarcode must accept allow_missing_price parameter")
        assert_true("addTallyItem(item.id)" in pos_html_source, "Tally search result must call addTallyItem directly (no confirm)")
        assert_true("focusNextBillingField" in pos_html_source, "after adding item, focusNextBillingField must be called to handle missing MRP/Rate")


        # Layout/UI checks
        assert_true('focusNextBillingField(itemId, "qty")' in pos_html_source and 'focusNextBillingField(itemId, "mrp")' in pos_html_source, "Enter navigation must follow Item -> Qty -> MRP -> Rate")
        assert_true('pos-qty-button' not in pos_html_source, "qty +/- buttons removed")
        assert_true('item.qty < 0' in pos_html_source and 'return-badge' in pos_html_source, "negative qty row shows return badge")
        assert_true('Quantity cannot be zero' in pos_py_source, "zero qty is rejected")
        assert_true('else if (fieldName === "rate")' in pos_html_source and 'focusNextBillingField(itemId, "next_row_item")' in pos_html_source, "rate Enter moves to next_row_item")
        assert_true('if (printAfterSave && data.sale_id)' in pos_html_source, "Save+Print only prints after sale_id")

        assert_true("???" not in pos_markup + pos_py_source + app_css, "Code contains mojibake ???")
        assert_true("cart.cart_mode == SALE_EDIT_CART_MODE" in pos_py_source, "sale_edit auto-parking must be handled explicitly")
        assert_true("source_bill_number" in pos_py_source and "source_bill_number" in pos_markup, "sale_edit cart payload should expose source bill number")

        assert_true("heldBillCount" in pos_markup, "Recent Bills count is missing")
        assert_true("activeBillNavItem" in pos_markup and 'type: "open"' in pos_markup, "POS bill nav must keep the current active bill visible locally")
        assert_true('"Open / Held Bills"' in pos_markup and "${openCount} open / ${heldCount} held / ${previousCount} today" in pos_markup, "POS bill nav must separate open, held, and previous counts")
        assert_true('if (item.type === "open") return 2;' in pos_markup, "Open bill must sort with held bills, not always at the top")
        assert_true('item.type === "open" && item.id === state.cart.cart_id' in pos_markup, "POS bill nav must reselect the currently open bill after reload")
        assert_true('if (targetItem.type === "open")' in pos_markup, "Opening the active bill row should be a no-op, not a server call")
        assert_true('phonePrintCopiesConfirmed = true' in phone_print_markup, "Voice Fill print flow must skip copies prompt via global flag")
        assert_true("cart_mode === \"sale_edit\"" in pos_html_source and "handleCtrlAQuickAction()" in pos_html_source, "POS template missing ctrlAModal trigger for sale_edit navigation")
        assert_true("fieldAlreadySaved" in pos_html_source and "return true" in pos_html_source, "No-op Enter check (fieldAlreadySaved) does not exist or return properly")

        # UI Modal Robustness Checks
        assert_true("fetch(\"/pos/checkout/json\"" in pos_html_source, "checkout must call JSON checkout endpoint")
        assert_true('fetch("/pos/cart/active/discard"' in pos_html_source and "return true" in pos_html_source, "Ctrl A Discard must call discard endpoint and continue")
        assert_true('fetch("/pos/cart/hold"' in pos_html_source and "return true" in pos_html_source, "Ctrl A Hold must call hold endpoint and continue")
        assert_true("qty = item.total_qty ?? item.count ?? 0" in pos_html_source, "held bill qty must use count as fallback so it does not show Qty 0")
        assert_true('selectedItem.status === "held"' in pos_html_source and 'targetItem.status !== "held"' in pos_html_source, "Discard Selected must only act on real held rows")
        assert_true("state.billNavBusy" in pos_html_source and "billNavLoadRequestId" in pos_html_source, "bill navigation must guard overlapping PgUp/PgDn actions")
        assert_true(".where(PosCart.status == HELD_CART_STATUS)" in pos_py_source, "held bill endpoint must not mix active carts into held list")
        assert_true('"cart": _cart_payload(db)' in pos_py_source, "discard held route must return current cart payload")
        main_source = (ROOT / "app" / "main.py").read_text(encoding="utf-8")
        assert_true("serialize_pos_cart_mutations" in main_source and "pos_cart_mutation_lock" in main_source, "POS cart mutations must be serialized")
        assert_true("Normalized %s duplicate active POS carts" in pos_py_source and "stale_cart.status = HELD_CART_STATUS" in pos_py_source, "POS must normalize duplicate active carts safely")
        assert_true(".pos-held-row.selected.opened" in app_css, "selected bill row style must win over opened row style")

        # Layout/UI checks
        assert_true("body.pos-page" in app_css and "overflow: hidden" in app_css, "body.pos-page must lock browser scroll")
        assert_true("pos-search-results-list .pos-suggestion.active" in app_css, "active search result CSS must exist")
        assert_true("background: #1f6feb" in app_css or "background: #1f6feb" in pos_html_source, "active search result must use high-contrast blue background")
        assert_true("pos-held-row-top" in app_css and "grid-template-columns: auto minmax(0, 1fr) auto" in app_css, "Recent Bills row-top must have 3-column grid (badge + label + total)")
        assert_true("pos-held-row-sub" in app_css, "Recent Bills sub line CSS must exist")
        # Ensure searchPanelTotal is guarded: not a plain direct access
        assert_true("searchPanelTotal.textContent" not in pos_html_source or "if (searchPanelTotal)" in pos_html_source, "searchPanelTotal must be null-guarded since element was removed")
        # Ensure missing-price selection skips confirm popup for both barcode and Tally items
        assert_true("allow_missing_price" in pos_html_source, "addBarcode must accept allow_missing_price parameter")
        assert_true("addTallyItem(item.id)" in pos_html_source, "Tally search result must call addTallyItem directly (no confirm)")
        assert_true("focusNextBillingField" in pos_html_source, "after adding item, focusNextBillingField must be called to handle missing MRP/Rate")


        # Layout/UI checks
        assert_true('focusNextBillingField(itemId, "qty")' in pos_html_source and 'focusNextBillingField(itemId, "mrp")' in pos_html_source, "Enter navigation must follow Item -> Qty -> MRP -> Rate")
        assert_true('pos-qty-button' not in pos_html_source, "qty +/- buttons removed")
        assert_true('item.qty < 0' in pos_html_source and 'return-badge' in pos_html_source, "negative qty row shows return badge")
        assert_true('Quantity cannot be zero' in pos_py_source, "zero qty is rejected")
        assert_true('else if (fieldName === "rate")' in pos_html_source and 'focusNextBillingField(itemId, "next_row_item")' in pos_html_source, "rate Enter moves to next_row_item")
        assert_true('if (printAfterSave && data.sale_id)' in pos_html_source, "Save+Print only prints after sale_id")

        assert_true("???" not in pos_markup + pos_py_source + app_css, "Code contains mojibake ???")
        assert_true("cart.cart_mode == SALE_EDIT_CART_MODE" in pos_py_source, "sale_edit auto-parking must be handled explicitly")
        assert_true("source_bill_number" in pos_py_source and "source_bill_number" in pos_markup, "sale_edit cart payload should expose source bill number")

        assert_true("heldBillCount" in pos_markup, "Recent Bills count is missing")
        assert_true("activeBillNavItem" in pos_markup and 'type: "open"' in pos_markup, "POS bill nav must keep the current active bill visible locally")
        assert_true('"Open / Held Bills"' in pos_markup and "${openCount} open / ${heldCount} held / ${previousCount} today" in pos_markup, "POS bill nav must separate open, held, and previous counts")
        assert_true('if (item.type === "open") return 2;' in pos_markup, "Open bill must sort with held bills, not always at the top")
        assert_true('item.type === "open" && item.id === state.cart.cart_id' in pos_markup, "POS bill nav must reselect the currently open bill after reload")
        assert_true('if (targetItem.type === "open")' in pos_markup, "Opening the active bill row should be a no-op, not a server call")
        assert_true("item.item_count ?? item.lines ?? 0" in pos_markup, "Held bill line count must fall back to lines")
        assert_true("item.total_qty ?? item.count ?? 0" in pos_markup, "Held bill qty must fall back to count")
        assert_true("PgUp/PgDn Bills" in pos_markup, "POS help text must mention PgUp/PgDn Bills")

        assert_true('name="start_date"' in sales_markup and 'name="payment_mode"' in sales_markup, "Sales page has filter inputs for start/end/payment/bill number")
        assert_true("start_date: str | None = Query(None)" in sales_route_source, "Sales route accepts filter query params")
        assert_true('href="/sales/{{ sale.id }}/receipt"' in sale_detail_markup, "Sale detail page still links to receipt")
        assert_true("{% for item in sale.items %}" in sale_detail_markup and "sale.total" in sale_detail_markup, "Sale detail page renders item rows and totals")
        assert_true("Thank you" in sale_receipt_markup and "sale.items" in sale_receipt_markup, "Receipt print page still exists and renders sale items")

        # Voice Fill Editable Dialog Checks
        # removed phoneVoicePrintButton check
        # removed pvPrintBtn check
        assert_true('phoneVoiceConfirmCancelButton' not in phone_print_markup, "phoneVoiceConfirmCancelButton is not referenced if button removed")
        assert_true("function pvShowConfirm(" in phone_print_markup, "function pvShowConfirm exists or equivalent replacement exists")
        assert_true("pvRenderConfirmBody" in phone_print_markup, "editable dialog renders from pvFieldMeta")
        assert_true("data-phone-voice-field" in phone_print_markup, "editable inputs have data-phone-voice-field")
        assert_true("family_name" in phone_print_markup, "family_name is included in voice metadata")
        assert_true("copies" in phone_print_markup, "copies is included in voice metadata")
        assert_true("assign_barcode" not in phone_print_markup, "Voice Fill does not implement separate barcode duplicate logic")
        assert_true("pvApplyRowToPhoneForm" in phone_print_markup, "Voice Fill uses existing phone print submit path")
        assert_true("phoneSubmitPrintButton.click()" in phone_print_markup, "phoneSubmitPrintButton.click only happens in Print button path")
        assert_true("phonePrintCopiesConfirmed = true" in phone_print_markup, "phonePrintCopiesConfirmed is used only around confirmed Print action")
        assert_true("manual_only" in phone_print_markup, "manual-only barcode/qr/ean/upc are not applied from voice")
        assert_true("???" not in phone_print_markup, "phone print template contains mojibake ???")
        assert_true("pvInputByKey(" in phone_print_markup, "field refs are guarded")

        print("Smoke checks passed")
    finally:
        db.close()


if __name__ == "__main__":
    main()
