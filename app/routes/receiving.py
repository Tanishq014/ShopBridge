from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from app.services.template_filters import register_template_filters
from app.config import TEMPLATES_DIR

router = APIRouter(prefix="/receiving", tags=["receiving"])
templates = register_template_filters(Jinja2Templates(directory=str(TEMPLATES_DIR)))
from sqlalchemy.orm import Session
from sqlalchemy import select
from typing import List

from app.db import get_db
from app.schemas import (
    ReceivingSessionCreate,
    ReceivingSessionRead,
    ReceivingItemCreate,
    ReceivingItemRead,
    SupplierBase,
    SupplierRead,
    SupplierProductMappingCreate,
    SupplierProductMappingRead,
    TallyItemRequest,
)
from app.services.receiving_service import (
    get_or_create_supplier,
    create_receiving_session,
    update_session_status,
    create_receiving_item,
    tally_item,
    map_supplier_product,
)
from app.models import ReceivingSession, ReceivingItem

router = APIRouter(prefix="/receiving", tags=["receiving"])

@router.post("/suppliers", response_model=SupplierRead)
def create_supplier(data: SupplierBase, db: Session = Depends(get_db)):
    return get_or_create_supplier(db, data.name)

@router.post("/sessions", response_model=ReceivingSessionRead)
def create_session(data: ReceivingSessionCreate, db: Session = Depends(get_db)):
    try:
        return create_receiving_session(db, data)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.get("/sessions", response_model=List[ReceivingSessionRead])
def list_sessions(db: Session = Depends(get_db)):
    return db.execute(select(ReceivingSession).order_by(ReceivingSession.created_at.desc())).scalars().all()

@router.post("/sessions/{session_id}/status", response_model=ReceivingSessionRead)
def change_session_status(session_id: int, status: str, db: Session = Depends(get_db)):
    try:
        return update_session_status(db, session_id, status)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.post("/items", response_model=ReceivingItemRead)
def add_item(data: ReceivingItemCreate, db: Session = Depends(get_db)):
    try:
        return create_receiving_item(db, data)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

from fastapi import File, UploadFile, BackgroundTasks
from app.services.extraction_service import start_extraction_job
import shutil
import tempfile
import os

from typing import List

@router.post("/{session_id}/extract")
def extract_invoice_endpoint(
    session_id: int, 
    background_tasks: BackgroundTasks, 
    files: List[UploadFile] = File(...), 
    db: Session = Depends(get_db)
):
    if not files:
        raise HTTPException(status_code=400, detail="No files uploaded")

    file_paths = []
    for file in files:
        ext = ".pdf"
        if file.content_type == "image/jpeg":
            ext = ".jpg"
        elif file.content_type == "image/png":
            ext = ".png"
            
        temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=ext)
        shutil.copyfileobj(file.file, temp_file)
        temp_file.close()
        file_paths.append(temp_file.name)
    
    job = start_extraction_job(
        db=db,
        session_id=session_id,
        file_paths=file_paths,
        mime_type=files[0].content_type,
        background_tasks=background_tasks
    )
    return {"job_id": job.id, "status": job.status}

@router.get("/{session_id}/extraction_status")
def get_extraction_status_endpoint(session_id: int, db: Session = Depends(get_db)):
    from app.models import ExtractionJob
    job = db.query(ExtractionJob).filter(ExtractionJob.session_id == session_id).order_by(ExtractionJob.started_at.desc()).first()
    if not job:
        return {"status": "NOT_FOUND"}
        
    return {
        "job_id": job.id,
        "status": job.status,
        "error": job.error,
        "processing_time": job.processing_time
    }

@router.post("/items/{item_id}/tally", response_model=ReceivingItemRead)
def tally_receiving_item(item_id: int, data: TallyItemRequest, db: Session = Depends(get_db)):
    try:
        return tally_item(db, item_id, data.received_qty)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.post("/mappings", response_model=SupplierProductMappingRead)
