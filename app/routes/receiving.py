from fastapi import APIRouter, Depends, HTTPException, Request, Form, File, UploadFile, BackgroundTasks
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from app.services.template_filters import register_template_filters
from app.config import TEMPLATES_DIR
from datetime import datetime, timezone
from decimal import Decimal
from typing import List
import json
import shutil
import tempfile
import os

router = APIRouter(prefix="/receiving", tags=["receiving"])
templates = register_template_filters(Jinja2Templates(directory=str(TEMPLATES_DIR)))
from sqlalchemy.orm import Session
from sqlalchemy import select

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

@router.post("/sessions/delete-all")
@router.delete("/sessions")
def delete_all_sessions(request: Request, db: Session = Depends(get_db)):
    from app.models import ExtractionJob
    # Clean up any source documents stored on disk
    sessions = db.query(ReceivingSession).all()
    for s in sessions:
        if s.source_document_path and os.path.exists(s.source_document_path):
            try:
                os.remove(s.source_document_path)
            except Exception:
                pass
    db.query(ExtractionJob).delete(synchronize_session=False)
    db.query(ReceivingItem).delete(synchronize_session=False)
    count = db.query(ReceivingSession).delete(synchronize_session=False)
    db.commit()
    if "application/json" in request.headers.get("accept", ""):
        return {"status": "deleted", "deleted_count": count}
    return RedirectResponse(url="/receiving/", status_code=303)

