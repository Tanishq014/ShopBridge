import unittest
from decimal import Decimal
from datetime import datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from fastapi.testclient import TestClient

from app.db import Base, get_db
from app.main import app
from app.models import ReceivingSession, ReceivingItem, ProductFamily, Supplier, LabelVariant, PricingRule, TemplateMaster, PrintJob
from app.services.receiving_service import update_session_status

class TestReceivingPhase3(unittest.TestCase):
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

    def setup_phase3_data(self):
        supplier = Supplier(name="Test Supplier P3")
        self.db.add(supplier)
        self.db.commit()
        
        template = TemplateMaster(template_id="TEST_TMPL", template_name="Test", bartender_file_path="C:\\test.btw")
        self.db.add(template)
        self.db.commit()
        
        family = ProductFamily(family_name="Test Family", category="clothes", default_template_id=template.id, default_tax_rate=0, default_unit="PCS")
        self.db.add(family)
        self.db.commit()
        
        session = ReceivingSession(supplier_id=supplier.id, status="RECEIVING")
        self.db.add(session)
        self.db.commit()
        
        return supplier, template, family, session

    def test_pricing_suggestions_markup(self):
        rule = PricingRule(category="clothes", cost_rule_type="MARKUP", cost_rule_percent=Decimal("50"))
        self.db.add(rule)
        self.db.commit()
        
        from app.services.workflow.pricing_suggestion_service import generate_pricing_suggestions
        family = ProductFamily(family_name="P3", category="clothes")
        
        sugg = generate_pricing_suggestions(self.db, family, landing_price=Decimal("100"), mrp=None)
        self.assertEqual(sugg.cost_based_suggestion, Decimal("150"))

    def test_pricing_suggestions_gross_margin(self):
        from app.services.workflow.pricing_suggestion_service import generate_pricing_suggestions
        rule = PricingRule(category="shoes", cost_rule_type="GROSS_MARGIN", cost_rule_percent=Decimal("50"))
        self.db.add(rule)
        self.db.commit()
        
        family = ProductFamily(family_name="P3", category="shoes")
        sugg = generate_pricing_suggestions(self.db, family, landing_price=Decimal("100"), mrp=None)
        self.assertEqual(sugg.cost_based_suggestion, Decimal("200"))

    def test_pricing_suggestions_zero_handling(self):
        from app.services.workflow.pricing_suggestion_service import generate_pricing_suggestions
        rule = PricingRule(category="zero", cost_rule_type="GROSS_MARGIN", cost_rule_percent=Decimal("100"))
        self.db.add(rule)
        self.db.commit()
        
        family = ProductFamily(family_name="P3", category="zero")
        try:
            sugg = generate_pricing_suggestions(self.db, family, landing_price=Decimal("100"), mrp=None)
            self.assertIsNone(sugg.cost_based_suggestion)
        except ZeroDivisionError:
            self.fail("Failed to handle zero/100% margin safely")

    def test_pricing_persistence_and_variant_creation(self):
        supplier, template, family, session = self.setup_phase3_data()
        
        item = ReceivingItem(session_id=session.id, raw_description="Item 1", expected_qty=10, received_qty=10, tally_status="VERIFIED", billing_item="Test Family", template_id=template.id)
        self.db.add(item)
        self.db.commit()
        self.db.refresh(item)
        
        res = self.client.post(f"/receiving/items/{item.id}/price", json={
            "landing_price": "100",
            "mrp": "200",
            "selling_price": "150"
        })
        self.assertEqual(res.status_code, 200)
        
        self.db.refresh(item)
        self.assertEqual(item.pricing_status, "CONFIRMED")
        self.assertEqual(item.confirmed_selling_price, Decimal("150"))
        self.assertEqual(item.landing_price, Decimal("100"))
        self.assertIsNotNone(item.matched_variant_id)
        
        variant1 = self.db.get(LabelVariant, item.matched_variant_id)
        self.assertEqual(variant1.mrp, Decimal("200"))
        self.assertEqual(variant1.selling_price, Decimal("150"))
        
        res = self.client.post(f"/receiving/items/{item.id}/price", json={
            "landing_price": "100",
            "mrp": "200",
            "selling_price": "150"
        })
        self.assertEqual(res.status_code, 200)
        self.db.refresh(item)
        self.assertEqual(item.matched_variant_id, variant1.id)

        res = self.client.post(f"/receiving/items/{item.id}/price", json={
            "landing_price": "90", 
            "mrp": "200",
            "selling_price": "150"
        })
        self.assertEqual(res.status_code, 200)
        self.db.refresh(item)
        self.assertEqual(item.landing_price, Decimal("90"))
        self.assertEqual(item.matched_variant_id, variant1.id)

        res = self.client.post(f"/receiving/items/{item.id}/price", json={
            "landing_price": "90",
            "mrp": "250", 
            "selling_price": "150"
        })
        self.assertEqual(res.status_code, 200)
        self.db.refresh(item)
        self.assertNotEqual(item.matched_variant_id, variant1.id)
        variant2 = self.db.get(LabelVariant, item.matched_variant_id)
        self.assertEqual(variant2.mrp, Decimal("250"))
        
        # A -> B -> A regression test
        res = self.client.post(f"/receiving/items/{item.id}/price", json={
            "landing_price": "100",
            "mrp": "200", 
            "selling_price": "150"
        })
        self.assertEqual(res.status_code, 200)
        self.db.refresh(item)
        self.assertEqual(item.matched_variant_id, variant1.id) # EXACT REUSE

    def test_completion_blocking(self):
        supplier, template, family, session = self.setup_phase3_data()
        
        item1 = ReceivingItem(session_id=session.id, raw_description="Item 1", tally_status="UNVERIFIED", billing_item="Test Family", template_id=template.id)
        self.db.add(item1)
        self.db.commit()
        
        with self.assertRaises(ValueError) as context:
            update_session_status(self.db, session.id, "COMPLETED")
        self.assertTrue("UNVERIFIED" in str(context.exception))
            
        item1.tally_status = "VERIFIED"
        item1.received_qty = Decimal("10")
        item1.pricing_status = "PENDING"
        self.db.commit()
        
        with self.assertRaises(ValueError) as context:
            update_session_status(self.db, session.id, "COMPLETED")
        self.assertTrue("pricing confirmation" in str(context.exception).lower())
            
        item1.pricing_status = "CONFIRMED"
        item1.label_status = "FAILED"
        self.db.commit()
        
        with self.assertRaises(ValueError) as context:
            update_session_status(self.db, session.id, "COMPLETED")
        self.assertTrue("label printing not resolved" in str(context.exception).lower())
            
        item1.label_status = "QUEUED"
        self.db.commit()
        
        update_session_status(self.db, session.id, "COMPLETED")
        self.assertEqual(session.status, "COMPLETED")

    def test_zero_received_bypass(self):
        supplier, template, family, session = self.setup_phase3_data()
        
        item = ReceivingItem(session_id=session.id, raw_description="Zero", tally_status="VERIFIED", received_qty=Decimal("0"), expected_qty=Decimal("10"))
        self.db.add(item)
        self.db.commit()
        
        update_session_status(self.db, session.id, "COMPLETED")
        self.assertEqual(session.status, "COMPLETED")
