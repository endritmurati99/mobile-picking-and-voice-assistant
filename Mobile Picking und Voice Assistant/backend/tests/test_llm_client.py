import json

import httpx
import pytest

from app.services.llm_client import LlmClient, RECOMMENDED_ACTIONS


def _client_with(handler):
    return LlmClient(
        endpoint="http://ollama:11434",
        model="qwen2.5:7b",
        timeout_ms=5000,
        transport=httpx.MockTransport(handler),
    )


@pytest.mark.anyio
async def test_classify_disposition_parses_valid_json():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        captured["body"] = json.loads(request.content)
        content = json.dumps({"disposition": "scrap", "confidence": 0.91, "summary": "Totalschaden am Karton."})
        return httpx.Response(200, json={"message": {"role": "assistant", "content": content}})

    client = _client_with(handler)
    result = await client.classify_disposition(description="Karton komplett zerbrochen", priority="1", photo_count=2)

    assert captured["path"] == "/api/chat"
    assert captured["body"]["format"] == "json"
    assert captured["body"]["model"] == "qwen2.5:7b"
    assert result.ok is True
    assert result.disposition == "scrap"
    assert result.confidence == 0.91
    assert result.summary == "Totalschaden am Karton."
    assert result.recommended_action == RECOMMENDED_ACTIONS["scrap"]
    assert result.model == "qwen2.5:7b"


@pytest.mark.anyio
async def test_classify_disposition_clamps_confidence_and_defaults_summary():
    def handler(request: httpx.Request) -> httpx.Response:
        content = json.dumps({"disposition": "REWORK", "confidence": 1.7, "summary": "  "})
        return httpx.Response(200, json={"message": {"content": content}})

    result = await _client_with(handler).classify_disposition(description="Etikett schief")

    assert result.ok is True
    assert result.disposition == "rework"  # normalized lowercase
    assert result.confidence == 1.0  # clamped to [0,1]
    assert result.summary == "LLM-Einstufung: rework."


@pytest.mark.anyio
async def test_invalid_category_returns_not_ok():
    def handler(request: httpx.Request) -> httpx.Response:
        content = json.dumps({"disposition": "explode", "confidence": 0.5, "summary": "x"})
        return httpx.Response(200, json={"message": {"content": content}})

    result = await _client_with(handler).classify_disposition(description="foo")

    assert result.ok is False
    assert result.disposition is None
    assert result.model == "qwen2.5:7b"


@pytest.mark.anyio
async def test_non_json_content_returns_not_ok():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"message": {"content": "kein json"}})

    result = await _client_with(handler).classify_disposition(description="foo")
    assert result.ok is False


@pytest.mark.anyio
async def test_http_error_returns_not_ok():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    result = await _client_with(handler).classify_disposition(description="foo")
    assert result.ok is False


@pytest.mark.anyio
async def test_transport_exception_returns_not_ok():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("ollama down")

    result = await _client_with(handler).classify_disposition(description="foo")
    assert result.ok is False
