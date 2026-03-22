"""Pydantic Models für Voice I/O."""
from pydantic import BaseModel
from typing import Optional


class VoiceRecognitionResponse(BaseModel):
    text: str
    intent: str
    value: Optional[str] = None
    confidence: float
    tts_response: Optional[str] = None


class TTSRequest(BaseModel):
    text: str
    lang: str = "de-DE"
