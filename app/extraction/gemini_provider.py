import os
import json
import asyncio
import time
from typing import Any
from pydantic import BaseModel, Field
from dotenv import load_dotenv
from PIL import Image

load_dotenv()

from google import genai
from google.genai import types

from app.extraction.provider import (
    ExtractionProvider,
    ExtractionJobResult,
    ExtractedDocument,
    ExtractedPage,
    ExtractedRow,
    GroundedField
)
from app.extraction.vocabulary import VOCABULARY_V1


class GeminiProvider(ExtractionProvider):
    def __init__(self):
        # Relies on GEMINI_API_KEY being set in the environment or .env
        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            raise ValueError("GEMINI_API_KEY not found in environment.")
        self.client = genai.Client(api_key=api_key)

    @property
    def provider_name(self) -> str:
        return "Gemini"

    @property
    def provider_version(self) -> str:
        return "gemini-3.6-flash"

    def extract_invoice(
        self,
        file_paths: list[str],
        mime_type: str,
        templates: list[dict[str, Any]],
        structured_aliases: dict[str, str] | None,
        extraction_notes: str | None,
        few_shot_examples: list[dict[str, Any]] | None
    ) -> ExtractionJobResult:
        start_time = time.time()
        
        # 1. Build the prompt
        ROW_SCHEMA = """
{
  "page_number": 1,
  "image_width": 1080,
  "image_height": 1440,
  "global_discounts": [37.0, 5.0],
  "global_taxes": [2.5, 2.5],
  "rows": [
    {
      "source_row_number": {"bbox": [338, 47, 349, 58], "value": "1"},
      "raw_description":   {"bbox": [338, 70, 350, 191], "value": "GIRLS CO-ORD SET"},
      "suggested_billing_item": "Co-Ord Set",
      "article_number":  {"bbox": [347, 393, 358, 423], "value": "6108"},
      "design":          {"bbox": [347, 431, 358, 468], "value": "25401"},
      "quantity":        {"bbox": [351, 546, 360, 580], "value": 18},
      "mrp":             {"bbox": [354, 672, 363, 719], "value": 795},
      "line_amount":     {"bbox": [352, 871, 363, 928], "value": 14310}
    }
  ]
}"""
        system_instruction = (
            "You are an expert Document AI data extractor. Your job is to extract rich structured data from the provided invoice pages. "
            f"The core extraction vocabulary is: {json.dumps(VOCABULARY_V1['core_fields'])}. "
            f"The known semantic attributes are: {json.dumps(VOCABULARY_V1['known_attributes'])}.\n\n"
            "Return EXACTLY ONE JSON object matching the schema shown in the example below. "
            "Do NOT wrap it in markdown code fences or add any extra text outside the JSON.\n\n"
            f"REQUIRED JSON SCHEMA EXAMPLE:\n{ROW_SCHEMA}\n\n"
            "Rules:\n"
            "- For EVERY extracted field (except `suggested_billing_item`), provide BOTH a `bbox` [ymin, xmin, ymax, xmax] normalised to 0-1000 AND a `value`. A bbox without a value is invalid — you MUST read and transcribe the actual number or text printed at that location.\n"
            "- ALL fields for a single printed row MUST be in exactly ONE object in `rows`. Never split a row across multiple objects.\n"
            "- Extract EVERY visible column for each row including quantity, mrp/price, purchase_rate, and line_amount. Never omit numeric columns.\n"
            "- For `purchase_rate` and `line_amount`, extract them EXACTLY as printed. Do NOT apply discounts.\n"
            "- DOZEN UNIT CONVERSION (DOZ / DOZEN / DZN / DZ): Wholesale invoices often bill products in dozens (unit: DOZ, DOZEN, DZN, DZ). The store manages inventory by single pieces (PCS). Whenever an item's unit or quantity is in dozens:\n"
            "  * Multiply quantity by 12 (e.g. printed qty 2 DOZ -> extract quantity value 24).\n"
            "  * Divide the per-dozen price / purchase_rate by 12 to get the single unit rate (e.g. printed rate 1200/doz -> extract purchase_rate value 100).\n"
            "  * If MRP is also printed per dozen, divide MRP by 12 as well.\n"
            "  * Set the extracted `unit` to 'PCS'.\n"
            "  * The `line_amount` remains the same total printed amount (e.g. 24 * 100 = 2400).\n"
            "- For `global_discounts` / `global_taxes`, extract bottom-of-page percentage numbers into those lists.\n"
            "- `suggested_billing_item`: ultra-short generic name (10-15 chars max), strip brands/sizes/genders.\n"
            "- OBEY any 'Supplier Specific Instructions' and 'Column Aliases' below absolutely, even if they contradict your understanding.\n"
            "- Omit fields that are genuinely absent; do not invent values (except `suggested_billing_item`).\n"
        )
        
        prompt_parts = []
        prompt_parts.append("The system possesses the following label templates, indicating what kind of products are generally received and the semantic fields they map to:\n")
        prompt_parts.append(json.dumps(templates, indent=2))
        
        if extraction_notes:
            prompt_parts.append(f"\n\nSupplier Specific Instructions:\n{extraction_notes}")
            
        if structured_aliases:
            prompt_parts.append(f"\n\nSupplier Specific Column Aliases:\n{json.dumps(structured_aliases, indent=2)}")

        if few_shot_examples and len(few_shot_examples) > 0:
            prompt_parts.append(f"\n\nHere are some previously verified successful extractions from this supplier to use as examples:\n{json.dumps(few_shot_examples, indent=2)}")

        prompt_parts.append("\n\nPlease extract all line items from the attached invoice.")

        prompt = "\n".join(prompt_parts)

        # 2. Extract page by page to avoid token limits
        file_objs = []
        page_dimensions = {} # 1-indexed page mapping
        print(f"\n[Gemini] Starting extraction for {len(file_paths)} pages...")
        for idx, fp in enumerate(file_paths):
            print(f"[Gemini] Uploading {fp} to Gemini...")
            file_objs.append(self.client.files.upload(file=fp, config={'mime_type': mime_type}))
            try:
                from PIL import Image
                with Image.open(fp) as img:
                    page_dimensions[idx + 1] = (img.width, img.height)
                    print(f"[Gemini] Loaded PIL dimensions for page {idx + 1}: {img.width}x{img.height}")
            except Exception as e:
                print(f"[Gemini] [WARN] Failed to load PIL dimensions for {fp}: {e}")
                page_dimensions[idx + 1] = (None, None)
            
        doc = ExtractedDocument(
            provider=self.provider_name,
            provider_model=self.provider_version,
            provider_version="v1",
            extracted_at="",
            pages=[]
        )
        
        from datetime import datetime, timezone
        doc.extracted_at = datetime.now(timezone.utc).replace(tzinfo=None).isoformat()
        import uuid
        
        tokens_used = 0
        prompt_tokens = 0
        candidate_tokens = 0
        raw_responses = []

        try:
            for page_idx, file_obj in enumerate(file_objs):
                page_num = page_idx + 1
                contents = [file_obj, prompt]
                
                print(f"[Gemini] Generating structured output for Page {page_num}/{len(file_objs)}...")
                
                # 3. Call the model with Structured Outputs for a SINGLE PAGE
                models_to_try = ["gemini-3.6-flash", "gemini-3.5-flash"]
                
                response = None
                for model_name in models_to_try:
                    print(f"[Gemini] Attempting extraction with model: {model_name}")
                    max_retries = 3
                    base_delay = 2
                    
                    model_success = False
                    for attempt in range(max_retries):
                        if attempt > 0:
                            print(f"[Gemini] [RETRY] Retry attempt {attempt + 1}/{max_retries} for page {page_num} on {model_name}...")
                            
                        try:
                            response = self.client.models.generate_content(
                                model=model_name,
                                contents=contents,
                                config=types.GenerateContentConfig(
                                    system_instruction=system_instruction,
                                    response_mime_type="application/json",
                                    temperature=0.1,
                                ),
                            )
                            model_success = True
                            break
                        except Exception as e:
                            err_str = str(e).lower()
                            if "503" in err_str or "429" in err_str or "unavailable" in err_str or "quota" in err_str or "not found" in err_str:
                                if attempt == max_retries - 1:
                                    print(f"[Gemini] [WARN] Model {model_name} failed all {max_retries} attempts. Last error: {e}")
                                else:
                                    print(f"[Gemini] [WARN] Error on page {page_num} with {model_name} ({e}), retrying in {base_delay * (2 ** attempt)}s...")
                                    time.sleep(base_delay * (2 ** attempt))
                            else:
                                print(f"[Gemini] [ERROR] Unrecoverable error on {model_name} page {page_num}: {e}")
                                break
                    
                    if model_success:
                        break
                        
                if not response or not getattr(response, 'text', None):
                    raise RuntimeError(f"All fallback models failed for page {page_num}. Please try again later.")
                
                raw_response = response.text
                raw_responses.append(raw_response)
                
                t_used = 0
                if response.usage_metadata:
                    t_used = response.usage_metadata.total_token_count
                    tokens_used += t_used
                    prompt_tokens += response.usage_metadata.prompt_token_count
                    candidate_tokens += response.usage_metadata.candidates_token_count

                print(f"[Gemini] [SUCCESS] Page {page_num} inference complete! Parsing JSON ({t_used} tokens)...")

                # Parse response into our Document AI model for this page
                try:
                    raw_text = raw_response.strip()
                    # Strip markdown code fences if present
                    if raw_text.startswith("```"):
                        raw_text = raw_text.split("\n", 1)[-1]
                        raw_text = raw_text.rsplit("```", 1)[0].strip()
                    page = ExtractedPage.model_validate_json(raw_text)
                    print(f"[Gemini] [SUCCESS] Page {page_num} successfully parsed! Extracted {len(page.rows)} rows.")
                except Exception as e:
                    # Save the partial payload for inspection
                    import os
                    debug_path = os.path.join(os.path.dirname(__file__), '..', '..', 'data', f'failed_payload_debug_page_{page_num}.json')
                    with open(debug_path, 'w', encoding='utf-8') as f:
                        f.write(raw_response)
                    print(f"[Gemini] [ERROR] JSON Parse Error on page {page_num}. Saved to {debug_path}.")
                    raise RuntimeError(f"Failed to parse JSON payload for page {page_num}. Saved raw payload to {debug_path}. Error: {e}")
                
                # Ensure page number is correct
                page.page_number = page_num
                
                # Inject PIL dimensions and assign row UUIDs
                if page_num in page_dimensions:
                    page.image_width = page_dimensions[page_num][0]
                    page.image_height = page_dimensions[page_num][1]
                
                doc.pages.append(page)
            
            processing_time = time.time() - start_time
            print(f"[Gemini] [SUCCESS] All pages processed successfully in {processing_time:.2f}s!")
            
            return ExtractionJobResult(
                document=doc,
                raw_provider_response="[" + ",".join(raw_responses) + "]",
                tokens_used=tokens_used,
                prompt_tokens=prompt_tokens,
                candidate_tokens=candidate_tokens,
                cost=0.0, # Implement cost estimation if needed
                input_pages=len(doc.pages)
            )
            
        except Exception as e:
            # Re-raise or handle so the job tracks the error
            raise e
        finally:
            # Cleanup file
            for file_obj in file_objs:
                try:
                    self.client.files.delete(name=file_obj.name)
                except Exception:
                    pass
