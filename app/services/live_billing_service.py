"""Live voice billing service interfacing FastAPI with Gemini 3.8 Live."""
from __future__ import annotations

import asyncio
from decimal import Decimal
import json
import logging
from typing import Any

from fastapi import WebSocket, WebSocketDisconnect
from google import genai
from google.genai import types

from app.config import GEMINI_API_KEY
from app.schemas_voice import CartAction
from app.services.in_memory_cart_service import (
    InMemoryCartService,
    DEFAULT_CATALOGUE,
    get_or_create_cart,
)

logger = logging.getLogger(__name__)

# Fallback models in priority order
LIVE_MODELS = [
    "gemini-3.8-live",
    "models/gemini-3.8-live",
    "models/gemini-3.1-flash-live-preview",
]

# Supported high-fidelity prebuilt voices
LIVE_VOICES = ["Aoede", "Puck", "Charon", "Kore", "Fenrir"]
DEFAULT_VOICE = "Aoede"


def build_system_instruction(catalogue_text: str, existing_cart_text: str = "") -> str:
    cart_section = ""
    if existing_cart_text:
        cart_section = f"""
CURRENT BILL / ACTIVE CART STATE (Session Continuity):
{existing_cart_text}
(This bill was already on the counter before this connection. Keep building upon it unless Dad asks to remove or clear items.)
"""

    return f"""You are the ShopBridge real-time voice billing assistant for Balaji Cosmetics retail shop.
You are actively listening to the shopkeeper (Dad) who speaks in Hindi, Hinglish, or English while wearing earphones.
{cart_section}
CATALOGUE (Shop Inventory):
{catalogue_text}

============================================================
CRITICAL INTENT RULE: CONVERSATION vs BILLING MUTATION
============================================================
You must strictly distinguish between CONVERSATIONAL CHATTER and EXPLICIT BILLING ACTIONS.

1. CONVERSATIONAL SPEECH / QUESTIONS / GREETINGS / NOISE (STRICT NO-TOOL ZONE):
   - When Dad asks a question, checks readiness, pauses, greets, or makes casual remarks, DO NOT CALL `processCartCommand`!
   - NEVER mutate the cart on conversational words, questions, or noise!
   - Specific Conversational Triggers & Natural Spoken Responses:
     * Dad asks: "बोलूं आइटम?" / "बोलूं?" / "शुरू करें?" / "आइटम बोलूं?" (Asking permission to start dictating)
       -> Spoken reply: "हाँ Dad बोलिए, सुन रहा हूँ।" (DO NOT CALL ANY TOOL! DO NOT ADD ANYTHING!)
     * Dad says: "Hello hello" / "नमस्ते" / "हेलो" (Greeting)
       -> Spoken reply: "हेलो Dad! बोलिए क्या ऐड करना है?" (NO TOOL CALL!)
     * Dad asks: "सुन रहे हो?" / "आवाज़ आ रही है?" / "रेडी हो?" (Readiness check)
       -> Spoken reply: "हाँ Dad, बिल्कुल सुन रहा हूँ, बोलिए।" (NO TOOL CALL!)
     * Dad says: "एक मिनट रुको" / "एक सेकंड" / "ग्राहक आया है" (Pausing)
       -> Spoken reply: "जी ठीक है, मैं रुका हूँ।" (NO TOOL CALL!)
     * Dad says filler words: "हाँ", "अच्छा", "ठीक है", "हम्म"
       -> Acknowledge gently (e.g. "हाँ जी", "बोलिए") (NO TOOL CALL!)
     * Dad asks about the bill: "टोटल कितना हुआ?" / "कितने आइटम हुए?"
       -> Answer concisely in spoken voice with current total (e.g. "Total ₹120 हुआ है.") (NO TOOL CALL!)
     * Background noise, throat clearing, breathing, or indistinct garbled sounds (e.g. "por noite"):
       -> If Dad seemed to talk to you, ask: "माफ़ कीजिये, समझ नहीं आया, फिर से बोलिए।"

2. EXPLICIT BILLING ACTIONS (ONLY TIME TO CALL `processCartCommand`):
   - You MUST call `processCartCommand` ONLY when Dad explicitly dictates an item to add, change, remove, or clear!
   - MULTI-ITEM BILLING IN ONE BREATH:
     * Dad often dictates multiple items in one sentence (e.g. "2 राखी 20 वाली, 3 काजल 100 वाले, और 1 डव साबुन").
     * You MUST call `processCartCommand` for EACH individual item!
   - ADD:
     * Dad names a specific merchandise product (e.g. "2 राखी 20 वाली", "Lakmé का काजल 160 MRP और 100 selling price", "लक्स साबुन", "3 हैंकी 50 वाले").
     * If Dad names an item with rate/mrp or quantity, call `action_type="ADD"`.
     * If no quantity is spoken, default to 1.
   - UPDATE_PRICE (Price Negotiation & Rate Corrections):
     * When Dad changes or negotiates the price of an existing item (e.g. "काजल 90 का कर दो", "90 लगा लो", "रेट 90 करो"):
       Call `action_type="UPDATE_PRICE"`, product_id or line_id, and rate=90 (and mrp if spoken).
       This updates the selling rate of the existing line without creating duplicate lines!
   - REMOVE (Subtract vs Entire Line):
     * If Dad specifies a quantity to remove (e.g. "2 राखी हटा दो", "हैंकी में से 1 कम करो"):
       Call `action_type="REMOVE"`, product_id, and `quantity=2` (or 1). This SUBTRACTS that quantity from the line!
     * If Dad does not specify a quantity (e.g. "राखी हटा दो", "काजल कैंसिल करो"):
       Call `action_type="REMOVE"`, product_id, and `quantity=null`. This removes the entire line!
   - SET_QUANTITY:
     * If Dad says "राखी 5 कर दो" or "हैंकी 3 पीस करो":
       Call `action_type="SET_QUANTITY"`, product_id or line_id, and `quantity=5`.
     * If Dad also specifies a new rate (e.g. "राखी 5 कर दो 18 के भाव से"), include `rate=18`.
   - CLEAR:
     * If Dad says "बिल क्लियर कर दो", "सब हटा दो", or "नया बिल बनाओ":
       Call `action_type="CLEAR"`.

3. SHOP CHATTER & ADVICE vs ACTUAL BILLING:
   - Dad frequently advises customers on shades, quality, or prices (e.g. "ये वाटरप्रूफ है, 150 का आता है", "रेड शेड अच्छा लगेगा", "राजू अंदर से साबुन ले आओ", "खुले पैसे नहीं हैं").
   - Discussing an item, advising, or asking the customer questions is NOT a sale command!
   - ONLY call `processCartCommand` when Dad is clearly executing a sale/billing command for that customer.

4. COLLOQUIAL HINDI NUMBERS & SHOP TERMS:
   - Understand standard Indian retail terms effortlessly:
     * "एक दर्जन" = 12, "आधा दर्जन" = 6, "दो पीस" = 2.
     * "डेढ़ सौ" = 150, "ढाई सौ" = 250, "पौने दो सौ" = 175, "सवा सौ" = 125, "पचास" = 50, "बीस" = 20.

============================================================
PRODUCT MATCHING & APPROXIMATION RULES:
============================================================
1. Nearest Item Matching in Catalogue:
   - Dad names brands, specific items, or colloquial terms. Always approximate to the closest catalogue item:
     * "Lakmé ka kajal 160 MRP aur 100 selling price" (or "Lakme kajal") -> Match "Kajal" (or "Lakme"), product_id="T263", quantity=1, rate=100, mrp=160.
     * "Lux sabun" -> Match "Soap" (or "Lux Soap").
     * "2 rakhi 20 wali" -> Match "Rakhi", quantity=2, rate=20.
     * "3 hand soap MRP 60 rate 55" -> Match "Hand Soap", quantity=3, rate=55, mrp=60.
2. Generic "Cosmetics" Fallback Rule:
   - If Dad explicitly names an actual cosmetic/beauty product (e.g. "mascara", "foundation 150 ka", "hair serum 200 ka", "face wash 80", "bleach 60 ka") that has NO matching item or category in the catalogue:
     * Approximate to generic "Cosmetics" (product_id="T125") with Dad's specified rate and MRP.
   - STRICT PROHIBITION ON "COSMETICS":
     * NEVER fall back to "Cosmetics" on words like "item", "बोलूं आइटम?", "saman", "bill", questions, greetings, or indistinct speech!
     * If no actual beauty/retail product name or selling rate was stated, DO NOT ADD "Cosmetics"!

============================================================
CONVERSATIONAL STYLE & CONFIRMATIONS:
============================================================
- Confirmation when an item is updated must be ULTRA-BRIEF, natural, and friendly (3 to 6 words in Hindi/Hinglish):
  * "Kajal add kar diya."
  * "2 rakhi add ho gayi."
  * "Kajal 90 ka kar diya."
  * "Rakhi 5 kar di."
  * "2 rakhi kam kar di."
  * "Rakhi hata di."
  * "Bill clear kar diya."
- When Dad asks "total kitna hua?" or "kitne paise hue?", state the exact subtotal from the cart: "Total ₹120 hua hai."
- If Dad interrupts you mid-sentence, yield immediately and address his new instruction.
"""


