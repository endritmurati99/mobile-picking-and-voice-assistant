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
