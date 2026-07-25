"""Lokaler LLM-Fallback fuer die Voice-Intent-Erkennung (Ollama).

Wird nur gerufen, wenn die deterministische Erkennung nichts Sicheres liefert.
Jeder Fehler/Timeout/ungueltige Antwort => ok=False, damit der Aufrufer sauber
auf das deterministische Ergebnis zurueckfaellt.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass

import httpx

from app.config import settings
from app.services.intent_engine import EXTERNAL_INTENT_LABELS

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = (
    "Du ordnest eine deutsche Sprachaeusserung eines Lager-Kommissionierers genau "
    "einem Befehl zu. Erlaubte Befehle: "
    "confirm (Position bestaetigen), confirm_all (ganzen Auftrag buchen), "
    "next (naechste Position), previous (zurueck), next_order (naechster Auftrag), "
    "problem (Stoerung/Fehler melden), photo (Foto), pause, done (fertig), "
    "whats_next (was jetzt/was picken), where (wo/welcher Platz), "
    "how_many_left (wie viele noch), status, repeat (wiederholen), help. "
    "Bei Verneinung (nicht, kein, nein) niemals confirm. Wenn unklar: unknown. "
    'Antworte ausschliesslich mit JSON {"intent": <befehl|unknown>, "confidence": <0..1>}.'
)


@dataclass(frozen=True)
class VoiceIntentResult:
    ok: bool
    model: str
    intent: str | None = None
    confidence: float | None = None


class VoiceIntentClassifier:
    def __init__(
        self,
        *,
        endpoint: str,
        model: str,
        timeout_ms: int = 4000,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._endpoint = endpoint.rstrip("/")
        self._model = model
        seconds = max(1.0, timeout_ms / 1000.0)
        self._timeout = httpx.Timeout(connect=3.0, read=seconds, write=5.0, pool=3.0)
        self._transport = transport

    async def classify(self, text: str) -> VoiceIntentResult:
        payload = {
            "model": self._model,
            "stream": False,
            "format": "json",
            "options": {"temperature": 0},
            "messages": [
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": (text or "").strip()},
            ],
        }
        try:
            async with httpx.AsyncClient(
                timeout=self._timeout, transport=self._transport
            ) as client:
                resp = await client.post(f"{self._endpoint}/api/chat", json=payload)
            resp.raise_for_status()
            content = resp.json().get("message", {}).get("content")
            return self._parse(content)
        except Exception as exc:  # noqa: BLE001 - jeder Fehler => Fallback
            logger.warning(
                json.dumps({"event_type": "voice_intent_llm_failed", "error": str(exc)})
            )
            return VoiceIntentResult(ok=False, model=self._model)

    def _parse(self, content: str | None) -> VoiceIntentResult:
        if not content or not isinstance(content, str):
            return VoiceIntentResult(ok=False, model=self._model)
        try:
            parsed = json.loads(content)
        except (TypeError, ValueError):
            return VoiceIntentResult(ok=False, model=self._model)
        if not isinstance(parsed, dict):
            return VoiceIntentResult(ok=False, model=self._model)
        intent = str(parsed.get("intent", "")).strip().lower()
        if intent not in EXTERNAL_INTENT_LABELS:
            return VoiceIntentResult(ok=False, model=self._model)
        try:
            confidence = max(0.0, min(1.0, round(float(parsed.get("confidence")), 2)))
        except (TypeError, ValueError):
            return VoiceIntentResult(ok=False, model=self._model)
        return VoiceIntentResult(
            ok=True, model=self._model, intent=intent, confidence=confidence
        )


_classifier: VoiceIntentClassifier | None = None


def get_classifier() -> VoiceIntentClassifier:
    global _classifier
    if _classifier is None:
        _classifier = VoiceIntentClassifier(
            endpoint=settings.llm_endpoint,
            model=settings.llm_voice_model,
            timeout_ms=settings.llm_voice_timeout_ms,
        )
    return _classifier
