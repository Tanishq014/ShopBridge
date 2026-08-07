import os
import sys
from decimal import Decimal
from datetime import datetime

# Ensure app is in path
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

from app.db import SessionLocal, engine, Base
from app.schemas import ReceivingSessionCreate, ReceivingItemCreate
from app.services.receiving_service import (
    get_or_create_supplier,
    create_receiving_session,
    update_session_status,
    create_receiving_item
)

def seed_receiving_session():
    # Ensure tables exist
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        # Create Supplier
        supplier_name = "MOCK SUPPLIER PVT LTD"
        supplier = get_or_create_supplier(db, supplier_name)
        
        # Create DRAFT Session
        session_data = ReceivingSessionCreate(
            supplier_id=supplier.id,
            invoice_number=f"MOCK-INV-{datetime.now().strftime('%H%M%S')}",
            invoice_date=datetime.now()
        )
        session = create_receiving_session(db, session_data)

        mock_items = [
            {"desc": "HAND WALLET", "code": "HBCH2150-1", "qty": 2, "rate": 396},
            {"desc": "HAND WALLET", "code": "HBCH2150-2", "qty": 1, "rate": 348},
            {"desc": "COPPY PURSE", "code": "EK165084", "qty": 4, "rate": 214},
            {"desc": "SOCKS", "code": "", "qty": 36, "rate": 46},
            {"desc": "SOCKS", "code": "", "qty": 48, "rate": 55},
            {"desc": "LAK C.C 399", "code": "", "qty": 5, "rate": 180},
            {"desc": "NIVEA.ROLL.249", "code": "", "qty": 6, "rate": 145},
            {"desc": "GANESH JI", "code": "", "qty": 1, "rate": 380},
            {"desc": "GANESH JI", "code": "", "qty": 1, "rate": 341},
            {"desc": "KEY CHAIN", "code": "", "qty": 2, "rate": 65},
            {"desc": "KEY CHAIN", "code": "", "qty": 3, "rate": 20},
        ]

        row_num = 1
        for item in mock_items:
            item_data = ReceivingItemCreate(
                session_id=session.id,
                bill_row_number=row_num,
                raw_description=item["desc"],
                supplier_product_code=item["code"] if item["code"] else None,
                expected_qty=Decimal(str(item["qty"])),
                unit="PCS",
                purchase_rate=Decimal(str(item["rate"]))
            )
            create_receiving_item(db, item_data)
            row_num += 1

        # Transition to RECEIVING after adding rows
        update_session_status(db, session.id, "RECEIVING")

        print(f"Mock session created successfully! Session ID: {session.id}")
        print("Navigate to /receiving to see it.")

    except Exception as e:
        print(f"Failed to seed: {e}")
    finally:
        db.close()

if __name__ == "__main__":
    seed_receiving_session()
