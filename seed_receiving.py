import os
from sqlalchemy.orm import Session
from app.db import SessionLocal
from app.models import ReceivingSession, ReceivingItem, Supplier

def seed_data():
    db = SessionLocal()
    
    # Ensure supplier
    supplier = db.query(Supplier).filter(Supplier.name == "Test Supplier").first()
    if not supplier:
        supplier = Supplier(name="Test Supplier")
        db.add(supplier)
        db.commit()
        db.refresh(supplier)
        
    # Check for existing session
    session = db.query(ReceivingSession).filter(ReceivingSession.supplier_id == supplier.id).first()
    if not session:
        session = ReceivingSession(supplier_id=supplier.id, status="RECEIVING")
        db.add(session)
        db.commit()
        db.refresh(session)
        
    # Add some items
    items_to_add = [
        {"raw_description": "SOCKS", "expected_qty": 10},
        {"raw_description": "HANDBAG WITH SERIAL", "expected_qty": 5},
        {"raw_description": "T-SHIRT", "expected_qty": 20},
        {"raw_description": "SHOES", "expected_qty": 2},
    ]
    
    for item_data in items_to_add:
        item = ReceivingItem(
            session_id=session.id,
            raw_description=item_data["raw_description"],
            expected_qty=item_data["expected_qty"]
        )
        db.add(item)
        
    db.commit()
    print(f"Seeded Session ID: {session.id}")
    db.close()

if __name__ == "__main__":
    seed_data()
