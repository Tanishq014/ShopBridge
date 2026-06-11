"""Voice Fill route — POST /voice/parse-stock-audio.

Accepts multipart/form-data with:
    audio               — binary audio blob (optional if transcript provided)
    template_id         — selected template ID
    template_name       — selected template display name
    template_fields_json — JSON array of field metadata (key, label, required,
                           aliases, voice_mode). Never includes coded-price map.
    existing_values_json — JSON object of current form field values
    transcript          — typed fallback text (optional if audio provided)

Returns application/json.
Never writes audio to disk.
"""
from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Form, HTTPException, UploadFile, File
from fastapi.responses import JSONResponse

from app.services import gemini_voice_service

logger = logging.getLogger(__name__)

router = APIRouter()

ALLOWED_AUDIO_MIME_TYPES = {
    "audio/webm",
    "audio/ogg",
    "audio/wav",
    "audio/mpeg",
    "audio/mp3",
    "audio/mp4",
    "audio/m4a",
}

@router.post("/voice/parse-stock-audio")
async def parse_stock_audio(
    audio: UploadFile | None = File(default=None),
    template_id: str = Form(default=""),
    template_name: str = Form(default=""),
    template_fields_json: str = Form(default="[]"),
    existing_values_json: str = Form(default="{}"),
    transcript: str = Form(default=""),
) -> JSONResponse:
    """Parse item details from voice audio or typed transcript using Gemini."""

    # --- Validate: need audio or transcript ---
    audio_bytes: bytes | None = None
    audio_mime = "audio/webm"

    if audio is not None and audio.filename:
        audio_mime = audio.content_type or "audio/webm"
        if audio_mime not in ALLOWED_AUDIO_MIME_TYPES and not audio_mime.startswith("audio/"):
            raise HTTPException(
                status_code=415,
                detail=f"Unsupported audio type: {audio_mime}",
            )
            
        audio_bytes = await audio.read()
        
        if len(audio_bytes) > 5 * 1024 * 1024:
            raise HTTPException(
                status_code=413,
                detail="Audio file too large. Maximum size is 5MB.",
            )
            
        if not audio_bytes:
            audio_bytes = None

    if not audio_bytes and not transcript.strip():
        raise HTTPException(
            status_code=422,
            detail="Provide either an audio recording or a typed transcript.",
        )

    # --- Parse JSON fields ---
    try:
        template_fields: list = json.loads(template_fields_json or "[]")
        if not isinstance(template_fields, list):
            template_fields = []
    except (json.JSONDecodeError, TypeError):
        template_fields = []

    try:
        existing_values: dict = json.loads(existing_values_json or "{}")
        if not isinstance(existing_values, dict):
            existing_values = {}
    except (json.JSONDecodeError, TypeError):
        existing_values = {}



    # --- Call service ---
    try:
        result = gemini_voice_service.parse_stock_audio(
            audio_bytes=audio_bytes,
            audio_mime=audio_mime,
            transcript=transcript.strip(),
            template_id=template_id,
            template_name=template_name,
            template_fields=template_fields,
            existing_values=existing_values,
        )
    except Exception as exc:
        logger.exception("Unexpected error in voice parse route.")
        return JSONResponse(
            status_code=500,
            content={"ok": False, "error": f"Internal server error: {exc}"},
        )

    if not result.get("ok"):
        return JSONResponse(
            status_code=422,
            content=result,
        )

    return JSONResponse(content=result)