@router.post("/sessions/{session_id}/delete")
@router.delete("/sessions/{session_id}")
def delete_session(session_id: int, request: Request, db: Session = Depends(get_db)):
    from app.models import ExtractionJob
    session = db.get(ReceivingSession, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    if session.source_document_path and os.path.exists(session.source_document_path):
        try:
            os.remove(session.source_document_path)
        except Exception:
            pass
    db.query(ExtractionJob).filter(ExtractionJob.session_id == session_id).delete(synchronize_session=False)
    db.query(ReceivingItem).filter(ReceivingItem.session_id == session_id).delete(synchronize_session=False)
    db.delete(session)
    db.commit()
    if "application/json" in request.headers.get("accept", ""):
        return {"status": "deleted", "session_id": session_id}
    return RedirectResponse(url="/receiving/", status_code=303)

@router.post("/items", response_model=ReceivingItemRead)
def add_item(data: ReceivingItemCreate, db: Session = Depends(get_db)):
    try:
        return create_receiving_item(db, data)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

from app.services.extraction_service import start_extraction_job

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
    
    try:
        job = start_extraction_job(
            db=db,
            session_id=session_id,
            file_paths=file_paths,
            mime_type=files[0].content_type,
            background_tasks=background_tasks
        )
        return {"job_id": job.id, "status": job.status}
    except Exception as e:
        for p in file_paths:
            try:
                if os.path.exists(p):
                    os.remove(p)
            except:
                pass
        raise HTTPException(status_code=500, detail=str(e))

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
    
    from app.models import Supplier
    suppliers = db.execute(select(Supplier).order_by(Supplier.name)).scalars().all()
    
    return templates.TemplateResponse(
        request=request,
        name="receiving_home.html",
        context={
            "active_sessions": active_sessions,
            "recent_sessions": recent_sessions,
            "suppliers": suppliers
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

@router.get("/{session_id}/grid_data")
def get_grid_data(session_id: int, template_id: int | None = None, db: Session = Depends(get_db)):
    session = db.get(ReceivingSession, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
        
    from app.services.workflow.label_draft_service import resolve_draft
    
    grid_rows = []
    sorted_items = sorted(session.items, key=lambda x: (x.source_page_number or 0, x.bill_row_number or 0, x.id))
    for item in sorted_items:
        draft = resolve_draft(db, item, template_id_override=template_id)
        
        # Flatten draft fields into a dict
        dynamic_fields = {}
        for f in draft.fields:
            dynamic_fields[f.semantic_field] = {
                "value": f.value,
                "source": f.source,
                "missing": f.missing
            }
            
        row = {
            "id": item.id,
            "raw_description": item.raw_description,
            "billing_item": item.billing_item,
            "supplier_product_code": item.supplier_product_code,
            "family_id": item.family_id,
            "expected_qty": item.expected_qty,
            "received_qty": item.received_qty,
            "purchase_rate": item.purchase_rate,
            "landing_price": item.landing_price,
            "mrp": item.mrp,
            "selling_price": item.confirmed_selling_price,
            "label_status": item.label_status,
            "tally_status": item.tally_status,
            "pricing_status": item.pricing_status,
            "unit": item.unit,
            "source_row_number": item.source_row_number,
            "dynamic_fields": dynamic_fields,
            "template_id": template_id or item.template_id
        }
        grid_rows.append(row)
    from app.models import ExtractionJob
    job = db.execute(
        select(ExtractionJob)
        .where(ExtractionJob.session_id == session_id)
        .order_by(ExtractionJob.started_at.desc())
    ).scalars().first()
    
    global_discounts = []
    global_taxes = []
    
    if job and job.raw_provider_response:
        import json
        try:
            pages = json.loads(job.raw_provider_response)
            if isinstance(pages, list) and len(pages) > 0:
                first_page = pages[0]
                global_discounts = first_page.get("global_discounts") or []
                global_taxes = first_page.get("global_taxes") or []
            elif isinstance(pages, dict):
                global_discounts = pages.get("global_discounts") or []
                global_taxes = pages.get("global_taxes") or []
        except Exception:
            pass
            
    code_target_length = 0
    if template_id:
        from app.models import TemplateMaster
        from app.services.workflow.template_field_service import parse_field_defaults
        tmpl = db.get(TemplateMaster, template_id)
        if tmpl and tmpl.default_field_values:
            defaults = parse_field_defaults(tmpl.default_field_values)
            code_def = defaults.get("coded_price") or defaults.get("code") or defaults.get("price_code") or ""
            if code_def:
                code_target_length = len(str(code_def))

    return {
        "items": grid_rows, 
        "global_discounts": global_discounts, 
        "global_taxes": global_taxes,
        "code_target_length": code_target_length
    }

@router.get("/{session_id}", response_class=HTMLResponse)
def receiving_workspace(session_id: int, request: Request, db: Session = Depends(get_db)):
    session = db.get(ReceivingSession, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
        
    items = session.items
    item_dicts = [ReceivingItemRead.model_validate(item).model_dump(mode="json") for item in items]
    
    from app.models import TemplateMaster
    from app.services.workflow.template_field_service import parse_field_defaults
    templates_list = db.execute(select(TemplateMaster).where(TemplateMaster.active_status == True)).scalars().all()
    templates_json = []
    for t in templates_list:
        code_len = 0
        if t.default_field_values:
            defaults = parse_field_defaults(t.default_field_values)
            c = defaults.get("coded_price") or defaults.get("code") or defaults.get("price_code") or ""
            if c:
                code_len = len(str(c))
        templates_json.append({"id": t.id, "name": t.template_name, "code_target_length": code_len})

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

@router.post("/new", response_class=HTMLResponse)
def create_new_session_ui(
    request: Request, 
    supplier_name: str = Form(...), 
    invoice_number: str = Form(None), 
    invoice_date: str = Form(None), 
    extraction_notes: str = Form(None),
    structured_aliases: str = Form(None),
    db: Session = Depends(get_db)
):
    try:
        # 1. Validate inputs before touching the DB
        inv_date = None
        if invoice_date:
            inv_date = datetime.strptime(invoice_date, "%Y-%m-%d").date()
            
        parsed_aliases = None
        if structured_aliases is not None:
            val = structured_aliases.strip()
            if val:
                import json
                try:
                    obj = json.loads(val)
                    if not isinstance(obj, dict):
                        raise ValueError("Structured Aliases must be a JSON dictionary (object).")
                    parsed_aliases = val
                except json.JSONDecodeError:
                    raise ValueError("Structured Aliases must be valid JSON format.")
                    
        # 2. Apply DB state
        supplier = get_or_create_supplier(db, supplier_name)
        
        # Save Supplier AI instructions
        if extraction_notes is not None:
            supplier.extraction_notes = extraction_notes.strip() if extraction_notes.strip() else None
            
        if structured_aliases is not None:
            supplier.structured_aliases = parsed_aliases
            
        # 3. Create session (this calls db.commit() internally)
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
        from sqlalchemy import func
        from app.models import ReceivingItem
        max_row = db.query(func.max(ReceivingItem.bill_row_number)).filter(ReceivingItem.session_id == session_id).scalar() or 0
        
        item_data = ReceivingItemCreate(
            session_id=session_id,
            bill_row_number=max_row + 1,
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
            profile["last_used_at"] = str(datetime.now(timezone.utc).replace(tzinfo=None))
            supplier.invoice_profile = json.dumps(profile)
            db.add(supplier)
    update_data = data.model_dump(exclude_unset=True)
    if "billing_item" in update_data:
        item.billing_item = update_data["billing_item"]
        
    if "manual_overrides" in update_data:
        from app.services.workflow.form_state_service import parse_extra_field_values
        import json
        try:
            current = parse_extra_field_values(item.manual_overrides)
            new_overrides = parse_extra_field_values(data.manual_overrides)
            current.update(new_overrides)
            item.manual_overrides = json.dumps(current)
        except Exception:
            item.manual_overrides = data.manual_overrides
            
    if "mrp" in update_data:
        item.mrp = update_data["mrp"]
        
    if "purchase_rate" in update_data:
        item.purchase_rate = update_data["purchase_rate"]
        
    if "landing_price" in update_data:
        item.landing_price = update_data["landing_price"]
        
    if "selling_price" in update_data:
        item.confirmed_selling_price = update_data["selling_price"]
        
    if "supplier_product_code" in update_data:
        item.supplier_product_code = update_data["supplier_product_code"]
        
    if "received_qty" in update_data:
        if update_data["received_qty"] is not None and update_data["received_qty"] < 0:
            raise HTTPException(status_code=400, detail="Received quantity cannot be negative")
        item.received_qty = update_data["received_qty"]
        if item.received_qty is None:
            item.tally_status = "UNVERIFIED"
        elif item.expected_qty is not None:
            item.tally_status = "VERIFIED" if item.received_qty == item.expected_qty else "MISMATCH"
        
    db.add(item)
    db.commit()
    db.refresh(item)
    
    if "received_qty" in update_data and update_data["received_qty"] is not None:
        if item.session and item.session.status == "RECEIVING":
            from app.services.receiving_service import tally_item
            try:
                item = tally_item(db, item.id, update_data["received_qty"])
            except Exception:
                pass # Ignore tally errors in draft save
            
    return item

@router.get("/items/{item_id}/draft_status")
def get_draft_status_endpoint(item_id: int, db: Session = Depends(get_db)):
    item = db.get(ReceivingItem, item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
        
    draft = resolve_draft(db, item)
    import dataclasses
    res = dataclasses.asdict(draft)
    res["billing_item"] = item.billing_item or ""
    return res

@router.post("/items/{item_id}/price", response_model=ReceivingItemRead)
def confirm_pricing_endpoint(item_id: int, data: ConfirmPricingRequest, db: Session = Depends(get_db)):
    try:
        return confirm_item_pricing(
            db, 
            item_id, 
            data.landing_price, 
            data.mrp, 
            data.selling_price, 
            data.manual_barcode or "",
            template_id=data.template_id
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.post("/items/{item_id}/print", response_model=ReceivingItemRead)
def print_label_endpoint(item_id: int, data: PrintLabelRequest, db: Session = Depends(get_db)):
    try:
        item = queue_print_item(
            db, 
            item_id, 
            data.copies, 
            force_reprint=data.force_reprint, 
            template_id=data.template_id
        )
        if item.label_status == "FAILED":
            raise HTTPException(status_code=500, detail="Print job failed. Check printer connection and logs.")
        return item
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