def create_mapping(data: SupplierProductMappingCreate, db: Session = Depends(get_db)):
    try:
        return map_supplier_product(
            db, 
            data.supplier_id, 
            data.family_id, 
            data.supplier_product_code, 
            data.supplier_description,
            data.confidence
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.get("/", response_class=HTMLResponse)
def receiving_home(request: Request, db: Session = Depends(get_db)):
    active_sessions = db.execute(
        select(ReceivingSession)
        .where(ReceivingSession.status.in_(["DRAFT", "RECEIVING"]))
        .order_by(ReceivingSession.created_at.desc())
    ).scalars().all()
    
    recent_sessions = db.execute(
        select(ReceivingSession)
        .where(ReceivingSession.status.in_(["COMPLETED", "CANCELLED"]))
        .order_by(ReceivingSession.updated_at.desc())
        .limit(10)
    ).scalars().all()
    
    return templates.TemplateResponse(
        request=request,
        name="receiving_home.html",
        context={
            "active_sessions": active_sessions,
            "recent_sessions": recent_sessions
        }
    )

@router.get("/{session_id}/extracted_json")
def get_extracted_json(session_id: int, db: Session = Depends(get_db)):
    from app.models import ExtractionJob
    job = db.execute(
        select(ExtractionJob)
        .where(ExtractionJob.session_id == session_id)
        .order_by(ExtractionJob.started_at.desc())
    ).scalars().first()
    
    if not job or not job.raw_provider_response:
        raise HTTPException(status_code=404, detail="No extracted JSON found for this session")
        
    import json
    try:
        return Response(content=job.raw_provider_response, media_type="application/json")
    except:
        return {"raw_payload": job.raw_provider_response}

@router.get("/{session_id}", response_class=HTMLResponse)
def receiving_workspace(session_id: int, request: Request, db: Session = Depends(get_db)):
    session = db.get(ReceivingSession, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
        
    items = session.items
    item_dicts = [ReceivingItemRead.model_validate(item).model_dump(mode="json") for item in items]
    
    from app.models import TemplateMaster
    templates_list = db.execute(select(TemplateMaster).where(TemplateMaster.active_status == True)).scalars().all()
    templates_json = [{"id": t.id, "name": t.template_name} for t in templates_list]

    from app.services.settings_service import get_price_code_settings, get_pricing_settings
    price_code_settings = get_price_code_settings()
    pricing_settings = get_pricing_settings()

    return templates.TemplateResponse(
        request=request,
        name="receiving_workspace.html",
        context={
            "session": session,
            "items": items,
            "items_json": item_dicts,
            "templates": templates_list,
            "templates_json": templates_json,
            "price_code_settings_json": {
                "digit_to_code": price_code_settings.digit_to_code,
                "code_to_digit": price_code_settings.code_to_digit
            },
            "pricing_settings": {
                "mrp_rounding": pricing_settings.mrp_rounding,
                "mrp_truncate_decimal": pricing_settings.mrp_truncate_decimal
            }
        }
    )
from fastapi import Form
from fastapi.responses import RedirectResponse, Response
from datetime import datetime
from decimal import Decimal

@router.post("/new", response_class=HTMLResponse)
def create_new_session_ui(request: Request, supplier_name: str = Form(...), invoice_number: str = Form(None), invoice_date: str = Form(None), db: Session = Depends(get_db)):
    try:
        supplier = get_or_create_supplier(db, supplier_name)
        
        inv_date = None
        if invoice_date:
            inv_date = datetime.strptime(invoice_date, "%Y-%m-%d").date()
        
        session_data = ReceivingSessionCreate(
            supplier_id=supplier.id,
            invoice_number=invoice_number,
            invoice_date=inv_date
        )
        session = create_receiving_session(db, session_data)
        
        return RedirectResponse(url=f"/receiving/{session.id}", status_code=303)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.post("/{session_id}/items", response_class=HTMLResponse)
def add_item_ui(
    session_id: int, 
    request: Request, 
    raw_description: str = Form(...), 
    supplier_product_code: str = Form(None), 
    expected_qty: Decimal | None = Form(None), 
    unit: str = Form(None),
    purchase_rate: Decimal | None = Form(None), 
    mrp: Decimal | None = Form(None),
    db: Session = Depends(get_db)
):
    try:
        item_data = ReceivingItemCreate(
            session_id=session_id,
            raw_description=raw_description,
            supplier_product_code=supplier_product_code,
            expected_qty=expected_qty,
            unit=unit,
            purchase_rate=purchase_rate,
            mrp=mrp
        )
        create_receiving_item(db, item_data)
        
        return RedirectResponse(url=f"/receiving/{session_id}", status_code=303)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.post("/{session_id}/start", response_class=HTMLResponse)
def start_receiving_ui(session_id: int, request: Request, db: Session = Depends(get_db)):
    try:
        update_session_status(db, session_id, "RECEIVING")
        return RedirectResponse(url=f"/receiving/{session_id}", status_code=303)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

from app.schemas import MatchFamilyRequest, ConfirmPricingRequest, PrintLabelRequest
from app.services.receiving_service import match_product_family, confirm_item_pricing, queue_print_item

@router.post("/items/{item_id}/match_family", response_model=ReceivingItemRead)
def match_family_endpoint(item_id: int, data: MatchFamilyRequest, db: Session = Depends(get_db)):
    try:
        return match_product_family(db, item_id, data.family_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

from app.schemas import UpdateDraftRequest
from app.services.workflow.label_draft_service import resolve_draft

@router.put("/items/{item_id}/draft", response_model=ReceivingItemRead)
def update_draft_endpoint(item_id: int, data: UpdateDraftRequest, db: Session = Depends(get_db)):
    item = db.get(ReceivingItem, item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
        
    if data.template_id is not None:
        item.template_id = data.template_id
        
        # Update Supplier Invoice Profile
        if item.session and item.session.supplier:
            supplier = item.session.supplier
            import json
            profile = {}
            if supplier.invoice_profile:
                try:
                    profile = json.loads(supplier.invoice_profile)
                except:
                    pass
            profile["preferred_template_id"] = data.template_id
            profile["last_used_at"] = str(datetime.utcnow())
            supplier.invoice_profile = json.dumps(profile)
            db.add(supplier)
    if data.billing_item is not None:
        item.billing_item = data.billing_item
    if data.manual_overrides is not None:
        item.manual_overrides = data.manual_overrides
        
    db.add(item)
    db.commit()
    db.refresh(item)
    return item

@router.get("/items/{item_id}/draft_status")
def get_draft_status_endpoint(item_id: int, db: Session = Depends(get_db)):
    item = db.get(ReceivingItem, item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
        
    draft = resolve_draft(db, item)
    import dataclasses
    return dataclasses.asdict(draft)

@router.post("/items/{item_id}/price", response_model=ReceivingItemRead)
def confirm_pricing_endpoint(item_id: int, data: ConfirmPricingRequest, db: Session = Depends(get_db)):
    try:
        return confirm_item_pricing(
            db, item_id, data.landing_price, data.mrp, data.selling_price, data.manual_barcode or ""
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.post("/items/{item_id}/print", response_model=ReceivingItemRead)
def print_label_endpoint(item_id: int, data: PrintLabelRequest, db: Session = Depends(get_db)):
    try:
        return queue_print_item(db, item_id, data.copies, force_reprint=data.force_reprint)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

from app.services.workflow.pricing_suggestion_service import generate_pricing_suggestions

@router.get("/items/{item_id}/pricing_suggestions")
def get_pricing_suggestions(item_id: int, landing_price: Decimal | None = None, mrp: Decimal | None = None, db: Session = Depends(get_db)):
    item = db.get(ReceivingItem, item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    
    from app.models import ProductFamily
    family = db.get(ProductFamily, item.family_id) if item.family_id else None
    suggestion = generate_pricing_suggestions(db, family, landing_price, mrp)
    return suggestion

@router.get("/items/{item_id}/previous_price")
def get_previous_price(item_id: int, db: Session = Depends(get_db)):
    item = db.get(ReceivingItem, item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
        
    if not item.family_id:
        return {"mrp": None, "selling_price": None}
        
    from app.services.workflow.variant_resolution_service import get_preferred_previous_variant
    preferred = get_preferred_previous_variant(db, item.family_id, item.supplier_product_code)
    
    if preferred:
        return {"mrp": preferred.mrp, "selling_price": preferred.selling_price}
    return {"mrp": None, "selling_price": None}

@router.get("/items/{item_id}/derive_mrp")
def derive_mrp_endpoint(item_id: int, selling_price: Decimal, discount_percent: Decimal, db: Session = Depends(get_db)):
    if discount_percent >= 100:
        return {"mrp": None}
    
    from app.services.workflow.pricing_suggestion_service import _apply_rounding
    from app.services.settings_service import get_pricing_settings
    settings = get_pricing_settings()
    
    mrp = selling_price / (Decimal("1") - discount_percent / Decimal("100"))
    mrp = _apply_rounding(mrp, settings.mrp_rounding, settings.mrp_truncate_decimal)
    return {"mrp": mrp}

@router.get("/items/{item_id}/derive_selling")
def derive_selling_endpoint(item_id: int, mrp: Decimal, discount_percent: Decimal, db: Session = Depends(get_db)):
    from app.services.workflow.pricing_suggestion_service import _apply_rounding
    from app.services.settings_service import get_pricing_settings
    settings = get_pricing_settings()
    
    selling = mrp * (Decimal("1") - discount_percent / Decimal("100"))
    selling = _apply_rounding(selling, settings.mrp_rounding, settings.mrp_truncate_decimal)
    return {"selling_price": selling}

