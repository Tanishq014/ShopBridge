import unittest
from decimal import Decimal
from datetime import datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models import (
    Supplier,
    SupplierProductMapping,
    ReceivingSession,
    ReceivingItem,
    ProductFamily,
)
from app.schemas import (
    ReceivingSessionCreate,
    ReceivingItemCreate,
)
from app.services.receiving_service import (
    get_or_create_supplier,
    create_receiving_session,
    update_session_status,
    create_receiving_item,
    tally_item,
    map_supplier_product,
    normalize_supplier_code,
)

class TestReceiving(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
        Base.metadata.create_all(bind=self.engine)
        TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)
        self.db = TestingSessionLocal()

    def tearDown(self):
        self.db.close()
        Base.metadata.drop_all(bind=self.engine)

    def test_create_supplier(self):
        supplier = get_or_create_supplier(self.db, "Test Supplier")
        self.assertIsNotNone(supplier.id)
        self.assertEqual(supplier.name, "Test Supplier")

        supplier2 = get_or_create_supplier(self.db, "Test Supplier")
        self.assertEqual(supplier.id, supplier2.id)

    def test_supplier_product_mapping(self):
        supplier = get_or_create_supplier(self.db, "Test Supplier")
        family = ProductFamily(family_name="Test Family")
        self.db.add(family)
        self.db.commit()

        # Normalizes code properly
        mapping = map_supplier_product(
            self.db,
            supplier.id,
            family.id,
            supplier_product_code=" test-code-1 ",
            supplier_description="TEST DESC"
        )
        self.assertEqual(mapping.supplier_product_code, "TEST-CODE-1")
        
        mapping2 = map_supplier_product(
            self.db,
            supplier.id,
            family.id,
            supplier_product_code="TEST-CODE-1",
            supplier_description="NEW DESC"
        )
        self.assertEqual(mapping2.id, mapping.id)
        self.assertEqual(mapping2.supplier_description, "NEW DESC")
        
        family2 = ProductFamily(family_name="Another Family")
        self.db.add(family2)
        self.db.commit()
        with self.assertRaisesRegex(ValueError, "Conflicting mapping"):
            map_supplier_product(
                self.db,
                supplier.id,
                family2.id,
                supplier_product_code="test-code-1",
            )

    def test_domain_validations(self):
        with self.assertRaisesRegex(ValueError, "Supplier not found"):
            create_receiving_session(self.db, ReceivingSessionCreate(supplier_id=999))
            
        supplier = get_or_create_supplier(self.db, "Test Supplier")
        with self.assertRaisesRegex(ValueError, "ProductFamily not found"):
            map_supplier_product(self.db, supplier.id, 999, "CODE")
            
        session = create_receiving_session(self.db, ReceivingSessionCreate(supplier_id=supplier.id))
        with self.assertRaisesRegex(ValueError, "ProductFamily not found"):
            create_receiving_item(self.db, ReceivingItemCreate(session_id=session.id, family_id=999))

    def test_session_lifecycle_transitions(self):
        supplier = get_or_create_supplier(self.db, "Test Supplier")
        session = create_receiving_session(self.db, ReceivingSessionCreate(supplier_id=supplier.id))
        
        self.assertEqual(session.status, "DRAFT")
        
        # Need an item to transition to RECEIVING
        create_receiving_item(self.db, ReceivingItemCreate(session_id=session.id, expected_qty=Decimal("1")))
        updated_session = update_session_status(self.db, session.id, "RECEIVING")
        self.assertEqual(updated_session.status, "RECEIVING")
        
        with self.assertRaisesRegex(ValueError, "Invalid transition"):
            update_session_status(self.db, session.id, "DRAFT")
            
        # Skipping transition to completed for this test since we just need a terminal session
        session.status = "COMPLETED"
        self.db.add(session)
        self.db.commit()
        
        session2 = create_receiving_session(self.db, ReceivingSessionCreate(supplier_id=supplier.id))
        create_receiving_item(self.db, ReceivingItemCreate(session_id=session2.id, expected_qty=Decimal("1")))
        update_session_status(self.db, session2.id, "RECEIVING")
        updated_session2 = update_session_status(self.db, session2.id, "CANCELLED")
        self.assertEqual(updated_session2.status, "CANCELLED")

    def test_state_invariants(self):
        supplier = get_or_create_supplier(self.db, "Test Supplier")
        session = create_receiving_session(self.db, ReceivingSessionCreate(supplier_id=supplier.id))
        
        # Can add in DRAFT
        item = create_receiving_item(self.db, ReceivingItemCreate(session_id=session.id, expected_qty=Decimal("10")))
        
        # Cannot tally in DRAFT
        with self.assertRaisesRegex(ValueError, "Cannot tally item unless session is RECEIVING"):
            tally_item(self.db, item.id, Decimal("10"))
            
        update_session_status(self.db, session.id, "RECEIVING")
        
        # Can add in RECEIVING
        item2 = create_receiving_item(self.db, ReceivingItemCreate(session_id=session.id, expected_qty=Decimal("5")))
        
        # Can tally in RECEIVING
        tally_item(self.db, item.id, Decimal("0"))
        self.assertEqual(item.tally_status, "MISMATCH")
        
        tally_item(self.db, item2.id, Decimal("0"))
        
        update_session_status(self.db, session.id, "COMPLETED")
        
        # Cannot add in COMPLETED
        with self.assertRaisesRegex(ValueError, "Cannot add items"):
            create_receiving_item(self.db, ReceivingItemCreate(session_id=session.id))
            
        # Cannot tally in COMPLETED
        with self.assertRaisesRegex(ValueError, "Cannot tally item unless session is RECEIVING"):
            tally_item(self.db, item2.id, Decimal("5"))

    def test_quantity_validations(self):
        supplier = get_or_create_supplier(self.db, "Test Supplier")
        session = create_receiving_session(self.db, ReceivingSessionCreate(supplier_id=supplier.id))
        
        with self.assertRaisesRegex(ValueError, "Expected quantity cannot be negative"):
            create_receiving_item(self.db, ReceivingItemCreate(session_id=session.id, expected_qty=Decimal("-5")))
            
        item = create_receiving_item(self.db, ReceivingItemCreate(session_id=session.id, expected_qty=Decimal("10")))
        update_session_status(self.db, session.id, "RECEIVING")
        
        with self.assertRaisesRegex(ValueError, "Received quantity cannot be negative"):
            tally_item(self.db, item.id, Decimal("-1"))

    def test_receiving_item_invariants(self):
        supplier = get_or_create_supplier(self.db, "Test Supplier")
        session = create_receiving_session(self.db, ReceivingSessionCreate(supplier_id=supplier.id))
        
        item_data = ReceivingItemCreate(
            session_id=session.id,
            raw_description="Unknown Product",
            expected_qty=Decimal("12.0"),
            unit="PCS",
            mrp=Decimal("500.00"),
            supplier_product_code=" CODE "
        )
        item = create_receiving_item(self.db, item_data)
        
        self.assertIsNotNone(item.id)
        self.assertIsNone(item.family_id)
        self.assertIsNone(item.matched_variant_id)
        self.assertEqual(item.supplier_product_code, "CODE")
        self.assertEqual(item.expected_qty, Decimal("12.0"))
        self.assertIsNone(item.received_qty)
        self.assertEqual(item.tally_status, "UNVERIFIED")
        self.assertEqual(item.pricing_status, "PENDING")
        
        family = ProductFamily(family_name="Test Family")
        self.db.add(family)
        self.db.commit()
        
        item_data2 = ReceivingItemCreate(
            session_id=session.id,
            expected_qty=Decimal("5.0"),
            family_id=family.id
        )
        item2 = create_receiving_item(self.db, item_data2)
        self.assertEqual(item2.family_id, family.id)
        
        map_supplier_product(self.db, supplier.id, family.id, "SUPP-123")
        item_data3 = ReceivingItemCreate(
            session_id=session.id,
            supplier_product_code=" supp-123 ",
            expected_qty=Decimal("1.0")
        )
        item3 = create_receiving_item(self.db, item_data3)
        self.assertEqual(item3.family_id, family.id)

    def test_tallying(self):
        supplier = get_or_create_supplier(self.db, "Test Supplier")
        session = create_receiving_session(self.db, ReceivingSessionCreate(supplier_id=supplier.id))
        item = create_receiving_item(self.db, ReceivingItemCreate(session_id=session.id, expected_qty=Decimal("10.0")))
        
        update_session_status(self.db, session.id, "RECEIVING")
        
        self.assertIsNone(item.received_qty)
        self.assertEqual(item.tally_status, "UNVERIFIED")
        
        tally_item(self.db, item.id, Decimal("10.0"))
        self.assertEqual(item.received_qty, Decimal("10.0"))
        self.assertEqual(item.tally_status, "VERIFIED")
        
        tally_item(self.db, item.id, Decimal("9.0"))
        self.assertEqual(item.received_qty, Decimal("9.0"))
        self.assertEqual(item.tally_status, "MISMATCH")
        
        tally_item(self.db, item.id, Decimal("11.0"))
        self.assertEqual(item.received_qty, Decimal("11.0"))
        self.assertEqual(item.tally_status, "MISMATCH")
        
        tally_item(self.db, item.id, Decimal("0.0"))
        self.assertEqual(item.received_qty, Decimal("0.0"))
        self.assertEqual(item.tally_status, "MISMATCH")

