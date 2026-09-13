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
        return "gemini-3.5-flash"

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
        system_instruction = (
            "You are an expert Document AI data extractor. Your job is to extract rich structured data from the provided invoice pages. "
            f"The core extraction vocabulary is: {json.dumps(VOCABULARY_V1['core_fields'])}. "
            f"The known semantic attributes are: {json.dumps(VOCABULARY_V1['known_attributes'])}.\n\n"
            "Return the full hierarchical `ExtractedDocument` payload. For EVERY extracted field (except `suggested_billing_item`), you MUST provide a bounding box (`bbox`) BEFORE you transcribe the value.\n"
            "- Extract the `bbox` as [ymin, xmin, ymax, xmax] normalized to a 0-1000 scale.\n"
            "- After the bbox, extract the interpreted `value`. (If numeric, convert it. If string, clean it up / normalize it. E.g. 'HANUMAN .P' -> 'Hanuman P').\n"
            "- For `purchase_rate`, MUST extract the FINAL NET unit rate after all discounts. (e.g. if Rate is 180 and Discount is 15%, extract 153). You can calculate this by `line_amount / quantity`. IMPORTANT: Always verify the mathematics (`purchase_rate * quantity == line_amount`). If the math does not line up perfectly (e.g. due to OCR errors where an 8 looks like a 0), do NOT output the `purchase_rate` or `line_amount` for that line. Leave them blank if you are not absolutely sure.\n"
            "- For `suggested_billing_item`, infer a clean, ULTRA-SHORT product name (e.g., 'Bowl Set' or 'Coffee Mug'). This is printed on tiny POS receipts, so STRIP OUT all brands, article numbers, codes, colors, and sizes. STRICTLY limit it to 10-15 characters maximum.\n"
            "- If the row has data matching any of the optional fields (like `brand`, `mrp`, `size`, `color`, `expiry`, etc.), extract them directly into their respective JSON keys.\n\n"
            "For row metadata:\n"
            "- Extract the printed row number into `source_row_number` exactly as printed.\n"
            "Do not invent values (except for `suggested_billing_item` which MUST be inferred for every row). If a printed field is missing, omit it."
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
                print(f"[Gemini] ⚠️ Failed to load PIL dimensions for {fp}: {e}")
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
                max_retries = 3
                base_delay = 2
                
                response = None
                for attempt in range(max_retries):
                    if attempt > 0:
                        print(f"[Gemini] 🔄 Retry attempt {attempt + 1}/{max_retries} for page {page_num}...")
                        
                    try:
                        response = self.client.models.generate_content(
                            model=self.provider_version,
                            contents=contents,
                            config=types.GenerateContentConfig(
                                system_instruction=system_instruction,
                                response_mime_type="application/json",
                                response_schema=ExtractedPage,
                                temperature=0.1,
                            ),
                        )
                        break
                    except Exception as e:
                        if attempt == max_retries - 1:
                            print(f"[Gemini] ❌ Error extracting page {page_num} on final attempt: {e}")
                            raise e
                        err_str = str(e).lower()
                        if "503" in err_str or "429" in err_str or "unavailable" in err_str or "quota" in err_str:
                            print(f"[Gemini] ⚠️ Rate limit or unavailable error on page {page_num}, retrying in {base_delay * (2 ** attempt)}s...")
                            time.sleep(base_delay * (2 ** attempt))
                        else:
                            print(f"[Gemini] ❌ Error extracting page {page_num}: {e}")
                            raise e
                
                raw_response = response.text
                raw_responses.append(raw_response)
                
                t_used = 0
                if response.usage_metadata:
                    t_used = response.usage_metadata.total_token_count
                    tokens_used += t_used
                    prompt_tokens += response.usage_metadata.prompt_token_count
                    candidate_tokens += response.usage_metadata.candidates_token_count

                print(f"[Gemini] ✅ Page {page_num} inference complete! Parsing JSON ({t_used} tokens)...")

                # Parse response directly into our Document AI model for this page
                try:
                    page = ExtractedPage.model_validate_json(raw_response)
                    print(f"[Gemini] ✅ Page {page_num} successfully parsed! Extracted {len(page.rows)} rows.")
                except Exception as e:
                    # Save the partial payload for inspection
                    import os
                    debug_path = os.path.join(os.path.dirname(__file__), '..', '..', 'data', f'failed_payload_debug_page_{page_num}.json')
                    with open(debug_path, 'w', encoding='utf-8') as f:
                        f.write(raw_response)
                    print(f"[Gemini] ❌ JSON Parse Error on page {page_num}. Saved to {debug_path}.")
                    raise RuntimeError(f"Failed to parse JSON payload for page {page_num}. Saved raw payload to {debug_path}. Error: {e}")
                
                # Ensure page number is correct
                page.page_number = page_num
                
                # Inject PIL dimensions and assign row UUIDs
                if page_num in page_dimensions:
                    page.image_width = page_dimensions[page_num][0]
                    page.image_height = page_dimensions[page_num][1]
                
                doc.pages.append(page)
            
            processing_time = time.time() - start_time
            print(f"[Gemini] 🎉 All pages processed successfully in {processing_time:.2f}s!")
            
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