def create_live_config(system_instruction_text: str, voice_name: str = DEFAULT_VOICE) -> types.LiveConnectConfig:
    chosen_voice = voice_name if voice_name in LIVE_VOICES else DEFAULT_VOICE
    tool = types.Tool(
        function_declarations=[
            types.FunctionDeclaration(
                name="processCartCommand",
                description=(
                    "Mutate the cart ONLY when Dad explicitly dictates a product or billing instruction "
                    "(add, set quantity, update price/rate, remove, clear). "
                    "NEVER call this tool for conversational questions (e.g. 'बोलूं आइटम?', 'sun rahe ho?'), "
                    "product inquiries/advice, greetings, pauses, filler words, or background noise."
                ),
                parameters_json_schema=CartAction.model_json_schema(),
                behavior=types.Behavior.BLOCKING,
            )
        ]
    )

    return types.LiveConnectConfig(
        response_modalities=[types.Modality.AUDIO],
        speech_config=types.SpeechConfig(
            voice_config=types.VoiceConfig(
                prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=chosen_voice)
            )
        ),
        system_instruction=types.Content(parts=[types.Part.from_text(text=system_instruction_text)]),
        tools=[tool],
        input_audio_transcription=types.AudioTranscriptionConfig(),
        output_audio_transcription=types.AudioTranscriptionConfig(),
        realtime_input_config=types.RealtimeInputConfig(
            turn_coverage="TURN_INCLUDES_ONLY_ACTIVITY",
        ),
    )