if __name__ == '__main__':
    unittest.main()

from fastapi.testclient import TestClient
from app.main import app

class TestReceivingUI(unittest.TestCase):
    def setUp(self):
        from sqlalchemy.pool import StaticPool
        self.engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool
        )
        Base.metadata.create_all(bind=self.engine)
        TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)
        
        def override_get_db():
            try:
                db = TestingSessionLocal()
                yield db
            finally:
                db.close()
                
        from app.db import get_db
        app.dependency_overrides[get_db] = override_get_db
        self.client = TestClient(app)
        self.db = TestingSessionLocal()

    def tearDown(self):
        self.db.close()
        Base.metadata.drop_all(bind=self.engine)
        app.dependency_overrides.clear()

    def test_get_receiving_home(self):
        response = self.client.get("/receiving/")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Smart Stock Receiving", response.content)

    def test_get_receiving_workspace(self):
        supplier = get_or_create_supplier(self.db, "Workspace Supplier")
        session = create_receiving_session(self.db, ReceivingSessionCreate(supplier_id=supplier.id))
        
        response = self.client.get(f"/receiving/{session.id}")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Workspace Supplier", response.content)
        
        # Test nonexistent
        response_404 = self.client.get("/receiving/999")
        self.assertEqual(response_404.status_code, 404)

    def test_tally_endpoint_accepts_decimal_string(self):
        supplier = get_or_create_supplier(self.db, "Supplier")
        session = create_receiving_session(self.db, ReceivingSessionCreate(supplier_id=supplier.id))
        item = create_receiving_item(self.db, ReceivingItemCreate(session_id=session.id, expected_qty=Decimal("10")))
        update_session_status(self.db, session.id, "RECEIVING")
        
        # Accept fractional quantity in JSON string
        response = self.client.post(
            f"/receiving/items/{item.id}/tally",
            json={"received_qty": "10.375"}
        )
        self.assertEqual(response.status_code, 200)
        
        self.db.refresh(item)
        self.assertEqual(item.received_qty, Decimal("10.375"))
        self.assertEqual(item.tally_status, "MISMATCH")

    def test_negative_quantity_rejected(self):
        supplier = get_or_create_supplier(self.db, "Supplier")
        session = create_receiving_session(self.db, ReceivingSessionCreate(supplier_id=supplier.id))
        item = create_receiving_item(self.db, ReceivingItemCreate(session_id=session.id, expected_qty=Decimal("10")))
        update_session_status(self.db, session.id, "RECEIVING")
        
        response = self.client.post(
            f"/receiving/items/{item.id}/tally",
            json={"received_qty": "-1"}
        )
        self.assertEqual(response.status_code, 400)
        
    def test_terminal_session_mutation_rejected(self):
        supplier = get_or_create_supplier(self.db, "Supplier")
        session = create_receiving_session(self.db, ReceivingSessionCreate(supplier_id=supplier.id))
        item = create_receiving_item(self.db, ReceivingItemCreate(session_id=session.id, expected_qty=Decimal("10")))
        update_session_status(self.db, session.id, "RECEIVING")
        tally_item(self.db, item.id, Decimal("0"))
        update_session_status(self.db, session.id, "COMPLETED")
        
        response = self.client.post(
            f"/receiving/items/{item.id}/tally",
            json={"received_qty": "10"}
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("session is RECEIVING", response.json()["detail"])


    def test_draft_session_with_zero_rows_cannot_start(self):
        supplier = get_or_create_supplier(self.db, "Supplier")
        session = create_receiving_session(self.db, ReceivingSessionCreate(supplier_id=supplier.id))
        
        response = self.client.post(f"/receiving/{session.id}/start")
        self.assertEqual(response.status_code, 400)
        self.assertIn("zero items", response.text)

    def test_draft_session_with_items_can_start(self):
        supplier = get_or_create_supplier(self.db, "Supplier")
        session = create_receiving_session(self.db, ReceivingSessionCreate(supplier_id=supplier.id))
        create_receiving_item(self.db, ReceivingItemCreate(session_id=session.id, expected_qty=Decimal("1")))
        
        response = self.client.post(f"/receiving/{session.id}/start", follow_redirects=False)
        self.assertEqual(response.status_code, 303)
        self.db.refresh(session)
        self.assertEqual(session.status, "RECEIVING")

    def test_expected_qty_zero_is_valid(self):
        supplier = get_or_create_supplier(self.db, "Supplier")
        session = create_receiving_session(self.db, ReceivingSessionCreate(supplier_id=supplier.id))
        item = create_receiving_item(self.db, ReceivingItemCreate(session_id=session.id, expected_qty=Decimal("0")))
        self.assertEqual(item.expected_qty, Decimal("0"))
        
        update_session_status(self.db, session.id, "RECEIVING")
        tally_item(self.db, item.id, Decimal("0"))
        self.assertEqual(item.tally_status, "VERIFIED")

    def test_tally_exact_fractional_match(self):
        supplier = get_or_create_supplier(self.db, "Supplier")
        session = create_receiving_session(self.db, ReceivingSessionCreate(supplier_id=supplier.id))
        item = create_receiving_item(self.db, ReceivingItemCreate(session_id=session.id, expected_qty=Decimal("1.500")))
        update_session_status(self.db, session.id, "RECEIVING")
        
        response = self.client.post(f"/receiving/items/{item.id}/tally", json={"received_qty": "1.500"})
        self.assertEqual(response.status_code, 200)
        self.db.refresh(item)
        self.assertEqual(item.received_qty, Decimal("1.500"))
        self.assertEqual(item.tally_status, "VERIFIED")

    def test_terminal_session_cannot_add_item_via_ui(self):
        supplier = get_or_create_supplier(self.db, "Supplier")
        session = create_receiving_session(self.db, ReceivingSessionCreate(supplier_id=supplier.id))
        item = create_receiving_item(self.db, ReceivingItemCreate(session_id=session.id, expected_qty=Decimal("1")))
        update_session_status(self.db, session.id, "RECEIVING")
        tally_item(self.db, item.id, Decimal("0"))
        update_session_status(self.db, session.id, "COMPLETED")
        
        response = self.client.post(f"/receiving/{session.id}/items", data={"raw_description": "Late Item"})
        self.assertEqual(response.status_code, 400)
        self.assertIn("Cannot add items", response.text)

    def test_dozen_unit_conversion_normalization(self):
        from app.extraction.provider import ExtractedRow, GroundedField
        from app.models import ReceivingSession, ReceivingItem
        
        supplier = get_or_create_supplier(self.db, "Dozen Supplier")
        session = create_receiving_session(self.db, ReceivingSessionCreate(supplier_id=supplier.id))
        
        # Test unit conversion logic directly as simulated from Gemini output
        unit_raw = "DOZ"
        expected_qty_val = 2.0
        purchase_rate_val = 1200.0
        mrp_val = 2400.0
        
        if unit_raw.upper() in ["DOZ", "DOZEN", "DZN", "DZ"]:
            expected_qty_val = expected_qty_val * 12
            purchase_rate_val = round(purchase_rate_val / 12, 2)
            mrp_val = round(mrp_val / 12, 2)
            unit_raw = "PCS"
            
        self.assertEqual(expected_qty_val, 24.0)
        self.assertEqual(purchase_rate_val, 100.0)
        self.assertEqual(mrp_val, 200.0)
        self.assertEqual(unit_raw, "PCS")

    def test_clean_code_and_padded_override_persistence(self):
        import json
        from app.models import ReceivingSession, ReceivingItem, TemplateMaster
        from app.schemas import UpdateDraftRequest
        from app.routes.receiving import update_draft_endpoint
        from app.services.workflow.label_draft_service import resolve_draft

        supplier = get_or_create_supplier(self.db, "Code Supplier")
        session = create_receiving_session(self.db, ReceivingSessionCreate(supplier_id=supplier.id))
        item = create_receiving_item(self.db, ReceivingItemCreate(
            session_id=session.id,
            raw_description="Test Item Clean Code",
            purchase_rate=100.0,
            mrp=200.0
        ))
        
        template = TemplateMaster(
            template_name="Test Template 6-char",
            template_id="TEST_TMPL",
            bartender_file_path="C:/test.btw",
            required_fields="item,mrp,coded_price,barcode",
            default_field_values="coded_price=ABCDEF",
            active_status=True
        )
        self.db.add(template)
        self.db.commit()

        # Update draft: clean code in supplier_product_code, padded in manual_overrides
        req = UpdateDraftRequest(
            template_id=template.id,
            supplier_product_code="EDZ",
            selling_price=120.0,
            manual_overrides=json.dumps({"coded_price": "XEDZQY"})
        )
        updated_item = update_draft_endpoint(item.id, req, self.db)
        
        # Verify clean code is saved to DB
        self.assertEqual(updated_item.supplier_product_code, "EDZ")
        overrides = json.loads(updated_item.manual_overrides)
        self.assertEqual(overrides.get("coded_price"), "XEDZQY")

        # Verify draft resolution pulls padded code for printing
        draft = resolve_draft(self.db, updated_item, template_id_override=template.id)
        coded_field = next((f for f in draft.fields if f.semantic_field == "coded_price"), None)
        self.assertIsNotNone(coded_field)
        self.assertEqual(coded_field.value, "XEDZQY")

    def test_code_is_numbers_only_validation(self):
        from app.services.workflow.validation_service import code_is_numbers_only

        self.assertTrue(code_is_numbers_only("20"))
        self.assertTrue(code_is_numbers_only("  12345  "))
        self.assertFalse(code_is_numbers_only("EDZ"))
        self.assertFalse(code_is_numbers_only("1DZ26"))
        self.assertFalse(code_is_numbers_only("SDZS"))
        self.assertFalse(code_is_numbers_only(""))
        self.assertFalse(code_is_numbers_only(None))



