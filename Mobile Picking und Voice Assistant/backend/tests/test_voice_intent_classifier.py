import json

import httpx
import pytest

from app.services.voice_intent_classifier import VoiceIntentClassifier, VoiceIntentResult


def _transport(handler):
    return httpx.MockTransport(handler)


def _ok_response(content: dict):
    def handler(request):
        return httpx.Response(200, json={"message": {"content": json.dumps(content)}})

    return _transport(handler)


@pytest.mark.asyncio
async def test_valid_intent_parsed():
    clf = VoiceIntentClassifier(
        endpoint="http://ollama:11434",
        model="m",
        transport=_ok_response({"intent": "next", "confidence": 0.8}),
    )
    result = await clf.classify("mach mal weiter irgendwie")
    assert result == VoiceIntentResult(ok=True, model="m", intent="next", confidence=0.8)


@pytest.mark.asyncio
async def test_unknown_label_is_not_ok():
    clf = VoiceIntentClassifier(
        endpoint="http://o",
        model="m",
        transport=_ok_response({"intent": "teleport", "confidence": 0.9}),
    )
    result = await clf.classify("beam mich hoch")
    assert result.ok is False


@pytest.mark.asyncio
async def test_garbage_content_is_not_ok():
    def handler(request):
        return httpx.Response(200, json={"message": {"content": "not json"}})

    clf = VoiceIntentClassifier(endpoint="http://o", model="m", transport=_transport(handler))
    result = await clf.classify("xyz")
    assert result.ok is False


@pytest.mark.asyncio
async def test_http_error_is_not_ok():
    def handler(request):
        return httpx.Response(500)

    clf = VoiceIntentClassifier(endpoint="http://o", model="m", transport=_transport(handler))
    result = await clf.classify("xyz")
    assert result.ok is False


@pytest.mark.asyncio
async def test_warmup_waits_longer_than_a_live_request():
    """Der Warmup darf das Laden des Modells nicht abbrechen.

    Gemessen am 25.08.2026: der Warmup lief mit demselben 4-s-Timeout wie eine
    echte Aeusserung. Ollama protokolliert daraufhin
    "client connection closed before llama-server finished loading, aborting
    load" und BRICHT DAS LADEN AB. Das Modell wurde daher nie warm, jede
    unsichere Aeusserung bezahlte erneut 4 s Wartezeit und fiel danach auf
    "nicht verstanden" -- der Fallback war dauerhaft wirkungslos.
    """
    seen: list[dict] = []

    def handler(request):
        seen.append(request.extensions.get("timeout") or {})
        return httpx.Response(200, json={"message": {"content": json.dumps(
            {"intent": "confirm", "confidence": 0.9})}})

    clf = VoiceIntentClassifier(
        endpoint="http://o", model="m", timeout_ms=4000, transport=_transport(handler)
    )

    await clf.classify("bestaetigen")
    live_read = seen[-1].get("read")

    await clf.warmup()
    warmup_read = seen[-1].get("read")

    assert live_read == 4.0
    assert warmup_read is not None and warmup_read >= 120.0
