import os
import json
import asyncio
import time
from typing import Any
from pydantic import BaseModel, Field
from dotenv import load_dotenv

load_dotenv()

from google import genai
from google.genai import types

from app.extraction.provider import (
    ExtractionProvider,
    ExtractionJobResult,
    ExtractedItem,
    ProvenanceInfo
)
from app.extraction.vocabulary import VOCABULARY_V1


class AIRawProvenance(BaseModel):
    source_text: str
    page: int | None = None
    bbox: list[int] | None = None
    source_column: str | None = None

class AttributePair(BaseModel):
    key: str
    value: str

class ConfidencePair(BaseModel):
    key: str
    score: float

class ProvenancePair(BaseModel):
    key: str
    provenance: AIRawProvenance

class AIExtractedItem(BaseModel):
    raw_description: str | None = None
    normalized_description: str | None = None
    suggested_billing_item: str | None = None
    supplier_product_code: str | None = None
    hsn_code: str | None = None
    quantity: float | None = None
    unit: str | None = None
    purchase_rate: float | None = None
    mrp: float | None = None
    attributes: list[AttributePair] = Field(default_factory=list)
    confidence: list[ConfidencePair] = Field(default_factory=list)
    provenance: list[ProvenancePair] = Field(default_factory=list)

class AIExtractionResponse(BaseModel):
    items: list[AIExtractedItem] = Field(default_factory=list)


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

    async def extract_invoice(
        self,
        file_path: str,
        mime_type: str,
        templates: list[dict[str, Any]],
        structured_aliases: dict[str, str] | None,
        extraction_notes: str | None,
        few_shot_examples: list[dict[str, Any]] | None
    ) -> ExtractionJobResult:
        start_time = time.time()
        
        # 1. Build the prompt
        system_instruction = (
            "You are an expert logistics data extractor. Your job is ONLY to extract text directly from the invoice into semantic fields. "
            f"The core extraction vocabulary is: {json.dumps(VOCABULARY_V1['core_fields'])}. "
            f"The known semantic attributes are: {json.dumps(VOCABULARY_V1['known_attributes'])}.\n\n"
            "Extract EVERYTHING you can confidently identify. Do not limit yourself to only fields explicitly requested by the template. "
            "Unknown product attributes should be placed into attributes using their original column names if no canonical semantic field exists. "
            "For 'normalized_description' and 'suggested_billing_item', strip away arbitrary supplier tokens (like 'N.1 DLX' or size/color codes) to create a clean, canonical POS product name. "
            "Never invent values."
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

        prompt_parts.append("\n\nPlease extract all line items from the attached invoice. Provide field-level confidence scores (0.0 to 1.0) and provenance for each extracted field (source text and column name).")

        prompt = "\n".join(prompt_parts)

        # 2. Upload the file to Gemini
        file_obj = self.client.files.upload(file=file_path, config={'mime_type': mime_type})

        try:
            # 3. Call the model with Structured Outputs (with retry logic)
            max_retries = 3
            base_delay = 2
            
            response = None
            for attempt in range(max_retries):
                try:
                    response = self.client.models.generate_content(
                        model=self.provider_version,
                        contents=[file_obj, prompt],
                        config=types.GenerateContentConfig(
                            system_instruction=system_instruction,
                            response_mime_type="application/json",
                            response_schema=AIExtractionResponse,
                            temperature=0.1,
                        ),
                    )
                    break
                except Exception as e:
                    if attempt == max_retries - 1:
                        raise e
                    err_str = str(e).lower()
                    if "503" in err_str or "429" in err_str or "unavailable" in err_str or "quota" in err_str:
                        await asyncio.sleep(base_delay * (2 ** attempt))
                    else:
                        raise e
            
            raw_response = response.text
            tokens_used = 0
            if response.usage_metadata:
                tokens_used = response.usage_metadata.total_token_count

            # Parse response
            ai_data = AIExtractionResponse.model_validate_json(raw_response)
            
            # Map to the core interface
            result_items = []
            for ai_item in ai_data.items:
                item = ExtractedItem(
                    raw_description=ai_item.raw_description,
                    normalized_description=ai_item.normalized_description,
                    suggested_billing_item=ai_item.suggested_billing_item,
                    supplier_product_code=ai_item.supplier_product_code,
                    hsn_code=ai_item.hsn_code,
                    quantity=ai_item.quantity,
                    unit=ai_item.unit,
                    purchase_rate=ai_item.purchase_rate,
                    mrp=ai_item.mrp,
                    attributes={attr.key: attr.value for attr in ai_item.attributes},
                    confidence={conf.key: conf.score for conf in ai_item.confidence},
                    review_required=False, # Backend business rules can override this later
                    provenance={prov.key: ProvenanceInfo(**prov.provenance.model_dump()) for prov in ai_item.provenance}
                )
                result_items.append(item)

            processing_time = time.time() - start_time
            
            return ExtractionJobResult(
                items=result_items,
                raw_provider_response=raw_response,
                tokens_used=tokens_used,
                cost=0.0, # Implement cost estimation if needed
                input_pages=1 # Would need a PDF parser to count properly
            )
            
        except Exception as e:
            # Re-raise or handle so the job tracks the error
            raise e
        finally:
            # Cleanup file
            try:
                self.client.files.delete(name=file_obj.name)
            except:
                pass
