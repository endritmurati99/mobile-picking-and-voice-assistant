"""
Voice-Endpoints: STT über Vosk + Intent-Erkennung.

ARCHITEKTUR:
- STT: Audio → Vosk-WebSocket → Transkript (lokal, kein Cloud)
- Intent: Transkript → intent_engine.recognize_intent() → strukturiertes Ergebnis
- TTS: Läuft im Browser (SpeechSynthesis) — kein Backend-Endpoint nötig

iOS Safari: SpeechRecognition funktioniert NICHT im PWA-Standalone-Modus.
Daher immer Server-Side STT mit Vosk.
"""
import logging
from fastapi import APIRouter, UploadFile, File, Form, HTTPException

from app.services import vosk_client
from app.services.intent_engine import recognize_intent, PickingContext

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/voice/recognize")
async def recognize_speech(
    audio: UploadFile = File(...),
    context: str = Form(default="awaiting_command"),
):
    """
    Audio-Blob empfangen, an Vosk-Server weiterleiten, Intent zurückgeben.

    context: PickingContext-Wert ('idle', 'awaiting_location_check',
             'awaiting_quantity_confirm', 'awaiting_command')

    Gibt zurück: {text, intent, value, confidence}
    """
    audio_bytes = await audio.read()
    if not audio_bytes:
        raise HTTPException(status_code=400, detail="Leere Audio-Datei")

    # Transkription über Vosk (WebSocket, lokaler Docker-Container)
    text = await vosk_client.transcribe_audio(audio_bytes)

    if not text:
        return {
            "text": "",
            "intent": "unknown",
            "value": None,
            "confidence": 0.0,
        }

    # Picking-Kontext für kontextabhängiges Intent-Matching
    try:
        ctx = PickingContext(context)
    except ValueError:
        ctx = PickingContext.AWAITING_COMMAND

    intent = recognize_intent(text, ctx)

    logger.info(f"STT: '{text}' → intent={intent.action} (conf={intent.confidence})")

    return {
        "text": intent.raw_text,
        "intent": intent.action,
        "value": intent.value,
        "confidence": intent.confidence,
    }
