import json
import uuid
import time
from datetime import datetime
from sqlalchemy.orm import Session
from fastapi import BackgroundTasks

from app.models import ExtractionJob, ReceivingSession, ReceivingItem, Supplier, TemplateMaster, SupplierExtractionExample
from app.extraction.gemini_provider import GeminiProvider

def start_extraction_job(
    db: Session,
    session_id: int,
    file_path: str,
    mime_type: str,
    background_tasks: BackgroundTasks
) -> ExtractionJob:
    # 1. Create the ExtractionJob in DB
    job = ExtractionJob(
        session_id=session_id,
        provider="Gemini",
        status="PENDING",
        started_at=datetime.utcnow()
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    # 2. Enqueue the background task
    background_tasks.add_task(
        _run_extraction_task,
        job_id=job.id,
        session_id=session_id,
        file_path=file_path,
        mime_type=mime_type
    )
    
    return job

async def _run_extraction_task(job_id: int, session_id: int, file_path: str, mime_type: str):
    # This needs its own DB session since it runs in the background
    from app.db import SessionLocal
    db = SessionLocal()
    job = None
    try:
        job = db.query(ExtractionJob).get(job_id)
        if not job:
            return
            
        session = db.query(ReceivingSession).get(session_id)
        supplier = session.supplier
        
        # Gather templates
        templates_db = db.query(TemplateMaster).filter(TemplateMaster.active_status == True).all()
        templates_payload = []
        for t in templates_db:
            req_fields = []
            if t.required_fields:
                rf = [f.strip() for f in t.required_fields.split(",") if f.strip()]
                mappings = {}
                if t.semantic_mappings:
                    mappings = json.loads(t.semantic_mappings)
                for f in rf:
                    semantic_key = mappings.get(f, f)
                    req_fields.append({"display": f, "semantic": semantic_key})
            
            templates_payload.append({
                "name": t.template_name,
                "required_fields": req_fields
            })
            
        # Gather supplier knowledge
        structured_aliases = None
        if supplier.structured_aliases:
            structured_aliases = json.loads(supplier.structured_aliases)
            
        extraction_notes = supplier.extraction_notes
        
        # Gather few shot
        examples_db = db.query(SupplierExtractionExample).filter(
            SupplierExtractionExample.supplier_id == supplier.id,
            SupplierExtractionExample.approved_by_user == True
        ).order_by(SupplierExtractionExample.created_at.desc()).limit(20).all()
        
        few_shot_examples = []
        for ex in examples_db:
            ex_dict = {
                "raw_description": ex.raw_description,
                "normalized_description": ex.normalized_description,
                "suggested_billing_item": ex.billing_item,
            }
            if ex.attributes:
                ex_dict["attributes"] = json.loads(ex.attributes)
            few_shot_examples.append(ex_dict)
            
        provider = GeminiProvider()
        job.provider_version = provider.provider_version
        job.status = "PROCESSING"
        db.commit()
        
        result = await provider.extract_invoice(
            file_path=file_path,
            mime_type=mime_type,
            templates=templates_payload,
            structured_aliases=structured_aliases,
            extraction_notes=extraction_notes,
            few_shot_examples=few_shot_examples
        )
        
        # Update Job
        job.status = "COMPLETED"
        job.completed_at = datetime.utcnow()
        job.tokens_used = result.tokens_used
        job.cost = result.cost
        job.input_pages = result.input_pages
        job.raw_provider_response = result.raw_provider_response
        
        duration = (job.completed_at - job.started_at).total_seconds()
        print(f"\n[🚀 {provider.provider_name} EXTRACTION COMPLETED]")
        print(f"   Model: {job.provider_version}")
        print(f"   Rows Extracted: {len(result.items)}")
        print(f"   Tokens Used: {result.tokens_used}")
        print(f"   Duration: {duration:.2f}s\n")
        
        preferred_template_id = None
        if supplier.invoice_profile:
            try:
                prof = json.loads(supplier.invoice_profile)
                preferred_template_id = prof.get("preferred_template_id")
            except:
                pass
        
        # Insert ReceivingItems
        for idx, item in enumerate(result.items):
            r_item = ReceivingItem(
                session_id=session_id,
                template_id=preferred_template_id,
                bill_row_number=idx + 1,
                raw_description=item.raw_description,
                normalized_description=item.normalized_description,
                billing_item=item.suggested_billing_item,
                supplier_product_code=item.supplier_product_code,
                hsn_code=item.hsn_code,
                expected_qty=item.quantity,
                unit=item.unit,
                purchase_rate=item.purchase_rate,
                mrp=item.mrp,
                extracted_attributes=json.dumps(item.attributes),
                source_provenance=json.dumps({k: v.model_dump() for k, v in item.provenance.items()}),
                extraction_confidence=0.0 
            )
            db.add(r_item)
            
        db.commit()
        
    except Exception as e:
        if job:
            job.status = "FAILED"
            job.error = str(e)
            job.completed_at = datetime.utcnow()
            db.commit()
    finally:
        db.close()
