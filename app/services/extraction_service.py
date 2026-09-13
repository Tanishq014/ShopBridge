import json
import uuid
import time
from datetime import datetime, timezone
from sqlalchemy.orm import Session
from fastapi import BackgroundTasks

from app.models import ExtractionJob, ReceivingSession, ReceivingItem, Supplier, TemplateMaster, SupplierExtractionExample
from app.extraction.gemini_provider import GeminiProvider

def start_extraction_job(
    db: Session,
    session_id: int,
    file_paths: list[str],
    mime_type: str,
    background_tasks: BackgroundTasks
) -> ExtractionJob:
    # 1. Create the ExtractionJob in DB
    job = ExtractionJob(
        session_id=session_id,
        provider="Gemini",
        status="PENDING",
        started_at=datetime.now(timezone.utc).replace(tzinfo=None)
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    # 2. Enqueue the background task
    background_tasks.add_task(
        _run_extraction_task,
        job_id=job.id,
        session_id=session_id,
        file_paths=file_paths,
        mime_type=mime_type
    )
    
    return job

def _run_extraction_task(job_id: int, session_id: int, file_paths: list[str], mime_type: str):
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
        
        result = provider.extract_invoice(
            file_paths=file_paths,
            mime_type=mime_type,
            templates=templates_payload,
            structured_aliases=structured_aliases,
            extraction_notes=extraction_notes,
            few_shot_examples=few_shot_examples
        )
        
        # Update Job
        job.status = "COMPLETED"
        job.completed_at = datetime.now(timezone.utc).replace(tzinfo=None)
        job.tokens_used = result.tokens_used
        job.cost = result.cost
        job.input_pages = result.input_pages
        job.raw_provider_response = result.raw_provider_response
        
        duration = (job.completed_at - job.started_at).total_seconds() if job.started_at else 0.0
        row_count = 0
        if result.document:
            for page in result.document.pages:
                row_count += len(page.rows)
                
        print(f"\n[🚀 {provider.provider_name} EXTRACTION COMPLETED]")
        print(f"   Model: {job.provider_version}")
        print(f"   Rows Extracted: {row_count}")
        print(f"   Tokens Used: {result.tokens_used} (Input: {result.prompt_tokens}, Output: {result.candidate_tokens})")
        print(f"   Duration: {duration:.2f}s\n")
        
        preferred_template_id = None
        if supplier.invoice_profile:
            try:
                prof = json.loads(supplier.invoice_profile)
                preferred_template_id = prof.get("preferred_template_id")
            except:
                pass
        
        # Insert ReceivingItems
        from sqlalchemy import func
        max_row = db.query(func.max(ReceivingItem.bill_row_number)).filter(ReceivingItem.session_id == session_id).scalar() or 0
        max_page = db.query(func.max(ReceivingItem.source_page_number)).filter(ReceivingItem.session_id == session_id).scalar() or 0
        
        bill_row_idx = max_row + 1
        if result.document:
            for page in result.document.pages:
                current_page_number = max_page + page.page_number
                for row in page.rows:
                    
                    def safe_val(field):
                        if field is None: return None
                        v = field.value if hasattr(field, 'value') else field
                        if isinstance(v, float) and v.is_integer():
                            return int(v)
                        return v
                        
                    def safe_float(val):
                        if val is None: return None
                        if isinstance(val, (int, float)): return float(val)
                        if isinstance(val, str):
                            try:
                                return float(val.replace(',', ''))
                            except ValueError:
                                pass
                        return None
                        
                    custom_attrs = {}
                    for key in ["brand", "size", "color", "article_number", "batch_number", "expiry", "serial_number", "manufacturer", "design", "model_no", "discount"]:
                        val = getattr(row, key, None)
                        if val is not None and safe_val(val) is not None:
                            custom_attrs[key] = safe_val(val)

                    r_item = ReceivingItem(
                        session_id=session_id,
                        template_id=preferred_template_id,
                        bill_row_number=bill_row_idx,
                        source_row_number=str(safe_val(row.source_row_number)) if safe_val(row.source_row_number) is not None else None,
                        source_row_inferred=False, 
                        source_page_number=current_page_number,
                        raw_description=str(safe_val(row.raw_description)) if safe_val(row.raw_description) is not None else None,
                        normalized_description=str(safe_val(row.normalized_description)) if safe_val(row.normalized_description) is not None else (str(safe_val(row.raw_description)) if safe_val(row.raw_description) is not None else None),
                        billing_item=str(safe_val(row.suggested_billing_item)) if safe_val(row.suggested_billing_item) is not None else None,
                        supplier_product_code=str(safe_val(row.supplier_product_code)) if safe_val(row.supplier_product_code) is not None else None,
                        hsn_code=str(safe_val(row.hsn_code)) if safe_val(row.hsn_code) is not None else None,
                        expected_qty=safe_float(safe_val(row.quantity)),
                        unit=str(safe_val(row.unit)) if safe_val(row.unit) is not None else None,
                        purchase_rate=safe_float(safe_val(row.purchase_rate)),
                        mrp=safe_float(safe_val(row.mrp)),
                        line_amount=safe_float(safe_val(row.line_amount)),
                        extracted_attributes=json.dumps(custom_attrs),
                        extracted_payload=row.model_dump_json(), # Full Document AI row JSON
                        extraction_confidence=0.0 
                    )
                    db.add(r_item)
                    bill_row_idx += 1
            
        db.commit()
        
    except Exception as e:
        if job:
            db.rollback()
            job.status = "FAILED"
            job.error = str(e)
            job.completed_at = datetime.now(timezone.utc).replace(tzinfo=None)
            db.commit()
    finally:
        db.close()
        for p in file_paths:
            try:
                import os
                if os.path.exists(p):
                    os.remove(p)
            except Exception:
                pass