async def run_live_billing_session(
    websocket: WebSocket,
    session_id: str | None = None,
    voice_name: str = DEFAULT_VOICE,
) -> None:
    """Manages the full-duplex session between browser and Gemini 3.8 Live."""
    if not GEMINI_API_KEY:
        await websocket.send_json({"type": "ERROR", "message": "GEMINI_API_KEY is not configured."})
        await websocket.close()
        return

    session_id, cart_service = get_or_create_cart(session_id)
    client = genai.Client(api_key=GEMINI_API_KEY)

    catalogue_text = cart_service.get_catalogue_text()
    existing_cart_text = cart_service.get_cart_summary_text()
    system_instruction = build_system_instruction(catalogue_text, existing_cart_text)
    config = create_live_config(system_instruction, voice_name=voice_name)

    # Send initial cart snapshot (including any existing items on reconnect) to UI
    initial_snapshot = cart_service.get_snapshot()
    serialized_items = [
        {
            "line_id": item.line_id,
            "product_id": item.product_id,
            "name": item.name,
            "quantity": item.quantity,
            "rate": float(item.rate) if item.rate is not None else None,
            "mrp": float(item.mrp) if item.mrp is not None else None,
            "amount": float(item.amount),
        }
        for item in initial_snapshot.items
    ]
    await websocket.send_json({
        "type": "SESSION_STARTED",
        "session_id": session_id,
        "cart": {
            "items": serialized_items,
            "subtotal": float(initial_snapshot.subtotal),
        },
        "catalogue": [p.model_dump() for p in cart_service.get_catalogue_list()],
        "voice": voice_name,
    })

    model_to_use = LIVE_MODELS[0]

    try:
        logger.info("Connecting to Gemini Live with model: %s, voice: %s", model_to_use, voice_name)
        async with client.aio.live.connect(model=model_to_use, config=config) as session:
            logger.info("Connected to Gemini Live session successfully.")
            await websocket.send_json({"type": "LIVE_READY", "model": model_to_use, "voice": voice_name})
            stop_event = asyncio.Event()

            async def browser_to_gemini():
                """Reads 16kHz PCM audio from browser WebSocket and feeds Gemini."""
                try:
                    while not stop_event.is_set():
                        message = await websocket.receive()
                        if message.get("type") == "websocket.disconnect":
                            break
                        if "bytes" in message and message["bytes"]:
                            pcm_chunk = message["bytes"]
                            # Stream binary audio chunk as standard media blob (mediaChunks)
                            await session.send_realtime_input(
                                media=types.Blob(
                                    data=pcm_chunk,
                                    mime_type="audio/pcm;rate=16000",
                                )
                            )
                        elif "text" in message and message["text"]:
                            data = json.loads(message["text"])
                            msg_type = data.get("type")
                            if msg_type == "PING":
                                await websocket.send_json({"type": "PONG"})
                            elif msg_type == "CLEAR_CART":
                                snapshot = cart_service.execute_action(CartAction(action_type="CLEAR"))
                                await websocket.send_json({
                                    "type": "CART_UPDATED",
                                    "cart": {
                                        "items": [],
                                        "subtotal": 0.0,
                                    },
                                })
                except (asyncio.CancelledError, WebSocketDisconnect):
                    pass
                except Exception as e:
                    if not stop_event.is_set():
                        logger.error("Error in browser_to_gemini loop: %s", e)
                finally:
                    stop_event.set()

            async def gemini_to_browser():
                """Reads audio, transcripts, and tool calls from Gemini and pushes to UI across continuous turns."""
                try:
                    while not stop_event.is_set():
                        async for response in session.receive():
                            if stop_event.is_set():
                                break

                            # 1. Handle Transcriptions & Audio Chunks
                            if response.server_content:
                                content = response.server_content
                                if content.interrupted:
                                    logger.info("Gemini speech interrupted by user speech / barge-in.")
                                    await websocket.send_json({"type": "INTERRUPTED"})
                                    # Skip processing residual model_turn parts in this interrupted response
                                    continue

                                if content.input_transcription and content.input_transcription.text:
                                    await websocket.send_json({
                                        "type": "TRANSCRIPT_CHUNK",
                                        "sender": "user",
                                        "text": content.input_transcription.text,
                                    })

                                if content.output_transcription and content.output_transcription.text:
                                    await websocket.send_json({
                                        "type": "TRANSCRIPT_CHUNK",
                                        "sender": "assistant",
                                        "text": content.output_transcription.text,
                                    })

                                if content.turn_complete:
                                    await websocket.send_json({"type": "TURN_COMPLETE"})

                                if content.model_turn:
                                    for part in content.model_turn.parts:
                                        if part.inline_data and part.inline_data.data:
                                            # Forward raw 24kHz audio bytes directly to browser
                                            await websocket.send_bytes(part.inline_data.data)

                            # Handle token usage telemetry
                            if response.usage_metadata:
                                meta = response.usage_metadata
                                await websocket.send_json({
                                    "type": "USAGE_UPDATE",
                                    "tokens": {
                                        "total": meta.total_token_count or 0,
                                        "prompt": meta.prompt_token_count or 0,
                                        "response": meta.response_token_count or 0,
                                    },
                                })

                            # 2. Handle Tool Calls
                            if response.tool_call and response.tool_call.function_calls:
                                function_responses: list[types.FunctionResponse] = []
                                for fc in response.tool_call.function_calls:
                                    logger.info("Gemini Live tool call received: %s (id=%s) args=%s", fc.name, fc.id, fc.args)
                                    if fc.name == "processCartCommand":
                                        try:
                                            action = CartAction.model_validate(fc.args)
                                            snapshot = cart_service.execute_action(action)

                                            # Step 1: Push CART_UPDATED immediately to UI
                                            serialized_items = [
                                                {
                                                    "line_id": item.line_id,
                                                    "product_id": item.product_id,
                                                    "name": item.name,
                                                    "quantity": item.quantity,
                                                    "rate": float(item.rate) if item.rate is not None else None,
                                                    "mrp": float(item.mrp) if item.mrp is not None else None,
                                                    "amount": float(item.amount),
                                                }
                                                for item in snapshot.items
                                            ]
                                            await websocket.send_json({
                                                "type": "CART_UPDATED",
                                                "cart": {
                                                    "items": serialized_items,
                                                    "subtotal": float(snapshot.subtotal),
                                                },
                                            })

                                            result_data = {
                                                "status": "SUCCESS",
                                                "subtotal": str(snapshot.subtotal),
                                                "itemCount": len(snapshot.items),
                                            }
                                        except Exception as exc:
                                            logger.warning("Failed to execute processCartCommand: %s", exc)
                                            await websocket.send_json({
                                                "type": "TOOL_ERROR",
                                                "error": str(exc),
                                            })
                                            result_data = {"status": "ERROR", "message": str(exc)}

                                        function_responses.append(
                                            types.FunctionResponse(
                                                name=fc.name,
                                                id=fc.id,
                                                response={"result": result_data},
                                            )
                                        )

                                if function_responses:
                                    # Step 2: Send official SDK tool response back to Gemini
                                    await session.send_tool_response(function_responses=function_responses)

                except (asyncio.CancelledError, WebSocketDisconnect):
                    pass
                except Exception as e:
                    if not stop_event.is_set():
                        logger.error("Error in gemini_to_browser loop: %s", e)
                finally:
                    stop_event.set()

            # Run both streaming loops concurrently with clean cancellation
            tasks = [
                asyncio.create_task(browser_to_gemini()),
                asyncio.create_task(gemini_to_browser()),
            ]
            try:
                done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            finally:
                stop_event.set()
                for t in tasks:
                    if not t.done():
                        t.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)

    except (asyncio.CancelledError, WebSocketDisconnect):
        logger.info("Voice billing session closed cleanly.")
    except Exception as e:
        logger.error("Failed to maintain Gemini Live session: %s", e)
        try:
            await websocket.send_json({"type": "ERROR", "message": f"Gemini Live error: {str(e)}"})
        except Exception:
            pass
