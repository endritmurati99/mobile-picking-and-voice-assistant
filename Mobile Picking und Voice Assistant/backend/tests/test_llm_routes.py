from fastapi.testclient import TestClient

from app.config import settings
from app.dependencies import get_llm_client
from app.main import app
from app.services.llm_client import LlmClient, LlmDispositionResult


class _StubLlm:
    def __init__(self, result: LlmDispositionResult):
        self._result = result
        self.calls = []

    async def classify_disposition(self, **kwargs):
        self.calls.append(kwargs)
        return self._result


def _override(stub):
    app.dependency_overrides[get_llm_client] = lambda: stub


def test_requires_callback_secret(monkeypatch):
    monkeypatch.setattr(settings, "n8n_callback_secret", "top-secret")
    with TestClient(app) as client:
        resp = client.post(
            "/api/internal/llm/quality-disposition",
            json={"alert_id": 1, "description": "kaputt"},
        )
    assert resp.status_code == 403


def test_returns_llm_disposition_on_success(monkeypatch):
    monkeypatch.setattr(settings, "n8n_callback_secret", "top-secret")
    monkeypatch.setattr(settings, "llm_provider", "ollama")
    stub = _StubLlm(LlmDispositionResult(
        ok=True, model="qwen2.5:7b", disposition="quarantine",
        confidence=0.72, summary="Feuchter Karton.", recommended_action="Ware sperren und manuelle Pruefung anfordern.",
    ))
    _override(stub)
    try:
        with TestClient(app) as client:
            resp = client.post(
                "/api/internal/llm/quality-disposition",
                headers={"X-N8N-Callback-Secret": "top-secret"},
                json={"alert_id": 7, "description": "Karton feucht", "priority": 1, "photo_count": 1},
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["llm_ok"] is True
        assert body["llm_disposition"] == "quarantine"
        assert body["llm_confidence"] == 0.72
        assert body["llm_provider"] == "ollama-local"
        # priority coerced from int to str before reaching the client
        assert stub.calls[0]["priority"] == "1"
    finally:
        app.dependency_overrides.pop(get_llm_client, None)


def test_returns_not_ok_when_llm_fails(monkeypatch):
    monkeypatch.setattr(settings, "n8n_callback_secret", "top-secret")
    monkeypatch.setattr(settings, "llm_provider", "ollama")
    stub = _StubLlm(LlmDispositionResult(ok=False, model="qwen2.5:7b"))
    _override(stub)
    try:
        with TestClient(app) as client:
            resp = client.post(
                "/api/internal/llm/quality-disposition",
                headers={"X-N8N-Callback-Secret": "top-secret"},
                json={"alert_id": 7, "description": "unklar"},
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["llm_ok"] is False
        assert body["llm_disposition"] is None
        assert body["llm_provider"] == "ollama-local"
    finally:
        app.dependency_overrides.pop(get_llm_client, None)


def test_disabled_provider_short_circuits(monkeypatch):
    monkeypatch.setattr(settings, "n8n_callback_secret", "top-secret")
    monkeypatch.setattr(settings, "llm_provider", "disabled")
    stub = _StubLlm(LlmDispositionResult(ok=True, model="x", disposition="scrap", confidence=0.9, summary="s"))
    _override(stub)
    try:
        with TestClient(app) as client:
            resp = client.post(
                "/api/internal/llm/quality-disposition",
                headers={"X-N8N-Callback-Secret": "top-secret"},
                json={"alert_id": 7, "description": "kaputt"},
            )
        assert resp.status_code == 200
        assert resp.json()["llm_ok"] is False
        assert stub.calls == []  # LLM never called when provider disabled
    finally:
        app.dependency_overrides.pop(get_llm_client, None)
