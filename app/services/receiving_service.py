from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

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
    SupplierBase,
    SupplierProductMappingCreate,
)

def normalize_supplier_code(code: Optional[str]) -> Optional[str]:
    if not code:
        return None
    return code.strip().upper()


def get_or_create_supplier(db: Session, name: str) -> Supplier:
    name = name.strip()
    supplier = db.execute(select(Supplier).where(Supplier.name == name)).scalar_one_or_none()
    if not supplier:
        supplier = Supplier(name=name)
        db.add(supplier)
        db.commit()
        db.refresh(supplier)
    return supplier


def create_receiving_session(db: Session, data: ReceivingSessionCreate) -> ReceivingSession:
    supplier = db.get(Supplier, data.supplier_id)
    if not supplier:
        raise ValueError("Supplier not found")
        
    session = ReceivingSession(
        supplier_id=data.supplier_id,
        invoice_number=data.invoice_number,
        invoice_date=data.invoice_date,
        source_document_path=data.source_document_path,
        status="DRAFT",
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    return session


def update_session_status(db: Session, session_id: int, status: str) -> ReceivingSession:
    session = db.get(ReceivingSession, session_id)
    if not session:
        raise ValueError("Session not found")
        
    valid_transitions = {
        "DRAFT": ["RECEIVING", "CANCELLED"],
        "RECEIVING": ["COMPLETED", "CANCELLED"],
        "COMPLETED": [],
        "CANCELLED": []
    }
    
    if status not in valid_transitions.get(session.status, []):
        raise ValueError(f"Invalid transition from {session.status} to {status}")
        
    if session.status == "DRAFT" and status == "RECEIVING":
        if not session.items:
            raise ValueError("Cannot start receiving session with zero items")
            
    if session.status == "RECEIVING" and status == "COMPLETED":
        for item in session.items:
            if item.tally_status == "UNVERIFIED":
                raise ValueError("Cannot complete session while items are UNVERIFIED")
            
            if item.received_qty is not None and item.received_qty > 0:
                if item.pricing_status != "CONFIRMED":
                    raise ValueError("Cannot complete session: some received items require pricing confirmation")
                if item.label_status not in ("NOT_REQUIRED", "QUEUED", "PRINTED"):
                    raise ValueError(f"Cannot complete session: label printing not resolved for {item.raw_description} (status: {item.label_status})")

    session.status = status
    db.add(session)
    db.commit()
    db.refresh(session)
    return session


def map_supplier_product(
    db: Session, 
    supplier_id: int, 
    family_id: int, 
    supplier_product_code: Optional[str] = None, 
    supplier_description: Optional[str] = None,
    confidence: Optional[Decimal] = None
) -> SupplierProductMapping:
    supplier = db.get(Supplier, supplier_id)
    if not supplier:
        raise ValueError("Supplier not found")
    family = db.get(ProductFamily, family_id)
    if not family:
        raise ValueError("ProductFamily not found")

    supplier_product_code = normalize_supplier_code(supplier_product_code)
    
    if supplier_product_code:
        existing = db.execute(
            select(SupplierProductMapping)
            .where(SupplierProductMapping.supplier_id == supplier_id)
            .where(SupplierProductMapping.supplier_product_code == supplier_product_code)
        ).scalar_one_or_none()
        
        if existing:
            if existing.family_id != family_id:
                raise ValueError("Conflicting mapping: supplier product code is already mapped to a different family.")
            existing.last_seen_at = datetime.utcnow()
            existing.supplier_description = supplier_description
            if confidence is not None:
                existing.confidence = confidence
            db.add(existing)
            db.commit()
            db.refresh(existing)
            return existing

    mapping = SupplierProductMapping(
        supplier_id=supplier_id,
        supplier_product_code=supplier_product_code,
        supplier_description=supplier_description,
        family_id=family_id,
        confidence=confidence
    )
    try:
        db.add(mapping)
        db.commit()
        db.refresh(mapping)
    except IntegrityError:
        db.rollback()
        raise ValueError("Conflicting mapping exists.")
    return mapping


def _resolve_family_id(db: Session, supplier_id: int, supplier_product_code: Optional[str]) -> Optional[int]:
    supplier_product_code = normalize_supplier_code(supplier_product_code)
    if not supplier_product_code:
        return None
    mapping = db.execute(
        select(SupplierProductMapping)
        .where(SupplierProductMapping.supplier_id == supplier_id)
        .where(SupplierProductMapping.supplier_product_code == supplier_product_code)
    ).scalar_one_or_none()
    return mapping.family_id if mapping else None


def create_receiving_item(db: Session, data: ReceivingItemCreate) -> ReceivingItem:
    session = db.get(ReceivingSession, data.session_id)
    if not session:
        raise ValueError("Session not found")
        
    if session.status not in ("DRAFT", "RECEIVING"):
        raise ValueError(f"Cannot add items to session in {session.status} status")
        
    if data.expected_qty is not None and data.expected_qty < 0:
        raise ValueError("Expected quantity cannot be negative")
        
    family_id = data.family_id
    if family_id:
        family = db.get(ProductFamily, family_id)
        if not family:
            raise ValueError("ProductFamily not found")
    else:
        family_id = _resolve_family_id(db, session.supplier_id, data.supplier_product_code)
        
    preferred_template_id = None
    if session.supplier.invoice_profile:
        import json
        try:
            prof = json.loads(session.supplier.invoice_profile)
            preferred_template_id = prof.get("preferred_template_id")
        except:
            pass

    item = ReceivingItem(
        session_id=data.session_id,
        template_id=preferred_template_id,
        bill_row_number=data.bill_row_number,
        raw_description=data.raw_description,
        normalized_description=data.normalized_description,
        supplier_product_code=normalize_supplier_code(data.supplier_product_code),
        extraction_confidence=data.extraction_confidence,
        source_provenance=data.source_provenance,
        expected_qty=data.expected_qty,
        received_qty=None,  # Always NULL initially
        unit=data.unit,
        purchase_rate=data.purchase_rate,
        list_price=data.list_price,
        mrp=data.mrp,
        discount=data.discount,
        line_amount=data.line_amount,
        family_id=family_id,
        matched_variant_id=None, # Explicitly null for Phase 1
        tally_status="UNVERIFIED",
        pricing_status="PENDING",
        label_status="UNRESOLVED"
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


def tally_item(db: Session, item_id: int, received_qty: Decimal) -> ReceivingItem:
    item = db.get(ReceivingItem, item_id)
    if not item:
        raise ValueError("Receiving item not found")
        
    if item.session.status != "RECEIVING":
        raise ValueError("Cannot tally item unless session is RECEIVING")
        
    if received_qty < 0:
        raise ValueError("Received quantity cannot be negative")
        
    item.received_qty = received_qty
    
    if received_qty == 0:
        item.tally_status = "UNVERIFIED"
    elif item.expected_qty is not None and item.received_qty == item.expected_qty:
        item.tally_status = "VERIFIED"
    else:
        item.tally_status = "MISMATCH"
        
    db.add(item)
    db.commit()
    db.refresh(item)
    return item

def match_product_family(db: Session, item_id: int, family_id: int) -> ReceivingItem:
    item = db.get(ReceivingItem, item_id)
    if not item:
        raise ValueError("Receiving item not found")
    family = db.get(ProductFamily, family_id)
    if not family:
        raise ValueError("Product family not found")
        
    item.family_id = family.id
    db.add(item)
    
    # Auto-learn mapping if supplier product code is present
    if item.supplier_product_code:
        map_supplier_product(
            db, 
            supplier_id=item.session.supplier_id, 
            family_id=family.id, 
            supplier_product_code=item.supplier_product_code
        )
            
    db.commit()
    db.refresh(item)
    return item


def confirm_item_pricing(
    db: Session, 
    item_id: int, 
    landing_price: Decimal | None, 
    mrp: Decimal | None, 
    selling_price: Decimal,
    manual_barcode: str = ""
) -> ReceivingItem:
    item = db.get(ReceivingItem, item_id)
    if not item:
        raise ValueError("Receiving item not found")
    if item.tally_status == "UNVERIFIED":
        raise ValueError("Cannot price an unverified item")
        
    from app.services.workflow.variant_resolution_service import resolve_variant_for_receiving
    from app.services.workflow.label_draft_service import resolve_draft
    
    draft = resolve_draft(db, item)
    
    # Safely resolve variant
    variant = resolve_variant_for_receiving(
        db=db,
        draft=draft,
        billing_item=item.billing_item or "",
        mrp=mrp,
        selling_price=selling_price,
        manual_barcode=manual_barcode
    )
    
    item.family_id = variant.family_id
    item.matched_variant_id = variant.id
    item.landing_price = landing_price
    item.mrp = mrp
    item.confirmed_selling_price = selling_price
    item.pricing_status = "CONFIRMED"
    item.pricing_confirmed_at = datetime.utcnow()
    
    # Default label status if we haven't printed
    if item.label_status in ("UNRESOLVED", "NOT_REQUIRED", "FAILED"):
        item.label_status = "PENDING"
        
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


def queue_print_item(db: Session, item_id: int, copies: int, force_reprint: bool = False) -> ReceivingItem:
    item = db.get(ReceivingItem, item_id)
    if not item:
        raise ValueError("Receiving item not found")
    if item.pricing_status != "CONFIRMED" or not item.matched_variant_id:
        raise ValueError("Cannot print item before pricing is confirmed")
        
    if copies <= 0:
        item.label_status = "NOT_REQUIRED"
        db.add(item)
        db.commit()
        db.refresh(item)
        return item
        
    if not force_reprint and item.label_status in ("QUEUED", "PRINTED"):
        return item # Idempotent if already printed/queued and not forced
        
    from app.services.workflow.print_service import create_print_job
    variant = item.matched_variant
    
    from app.services.workflow.form_state_service import variant_template_id
    template_id = variant_template_id(variant)
    from app.models import TemplateMaster
    template = db.get(TemplateMaster, template_id) if template_id else None
    
    if not template:
        item.label_status = "MISSING_TEMPLATE"
        db.add(item)
        db.commit()
        db.refresh(item)
        return item
        
    try:
        job = create_print_job(db, variant, template, copies)
        if job.status == "failed":
            item.label_status = "FAILED"
        elif job.status == "pending":
            item.label_status = "QUEUED" # CSV mode or async
        elif job.status == "printed":
            item.label_status = "PRINTED"
    except Exception as exc:
        item.label_status = "FAILED"
        
    db.add(item)
    db.commit()
    db.refresh(item)
    return item
