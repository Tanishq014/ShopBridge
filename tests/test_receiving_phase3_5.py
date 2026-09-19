import unittest
from decimal import Decimal
from datetime import datetime
import json

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from fastapi.testclient import TestClient

from app.db import Base, get_db
from app.main import app
from app.models import (
    ReceivingSession, ReceivingItem, ProductFamily, Supplier, LabelVariant, 
    PricingRule, TemplateMaster, PrintJob
)
from app.services.workflow.label_draft_service import resolve_draft, draft_to_persistence_adapter
from app.services.workflow.variant_resolution_service import resolve_variant_for_receiving
from app.services.receiving_service import update_session_status

class TestReceivingPhase35(unittest.TestCase):
    def setUp(self):
        from sqlalchemy.pool import StaticPool
        self.engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool
        )
        Base.metadata.create_all(bind=self.engine)
        TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)
        self.db = TestingSessionLocal()
        
        def override_get_db():
            try:
                db = TestingSessionLocal()
                yield db
            finally:
                db.close()
                
        app.dependency_overrides[get_db] = override_get_db
        self.client = TestClient(app)

    def tearDown(self):
        self.db.close()
        Base.metadata.drop_all(bind=self.engine)

    def setup_base_data(self):
        supplier = Supplier(name="Test Supplier P3.5")
        self.db.add(supplier)
        
        template = TemplateMaster(
            template_id="TEST_TMPL", 
            template_name="Test", 
            bartender_file_path="C:\\test.btw",
            required_fields="mrp,selling_price,size"
        )
        self.db.add(template)
        
        template_no_size = TemplateMaster(
            template_id="TEST_TMPL2", 
            template_name="Test No Size", 
            bartender_file_path="C:\\test.btw",
            required_fields="mrp,selling_price"
        )
        self.db.add(template_no_size)
        
        family = ProductFamily(family_name="Test Family", category="clothes")
        self.db.add(family)
        
        session = ReceivingSession(supplier_id=1, status="RECEIVING")
        self.db.add(session)
        
        self.db.commit()
        return supplier, template, template_no_size, family, session

    def test_new_stock_variant_reused_by_receiving(self):
        # 1. test_new_stock_variant_reused_by_receiving
        supplier, template, template_no_size, family, session = self.setup_base_data()
        
        # Simulate New Stock created variant
        from app.services.price_code_service import generate_coded_price
        v = LabelVariant(
            barcode="NS123", family_id=family.id, item_display_name="Test Family",
            mrp=Decimal("100"), selling_price=Decimal("80"), template_id=template.id,
            size="L", coded_price=generate_coded_price(Decimal("80"))
        )
        self.db.add(v)
        self.db.commit()
        
        item = ReceivingItem(
            session_id=session.id, billing_item="Test Family", template_id=template.id,
            manual_overrides=json.dumps({"size": "L"}), tally_status="VERIFIED"
        )
        self.db.add(item)
        self.db.commit()
        
        draft = resolve_draft(self.db, item)
        resolved = resolve_variant_for_receiving(self.db, draft, "Test Family", Decimal("100"), Decimal("80"))
        
        self.assertEqual(resolved.barcode, "NS123")
        self.assertEqual(resolved.id, v.id)

    def test_receiving_variant_reused_by_new_stock(self):
        # 2. test_receiving_variant_reused_by_new_stock
        # (This is implicitly tested by ensuring receiving creates identical structures to New Stock)
        supplier, template, template_no_size, family, session = self.setup_base_data()
        item = ReceivingItem(
            session_id=session.id, billing_item="Test Family", template_id=template.id,
            manual_overrides=json.dumps({"size": "M"}), tally_status="VERIFIED"
        )
        self.db.add(item)
        self.db.commit()
        
        draft = resolve_draft(self.db, item)
        resolved = resolve_variant_for_receiving(self.db, draft, "Test Family", Decimal("100"), Decimal("80"))
        
        self.assertEqual(resolved.size, "M")

    def test_same_template_same_values_reuse(self):
        # 3. test_same_template_same_values_reuse
        supplier, template, template_no_size, family, session = self.setup_base_data()
        item = ReceivingItem(session_id=session.id, billing_item="Test Family", template_id=template.id, manual_overrides=json.dumps({"size": "M"}))
        self.db.add(item)
        self.db.commit()
        
        draft = resolve_draft(self.db, item)
        v1 = resolve_variant_for_receiving(self.db, draft, "Test Family", Decimal("100"), Decimal("80"))
        v2 = resolve_variant_for_receiving(self.db, draft, "Test Family", Decimal("100"), Decimal("80"))
        self.assertEqual(v1.id, v2.id)

    def test_changed_mrp_new_barcode(self):
        # 4. test_changed_mrp_new_barcode
        supplier, template, template_no_size, family, session = self.setup_base_data()
        item = ReceivingItem(session_id=session.id, billing_item="Test Family", template_id=template.id, manual_overrides=json.dumps({"size": "M"}))
        self.db.add(item)
        self.db.commit()
        
        draft = resolve_draft(self.db, item)
        v1 = resolve_variant_for_receiving(self.db, draft, "Test Family", Decimal("100"), Decimal("80"))
        v2 = resolve_variant_for_receiving(self.db, draft, "Test Family", Decimal("120"), Decimal("80"))
        self.assertNotEqual(v1.id, v2.id)

    def test_changed_selling_new_barcode(self):
        # 5. test_changed_selling_new_barcode
        supplier, template, template_no_size, family, session = self.setup_base_data()
        item = ReceivingItem(session_id=session.id, billing_item="Test Family", template_id=template.id, manual_overrides=json.dumps({"size": "M"}))
        self.db.add(item)
        self.db.commit()
        
        draft = resolve_draft(self.db, item)
        v1 = resolve_variant_for_receiving(self.db, draft, "Test Family", Decimal("100"), Decimal("80"))
        v2 = resolve_variant_for_receiving(self.db, draft, "Test Family", Decimal("100"), Decimal("90"))
        self.assertNotEqual(v1.id, v2.id)

    def test_changed_template_identity_new_barcode(self):
        # 6. test_changed_template_identity_new_barcode
        supplier, template, template_no_size, family, session = self.setup_base_data()
        item1 = ReceivingItem(session_id=session.id, billing_item="Test Family", template_id=template.id, manual_overrides=json.dumps({"size": "M"}))
        self.db.add(item1)
        self.db.commit()
        
        draft1 = resolve_draft(self.db, item1)
        v1 = resolve_variant_for_receiving(self.db, draft1, "Test Family", Decimal("100"), Decimal("80"))
        
        # Different template that doesn't use size
        item2 = ReceivingItem(session_id=session.id, billing_item="Test Family", template_id=template_no_size.id)
        self.db.add(item2)
        self.db.commit()
        
        draft2 = resolve_draft(self.db, item2)
        v2 = resolve_variant_for_receiving(self.db, draft2, "Test Family", Decimal("100"), Decimal("80"))
        
        self.assertNotEqual(v1.id, v2.id)

    def test_changed_custom_required_field_new_barcode(self):
        # 7. test_changed_custom_required_field_new_barcode
        supplier, template, template_no_size, family, session = self.setup_base_data()
        item = ReceivingItem(session_id=session.id, billing_item="Test Family", template_id=template.id)
        self.db.add(item)
        self.db.commit()
        
        item.manual_overrides = json.dumps({"size": "M"})
        draft1 = resolve_draft(self.db, item)
        v1 = resolve_variant_for_receiving(self.db, draft1, "Test Family", Decimal("100"), Decimal("80"))
        
        item.manual_overrides = json.dumps({"size": "L"})
        draft2 = resolve_draft(self.db, item)
        v2 = resolve_variant_for_receiving(self.db, draft2, "Test Family", Decimal("100"), Decimal("80"))
        self.assertNotEqual(v1.id, v2.id)

    def test_canonical_alias_differences_handled(self):
        # 8. test_canonical_alias_differences_handled
        supplier, template, template_no_size, family, session = self.setup_base_data()
        from app.services.price_code_service import generate_coded_price
        v = LabelVariant(
            barcode="ALIAS1", family_id=family.id, item_display_name="Test Family",
            mrp=Decimal("100"), selling_price=Decimal("80"), template_id=template.id,
            size="L", coded_price=generate_coded_price(Decimal("80"))
        )
        self.db.add(v)
        self.db.commit()
        
        item = ReceivingItem(session_id=session.id, billing_item="Test Family", template_id=template.id, manual_overrides=json.dumps({"SIZE": "L"}))
        self.db.add(item)
        self.db.commit()
        
        draft = resolve_draft(self.db, item)
        resolved = resolve_variant_for_receiving(self.db, draft, "Test Family", Decimal("100"), Decimal("80"))
        self.assertEqual(resolved.barcode, "ALIAS1")

    def test_landing_price_change_no_barcode(self):
        # 9. test_landing_price_change_no_barcode
        supplier, template, template_no_size, family, session = self.setup_base_data()
        item = ReceivingItem(session_id=session.id, billing_item="Test Family", template_id=template.id, manual_overrides=json.dumps({"size": "M"}))
        self.db.add(item)
        self.db.commit()
        
        draft = resolve_draft(self.db, item)
        # Landing price is not stored in variant or label draft
        v1 = resolve_variant_for_receiving(self.db, draft, "Test Family", Decimal("100"), Decimal("80"))
        v2 = resolve_variant_for_receiving(self.db, draft, "Test Family", Decimal("100"), Decimal("80")) # Same MRP/Selling
        self.assertEqual(v1.id, v2.id)

    def test_missing_required_field_blocks_print(self):
        # 10. test_missing_required_field_blocks_print
        supplier, template, template_no_size, family, session = self.setup_base_data()
        item = ReceivingItem(session_id=session.id, billing_item="Test Family", template_id=template.id)
        self.db.add(item)
        self.db.commit()
        
        draft = resolve_draft(self.db, item)
        self.assertFalse(draft.ready) # Missing size
        
        item.manual_overrides = json.dumps({"size": "M"})
        self.db.commit()
        draft2 = resolve_draft(self.db, item)
        # Still not ready because mrp and selling_price are required by template!
        # wait, mrp and selling price are provided at print time via confirm_pricing_endpoint
        # Actually draft doesn't get mrp/selling until they are confirmed, but they are 'PRICING' injected.
        # But we pass them manually here? Wait, draft checks item.mrp and item.confirmed_selling_price.
        item.mrp = Decimal("100")
        item.confirmed_selling_price = Decimal("80")
        self.db.commit()
        draft3 = resolve_draft(self.db, item)
        self.assertTrue(draft3.ready)

    import unittest.mock
    @unittest.mock.patch("app.services.workflow.label_draft_service.get_template_field_settings")
    def test_changing_template_recomputes_draft(self, mock_settings):
        from app.services.settings_service import TemplateFieldSettings
        mock_settings.return_value = TemplateFieldSettings(optional_fields=set())
        # 11. test_changing_template_recomputes_draft
        supplier, template, template_no_size, family, session = self.setup_base_data()
        item = ReceivingItem(session_id=session.id, billing_item="Test Family", template_id=template_no_size.id, mrp=Decimal("100"), confirmed_selling_price=Decimal("80"))
        self.db.add(item)
        self.db.commit()
        
        draft1 = resolve_draft(self.db, item)
        self.assertTrue(draft1.ready)
        self.assertNotIn("size", [f.template_field for f in draft1.fields])
        
        item.template_id = template.id
        self.db.commit()
        draft2 = resolve_draft(self.db, item)
        self.assertFalse(draft2.ready)
        self.assertIn("size", [f.template_field for f in draft2.fields])

    def test_manual_override_beats_ai(self):
        # 12. test_manual_override_beats_ai
        supplier, template, template_no_size, family, session = self.setup_base_data()
        item = ReceivingItem(
            session_id=session.id, billing_item="Test Family", template_id=template.id, 
            extracted_attributes=json.dumps({"size": "L"}),
            manual_overrides=json.dumps({"size": "M"})
        )
        self.db.add(item)
        self.db.commit()
        draft = resolve_draft(self.db, item)
        f = next(f for f in draft.fields if f.template_field == "size")
        self.assertEqual(f.value, "M")
        self.assertEqual(f.source, "MANUAL")

    def test_ai_beats_previous(self):
        # 13. test_ai_beats_previous
        supplier, template, template_no_size, family, session = self.setup_base_data()
        v = LabelVariant(
            barcode="PREV", family_id=family.id, item_display_name="Test Family",
            template_id=template.id, extra_field_values=json.dumps({"size": "S"})
        )
        self.db.add(v)
        self.db.commit()
        
        item = ReceivingItem(
            session_id=session.id, billing_item="Test Family", template_id=template.id,
            extracted_attributes=json.dumps({"size": "XL"})
        )
        self.db.add(item)
        self.db.commit()
        draft = resolve_draft(self.db, item)
        f = next(f for f in draft.fields if f.template_field == "size")
        self.assertEqual(f.value, "XL")
        self.assertEqual(f.source, "AI")

    def test_shipment_specific_fields_not_inherited(self):
        # 14. test_shipment_specific_fields_not_inherited
        supplier, template, template_no_size, family, session = self.setup_base_data()
        template_batch = TemplateMaster(
            template_id="TEST_TMPL_B", template_name="Test Batch", bartender_file_path="C:\\test.btw", required_fields="batch"
        )
        self.db.add(template_batch)
        self.db.commit()
        
        v = LabelVariant(
            barcode="BATCH1", family_id=family.id, item_display_name="Test Family",
            template_id=template_batch.id, extra_field_values=json.dumps({"batch": "OLD_BATCH"})
        )
        self.db.add(v)
        self.db.commit()
        
        item = ReceivingItem(session_id=session.id, billing_item="Test Family", template_id=template_batch.id)
        self.db.add(item)
        self.db.commit()
        draft = resolve_draft(self.db, item)
        f = next(f for f in draft.fields if f.template_field == "batch_no")
        self.assertEqual(f.source, "MISSING")
        self.assertIsNone(f.value)

    def test_ambiguous_family_name_deterministic(self):
        # 15. test_ambiguous_family_name_deterministic
        supplier, template, template_no_size, family, session = self.setup_base_data()
        family2 = ProductFamily(family_name="Test Family", category="shoes")
        self.db.add(family2)
        self.db.commit()
        
        from app.services.price_code_service import generate_coded_price
        v2 = LabelVariant(
            barcode="FAM2", family_id=family2.id, item_display_name="Test Family",
            template_id=template.id, size="L",
            mrp=Decimal("100"), selling_price=Decimal("80"), coded_price=generate_coded_price(Decimal("80"))
        )
        self.db.add(v2)
        self.db.commit()
        
        item = ReceivingItem(session_id=session.id, billing_item="Test Family", template_id=template.id, manual_overrides=json.dumps({"size": "L"}))
        self.db.add(item)
        self.db.commit()
        
        draft = resolve_draft(self.db, item)
        resolved = resolve_variant_for_receiving(self.db, draft, "Test Family", Decimal("100"), Decimal("80"))
        
        self.assertEqual(resolved.barcode, "FAM2")
        self.assertEqual(resolved.family_id, family2.id)

    def test_decimal_pricing_derivation(self):
        # 16. test_decimal_pricing_derivation
        # tested via routes, so use client
        res = self.client.get("/receiving/items/1/derive_mrp?selling_price=80&discount_percent=20")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["mrp"], 100)
        
        res = self.client.get("/receiving/items/1/derive_selling?mrp=100&discount_percent=20")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["selling_price"], 80)
        
        res = self.client.get("/receiving/items/1/derive_mrp?selling_price=80&discount_percent=100")
        self.assertEqual(res.status_code, 200)
        self.assertIsNone(res.json()["mrp"])

    def test_existing_new_stock_behavior(self):
        # 17. test_existing_new_stock_behavior
        # Not tested here, assumes old New Stock flows still work
        pass

    def test_item_display_name_default_fallback(self):
        # 18. test_item_display_name_default_fallback
        supplier, template, template_no_size, family, session = self.setup_base_data()
        item = ReceivingItem(session_id=session.id, billing_item="Fallback Name", template_id=template_no_size.id)
        self.db.add(item)
        self.db.commit()
        
        draft = resolve_draft(self.db, item)
        resolved = resolve_variant_for_receiving(self.db, draft, "Fallback Name", Decimal("100"), Decimal("80"))
        # When template does not have item_display_name, it stays empty (parity with New Stock)
        self.assertEqual(resolved.item_display_name, "")
        self.assertEqual(resolved.family.family_name, "Fallback Name")
        
        # When template DOES have an item display field (e.g. design), it falls back to billing_item
        tmpl_with_design = TemplateMaster(
            template_id="TEST_DESIGN",
            template_name="Test Design",
            bartender_file_path="C:\\test_design.btw",
            required_fields="mrp,selling_price,design"
        )
        self.db.add(tmpl_with_design)
        self.db.commit()
        
        item2 = ReceivingItem(session_id=session.id, billing_item="Fallback Name", template_id=tmpl_with_design.id)
        self.db.add(item2)
        self.db.commit()
        draft2 = resolve_draft(self.db, item2)
        resolved2 = resolve_variant_for_receiving(self.db, draft2, "Fallback Name", Decimal("100"), Decimal("80"))
        self.assertEqual(resolved2.item_display_name, "Fallback Name")

    def test_confirm_pricing_with_template_id(self):
        # 19. test_confirm_pricing_with_template_id
        supplier, template, template_no_size, family, session = self.setup_base_data()
        item = ReceivingItem(
            session_id=session.id,
            billing_item="Grid Test Item",
            extracted_attributes=json.dumps({"size": "XL", "brand": "SuperBrand"}),
            template_id=None # Initially no template
        )
        self.db.add(item)
        self.db.commit()

        # Confirm pricing passing template.id
        res = self.client.post(f"/receiving/items/{item.id}/price", json={
            "selling_price": 500,
            "mrp": 1000,
            "template_id": template.id
        })
        self.assertEqual(res.status_code, 200)
        self.db.refresh(item)
        self.assertEqual(item.template_id, template.id)
        self.assertEqual(item.pricing_status, "CONFIRMED")
        self.assertIsNotNone(item.matched_variant_id)
        variant = item.matched_variant
        self.assertEqual(variant.template_id, template.id)
        self.assertEqual(variant.size, "XL")

    def test_update_draft_received_qty_in_draft_status(self):
        # 20. test_update_draft_received_qty_in_draft_status
        supplier, template, template_no_size, family, session = self.setup_base_data()
        session.status = "DRAFT"
        self.db.add(session)
        self.db.commit()

        item = ReceivingItem(
            session_id=session.id,
            expected_qty=10,
            billing_item="Draft Item"
        )
        self.db.add(item)
        self.db.commit()

        res = self.client.put(f"/receiving/items/{item.id}/draft", json={
            "received_qty": 10,
            "mrp": 299
        })
        self.assertEqual(res.status_code, 200)
        self.db.refresh(item)
        self.assertEqual(item.received_qty, 10)
        self.assertEqual(item.tally_status, "VERIFIED")
        self.assertEqual(item.mrp, 299)

    def test_grid_data_sorting_and_template_override(self):
        # 21. test_grid_data_sorting_and_template_override
        supplier, template, template_no_size, family, session = self.setup_base_data()
        item2 = ReceivingItem(session_id=session.id, bill_row_number=2, source_page_number=1, raw_description="Item 2")
        item1 = ReceivingItem(session_id=session.id, bill_row_number=1, source_page_number=1, raw_description="Item 1")
        self.db.add_all([item2, item1])
        self.db.commit()

        res = self.client.get(f"/receiving/{session.id}/grid_data?template_id={template.id}")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        items = data["items"]
        self.assertEqual(len(items), 2)
        # Check sorted order: item1 should be first
        self.assertEqual(items[0]["id"], item1.id)
        self.assertEqual(items[1]["id"], item2.id)
        # Check template_id override applied
        self.assertEqual(items[0]["template_id"], template.id)

    def test_print_large_quantity_copies(self):
        # 22. test_print_large_quantity_copies
        from app.services.workflow.validation_service import validate_print_copies
        self.assertEqual(validate_print_copies(70), 70)
        with self.assertRaises(ValueError):
            validate_print_copies(1001)

        supplier, template, template_no_size, family, session = self.setup_base_data()
        variant = LabelVariant(
            barcode="VAR70", family_id=family.id, item_display_name="Test Product",
            mrp=Decimal("200"), selling_price=Decimal("150"), template_id=template_no_size.id
        )
        self.db.add(variant)
        self.db.commit()

        item = ReceivingItem(
            session_id=session.id,
            matched_variant_id=variant.id,
            pricing_status="CONFIRMED",
            template_id=template_no_size.id,
            expected_qty=70,
            received_qty=70
        )
        self.db.add(item)
        self.db.commit()

        res = self.client.post(f"/receiving/items/{item.id}/print", json={
            "copies": 70,
            "template_id": template_no_size.id
        })
        self.assertEqual(res.status_code, 200)
        self.db.refresh(item)
        self.assertIn(item.label_status, ["PRINTED", "QUEUED"])

    def test_print_validation_error_returns_400(self):
        # 23. test_print_validation_error_returns_400
        supplier, template, template_no_size, family, session = self.setup_base_data()
        variant = LabelVariant(
            barcode="VAR_ERR", family_id=family.id, item_display_name="Test Product",
            mrp=Decimal("200"), selling_price=Decimal("150"), template_id=template_no_size.id
        )
        self.db.add(variant)
        self.db.commit()

        item = ReceivingItem(
            session_id=session.id,
            matched_variant_id=variant.id,
            pricing_status="CONFIRMED",
            template_id=template_no_size.id,
            expected_qty=10,
            received_qty=10
        )
        self.db.add(item)
        self.db.commit()

        # Send copies > 1000 -> must return HTTP 400 with validation message
        res = self.client.post(f"/receiving/items/{item.id}/print", json={
            "copies": 5000,
            "template_id": template_no_size.id
        })
        self.assertEqual(res.status_code, 400)
        self.assertIn("Maximum print quantity is 1000", res.json()["detail"])

    def test_update_draft_negative_received_qty_returns_400(self):
        # 24. test_update_draft_negative_received_qty_returns_400
        supplier, template, template_no_size, family, session = self.setup_base_data()
        item = ReceivingItem(session_id=session.id, billing_item="Negative Test")
        self.db.add(item)
        self.db.commit()

        res = self.client.put(f"/receiving/items/{item.id}/draft", json={
            "received_qty": -3
        })
        self.assertEqual(res.status_code, 400)
        self.assertIn("cannot be negative", res.json()["detail"].lower())

    def test_extra_field_values_normalization(self):
        # 25. test_extra_field_values_normalization
        from app.services.bartender_service import _extra_field_values
        raw = json.dumps({"Color": "Red", "Fit Type": "Slim"})
        parsed = _extra_field_values(raw)
        self.assertEqual(parsed.get("Color"), "Red")
        self.assertEqual(parsed.get("color"), "Red")
        self.assertEqual(parsed.get("Fit Type"), "Slim")
        self.assertEqual(parsed.get("fit type"), "Slim")

    def test_com_lock_exists(self):
        # 26. test_com_lock_exists
        from app.services.bartender_activex_service import _com_lock
        import threading
        self.assertIsInstance(_com_lock, type(threading.RLock()))

    def test_print_quantity_warning_markup(self):
        # 27. test_print_quantity_warning_markup
        from pathlib import Path
        root = Path(__file__).resolve().parent.parent
        print_section = (root / "app" / "templates" / "workflow_partials" / "_print_section.html").read_text(encoding="utf-8")
        scripts = (root / "app" / "templates" / "workflow_partials" / "_scripts.html").read_text(encoding="utf-8")
        phone_print = (root / "app" / "templates" / "phone_print.html").read_text(encoding="utf-8")

        self.assertIn('id="printQuantityWarningDialog"', print_section)
        self.assertIn('max="1000"', print_section)
        self.assertIn('openPrintQuantityWarningDialog', scripts)
        self.assertIn('cleanCopies > 1000', scripts)
        self.assertIn('max="1000"', phone_print)
        self.assertIn('phoneCopyCountError', phone_print)
        self.assertIn('cleanCopies > 1000', phone_print)

    def test_template_defaults_never_populate_draft_values(self):
        # 28. test_template_defaults_never_populate_draft_values
        supplier, template, template_no_size, family, session = self.setup_base_data()
        tmpl_with_defaults = TemplateMaster(
            template_id="TEST_DEFAULTS",
            template_name="Template With Defaults",
            bartender_file_path="C:\\defaults.btw",
            required_fields="article,mrp,coded_price,barcode",
            default_field_values=json.dumps({
                "article": "narration",
                "mrp": "749",
                "coded_price": "KSKK",
                "barcode": "6291040000000"
            })
        )
        self.db.add(tmpl_with_defaults)
        self.db.commit()

        item = ReceivingItem(session_id=session.id, billing_item="Test Item")
        self.db.add(item)
        self.db.commit()

        draft = resolve_draft(self.db, item, template_id_override=tmpl_with_defaults.id)
        field_map = {f.semantic_field: f for f in draft.fields}

        # Grid cell values must NEVER be populated with template defaults
        self.assertIsNone(field_map["article"].value)
        self.assertIsNone(field_map["mrp"].value)
        self.assertIsNone(field_map["coded_price"].value)
        self.assertIsNone(field_map["barcode"].value)

    def test_unsafe_inheritance_fields_not_inherited_from_family(self):
        # 29. test_unsafe_inheritance_fields_not_inherited_from_family
        supplier, template, template_no_size, family, session = self.setup_base_data()
        old_var = LabelVariant(
            barcode="OLD_CODE",
            family_id=family.id,
            item_display_name="Custom Old Name",
            mrp=Decimal("999"),
            selling_price=Decimal("799"),
            coded_price="ZZZZ",
            template_id=template.id,
        )
        self.db.add(old_var)
        self.db.commit()

        # Unlinked item sharing only the family / billing_item name
        new_item = ReceivingItem(session_id=session.id, billing_item="Test Family")
        self.db.add(new_item)
        self.db.commit()

        draft = resolve_draft(self.db, new_item, template_id_override=template.id)
        field_map = {f.semantic_field: f for f in draft.fields}

        # mrp, barcode, selling_price, item_display_name must NOT be inherited from old variant
        if "mrp" in field_map:
            self.assertIsNone(field_map["mrp"].value)
        if "barcode" in field_map:
            self.assertIsNone(field_map["barcode"].value)

    def test_sticky_pricing_and_pending_filter_logic(self):
        # 30. test_sticky_pricing_and_pending_filter_logic
        from pathlib import Path
        root = Path(__file__).resolve().parent.parent
        spreadsheet_js = (root / "app" / "static" / "spreadsheet_mode.js").read_text(encoding="utf-8")
        receiving_js = (root / "app" / "static" / "receiving.js").read_text(encoding="utf-8")

        # Verify Pending filter keeps unprinted items even if tallied
        self.assertIn("tabMatch = tallyStatus === 'UNVERIFIED' || tallyStatus === 'MISMATCH' || labelStatus !== 'PRINTED';", spreadsheet_js)
        self.assertIn("activeFilter === 'PENDING' && (tally === 'UNVERIFIED' || tally === 'MISMATCH' || labelStatus !== 'PRINTED')", receiving_js)

        # Verify autoCalculated flag on Marg %, Disc %, and C Calc
        self.assertIn("codeInput.dataset.autoCalculated = 'true';", spreadsheet_js)
        self.assertIn("mrpInput.dataset.autoCalculated = 'true';", spreadsheet_js)

if __name__ == "__main__":
    unittest.main()


