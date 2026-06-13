"""Gemini Voice Fill service.

Sends audio or transcript plus template context to the Gemini API and returns
a validated multi-item JSON payload using Pydantic structured outputs.
"""
from __future__ import annotations

import json
import logging

from google import genai
from google.genai import types
from pydantic import BaseModel, Field, create_model

from app.config import (
    GEMINI_API_KEY,
    GEMINI_VOICE_MODEL,
    GEMINI_VOICE_FALLBACK_MODEL,
)

logger = logging.getLogger(__name__)



def _call_gemini_structured(
    model_name: str,
    parts: list,
    DynamicResponseSchema: type[BaseModel]
) -> dict:
    client = genai.Client(api_key=GEMINI_API_KEY)
    response = client.models.generate_content(
        model=model_name,
        contents=parts,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=DynamicResponseSchema,
            temperature=0.0
        )
    )
    data = json.loads(response.text)
    data["ok"] = True
    return data

def parse_stock_audio(
    *,
    audio_bytes: bytes | None = None,
    audio_mime: str = "audio/webm",
    transcript: str = "",
    template_id: str = "",
    template_name: str = "",
    template_fields: list | None = None,
    existing_values: dict | None = None,
) -> dict:
    if not GEMINI_API_KEY:
        logger.warning("GEMINI_API_KEY is not set — returning error response.")
        return {"ok": False, "error": "Gemini API key is not configured."}

    fields_def = {}
    
    # Always explicitly ask for family_name (Billing Item)
    fields_def["family_name"] = (
        str, 
        Field(default="", description="The Billing Item Name or Family Name. Extract if mentioned.")
    )
    
    for f in (template_fields or []):
        key = f.get("key")
        if not key: continue
        label = f.get("label", key)
        mode = f.get("voice_mode", "normal")
        
        if mode == "manual_only":
            continue
            
        desc = f"The {label}. Extract final intended value. Be flexible."
        if mode == "code_review":
            desc += " Only fill if explicitly spoken as a code/article marker."
            
        fields_def[key] = (
            str, 
            Field(default="", description=desc)
        )

    ItemFields = create_model("ItemFields", **fields_def)
    
    class ParsedItem(BaseModel):
        row_no: int
        fields: ItemFields
        needs_review_fields: list[str] = Field(description="List of keys that Gemini guessed or is unsure about, or fields that act as codes.", default_factory=list)
        missing_required_fields: list[str] = Field(description="List of keys of required fields that are missing.", default_factory=list)
        conflicts: list[str] = Field(description="List of conflict messages if the user says contradictory things.", default_factory=list)
        unmatched_text: list[str] = Field(description="List of text chunks like barcodes or things that don't belong to any field.", default_factory=list)
        notes: list[str] = Field(description="Any additional notes for the user.", default_factory=list)
        print_requested: bool = Field(description="True ONLY if the user clearly says 'print', 'print karo', 'nikal do'. Do NOT set for quantities like '5 piece' or 'qty 5'.", default=False)

    class GeminiVoiceResponse(BaseModel):
        raw_transcript: str = Field(description="The raw Hinglish transcript of what was spoken")
        items: list[ParsedItem] = Field(description="List of parsed items. If user mentions multiple items, separate them.")

    active_field_names = [f.get("label", f.get("key")) for f in (template_fields or []) if f.get("voice_mode") != "manual_only"]
    if "Billing Item" not in active_field_names and "family_name" not in active_field_names:
        active_field_names.append("Billing Item")
    active_fields_str = ", ".join(active_field_names)

    prompt = (
        "You are an expert AI assistant for an Indian retail shop. Your job is to deeply understand the context of a shopkeeper dictating product details for barcode printing.\n"
        "Listen to the audio or read the transcript and extract the requested fields based on the whole context of what was said.\n"
        f"The user is trying to fill a template named '{template_name}'.\n"
        f"The specific fields we are listening for are: {active_fields_str}.\n\n"
        "Instructions:\n"
        "- Return JSON matching the schema exactly. No markdown formatting, just raw JSON.\n"
        "- Be extremely flexible in understanding conversational Hindi/Hinglish.\n"
        "- Extract ONLY information actually present in the audio/transcript. Do NOT hallucinate data or use examples from this prompt.\n"
        "- If the input is just greetings (like 'hello'), noise, or empty, return empty fields.\n"
        "- Understand the whole context. For example, 'rate 10% discount krke' means you should calculate or extract the final intended rate string.\n"
        "- Example of how to map (strictly an example, do not use these values): If user says 'design XYZ', map 'XYZ' to design field.\n"
        "- Do NOT set print_requested for quantities like '5 piece', 'qty 5', '5 pcs'. Those are quantity/field values only.\n"
        "- `print_requested = true` ONLY if dad clearly says: 'print', 'print karo', 'print kar do', 'label print', 'label nikal do', 'nikal do', 'nikalna hai', 'print now'.\n"
        "- Barcode-like fields (barcode, qr, ean, upc) must NEVER be filled. If spoken, put them in unmatched_text or notes.\n"
        "- The 'code' or 'coded_price' field is explicitly ONLY letters. If the audio does not contain letters for it, leave it completely empty.\n"
        "- If a field is not mentioned, leave its value as an empty string.\n"
        "- Separate multiple items if the user explicitly lists multiple items.\n"
    )
    
    parts = []
    if audio_bytes:
        parts.append(types.Part.from_bytes(data=audio_bytes, mime_type=audio_mime or "audio/webm"))
    if transcript:
        prompt += f"\nTranscript:\n{transcript}\n"
    
    parts.append(prompt)

    try:
        return _call_gemini_structured(GEMINI_VOICE_MODEL, parts, GeminiVoiceResponse)
    except Exception as exc:
        if "404" in str(exc).lower() or "not found" in str(exc).lower():
            logger.warning("Primary voice model unavailable, falling back.")
            try:
                fallback_data = _call_gemini_structured(GEMINI_VOICE_FALLBACK_MODEL, parts, GeminiVoiceResponse)
                fallback_data["model_warning"] = "Primary model unavailable, used fallback."
                return fallback_data
            except Exception as fallback_exc:
                logger.exception("Fallback voice model also failed.")
                return {"ok": False, "error": str(fallback_exc)}
        
        logger.exception("Gemini structured parsing failed.")
        return {"ok": False, "error": str(exc)}

