import sys
import os
import json
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from app.db import SessionLocal
from app.models import ReceivingSession, TemplateMaster, SupplierExtractionExample

def dump_payload():
    db = SessionLocal()
    try:
        # Get the latest session
        session = db.query(ReceivingSession).order_by(ReceivingSession.id.desc()).first()
        if not session:
            print("No receiving sessions found.")
            return

        supplier = session.supplier
        print(f"--- DUMP FOR SUPPLIER: {supplier.name} (Session {session.id}) ---\n")

        # 1. Templates
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
        
        from app.extraction.vocabulary import VOCABULARY_V1
        
        system_instruction = (
            "You are an expert logistics data extractor. Your job is ONLY to extract text directly from the invoice into semantic fields. "
            f"The extraction vocabulary is strictly limited to the following fields: {json.dumps(VOCABULARY_V1)}\n\n"
        )
        
        structured_aliases = None
        if supplier.structured_aliases:
            structured_aliases = json.loads(supplier.structured_aliases)
            
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

        prompt_parts = []
        prompt_parts.append("The system possesses the following label templates, indicating what kind of products are generally received and the semantic fields they map to:\n")
        prompt_parts.append(json.dumps(templates_payload, indent=2))
        
        if supplier.extraction_notes:
            prompt_parts.append(f"\n\nSupplier Specific Instructions:\n{supplier.extraction_notes}")
            
        if structured_aliases:
            prompt_parts.append(f"\n\nSupplier Specific Column Aliases:\n{json.dumps(structured_aliases, indent=2)}")

        if few_shot_examples and len(few_shot_examples) > 0:
            prompt_parts.append(f"\n\nHere are some previously verified successful extractions from this supplier to use as examples:\n{json.dumps(few_shot_examples, indent=2)}")

        prompt_parts.append("\n\nPlease extract all line items from the attached invoice. Provide field-level confidence scores (0.0 to 1.0) and provenance for each extracted field (source text and column name).")

        prompt = "\n".join(prompt_parts)
        
        print("=== SYSTEM INSTRUCTION ===")
        print(system_instruction)
        print("\n=== USER PROMPT ===")
        print(prompt)

    finally:
        db.close()

if __name__ == "__main__":
    dump_payload()
