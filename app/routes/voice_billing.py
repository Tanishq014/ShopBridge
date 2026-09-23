import asyncio
import logging
from fastapi import APIRouter, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.config import TEMPLATES_DIR
from app.services.template_filters import register_template_filters
from app.services.live_billing_service import run_live_billing_session

logger = logging.getLogger(__name__)

router = APIRouter(tags=["voice-billing"])
templates = register_template_filters(Jinja2Templates(directory=str(TEMPLATES_DIR)))


@router.get("/pos/voice", response_class=HTMLResponse)
async def voice_billing_page(request: Request):
    """Renders the voice-first POS billing interface."""
    return templates.TemplateResponse(
        request,
        "voice_billing.html",
        {
            "request": request,
            "page_title": "Voice POS Billing - ShopBridge",
        },
    )


@router.websocket("/ws/voice-billing")
async def voice_billing_websocket(
    websocket: WebSocket,
    voice: str = "Aoede",
    session_id: str | None = None,
):
    """Full-duplex WebSocket endpoint bridging browser audio to Gemini 3.8 Live."""
    await websocket.accept()
    logger.info(
        "Voice billing WebSocket connection accepted from %s (voice=%s, session_id=%s)",
        websocket.client,
        voice,
        session_id,
    )
    try:
        await run_live_billing_session(websocket, session_id=session_id, voice_name=voice)
    except (asyncio.CancelledError, WebSocketDisconnect):
        logger.info("Voice billing WebSocket disconnected cleanly.")
    except Exception as e:
        logger.error("Unhandled error in voice billing session: %s", e)
    finally:
        logger.info("Voice billing WebSocket connection closed.")
