from unittest.mock import AsyncMock

import pytest

from fastapi.testclient import TestClient

from app.main import app
from tests.conftest import BROWSER_GATE_HEADERS, install_browser_gate
from app.routers import voice as voice_router
from app.services.voice_intent_classifier import VoiceIntentResult


@pytest.fixture(autouse=True)
def _browser_gate():
    """Task 16: die Voice-Routen haengen am App-weiten Browser-Gate. Diese
    Datei prueft die LLM-Fallback-Logik, nicht das Gate -- sie erfuellt es."""
    install_browser_gate(app)
    yield
    app.dependency_overrides.clear()


class _SpyClassifier:
    def __init__(self, result):
        self.result = result
        self.calls = 0

    async def classify(self, text):
        self.calls += 1
        return self.result


def _wire(monkeypatch, whisper_text, classifier):
    monkeypatch.setattr(voice_router, "convert_to_wav", AsyncMock(return_value=b"wav-bytes"))
    monkeypatch.setattr(
        voice_router.whisper_client, "transcribe_audio", AsyncMock(return_value=whisper_text)
    )
    monkeypatch.setattr(voice_router, "get_classifier", lambda: classifier)


def _post(client):
    return client.post(
        "/api/voice/recognize",
        data={
            "context": "awaiting_command",
            "surface": "detail",
            "remaining_line_count": "2",
            "active_line_present": "true",
        },
        files={"audio": ("voice.webm", b"1234", "audio/webm")},
    )


def test_llm_fills_unknown(monkeypatch):
    spy = _SpyClassifier(VoiceIntentResult(ok=True, model="m", intent="next", confidence=0.8))
    _wire(monkeypatch, "der himmel ist heute blau", spy)
    with TestClient(app, headers=BROWSER_GATE_HEADERS) as client:
        body = _post(client).json()
    assert body["intent"] == "next"
    assert body["match_strategy"] == "llm"
    assert spy.calls == 1


def test_llm_confirm_is_confidence_capped(monkeypatch):
    spy = _SpyClassifier(VoiceIntentResult(ok=True, model="m", intent="confirm", confidence=0.99))
    _wire(monkeypatch, "die sonne scheint schoen warm", spy)
    with TestClient(app, headers=BROWSER_GATE_HEADERS) as client:
        body = _post(client).json()
    assert body["intent"] == "confirm"
    assert body["confidence"] <= 0.85


def test_llm_not_called_on_confident_match(monkeypatch):
    spy = _SpyClassifier(VoiceIntentResult(ok=True, model="m", intent="next", confidence=0.9))
    _wire(monkeypatch, "bestaetigen", spy)
    with TestClient(app, headers=BROWSER_GATE_HEADERS) as client:
        body = _post(client).json()
    assert body["intent"] == "confirm"
    assert spy.calls == 0


def test_llm_failure_keeps_unknown(monkeypatch):
    spy = _SpyClassifier(VoiceIntentResult(ok=False, model="m"))
    _wire(monkeypatch, "zwei drei vier fuenf sechs", spy)
    with TestClient(app, headers=BROWSER_GATE_HEADERS) as client:
        body = _post(client).json()
    assert body["intent"] == "unknown"
    assert spy.calls == 1
