from unittest.mock import AsyncMock

import httpx
import pytest

from app.services.n8n_webhook import N8NReply, N8NWebhookClient


@pytest.mark.anyio
async def test_fire_event_wraps_payload_in_standard_envelope():
    client = N8NWebhookClient()
    captured = {}

    async def fake_post(url, json, headers, timeout=None):  # noqa: ARG001
        captured["url"] = url
        captured["json"] = json
        captured["headers"] = headers
        return object()

    client._client.post = AsyncMock(side_effect=fake_post)

    correlation_id = await client.fire_event(
        "quality-alert-created",
        {"alert_id": 42},
        picker={"user_id": 7, "name": "Mina Muster"},
        device_id="device-1",
        picking_context={
            "picking_id": 9,
            "move_line_id": 11,
            "product_id": 5,
            "location_id": 3,
            "priority": "2",
            "origin": "LEGO Ente",
        },
    )

    assert captured["url"].endswith("/quality-alert-created")
    assert captured["headers"]["Content-Type"] == "application/json"
    assert captured["json"]["event_name"] == "quality-alert-created"
    assert captured["json"]["schema_version"] == "v1"
    assert captured["json"]["picker"]["user_id"] == 7
    assert captured["json"]["device_id"] == "device-1"
    assert captured["json"]["picking_context"]["origin"] == "LEGO Ente"
    assert captured["json"]["payload"] == {"alert_id": 42}
    assert captured["json"]["correlation_id"] == correlation_id


@pytest.mark.anyio
async def test_request_reply_returns_parsed_n8n_response():
    client = N8NWebhookClient()

    async def fake_post(url, json, headers, timeout=None):  # noqa: ARG001
        request = httpx.Request("POST", url)
        return httpx.Response(
            200,
            json={
                "status": "ok",
                "tts_text": "Du baust die LEGO Ente.",
                "source": "n8n",
                "correlation_id": json["correlation_id"],
                "recommendation": {"action": "trigger_replenishment"},
            },
            request=request,
        )

    client._client.post = AsyncMock(side_effect=fake_post)

    reply = await client.request_reply(
        "voice-exception-query",
        {"text": "Was baue ich hier?", "intent": "unknown"},
    )

    assert isinstance(reply, N8NReply)
    assert reply.status == "ok"
    assert reply.tts_text == "Du baust die LEGO Ente."
    assert reply.source == "n8n"
    assert reply.correlation_id
    assert reply.latency_ms >= 0
    assert reply.recommendation == {"action": "trigger_replenishment"}


@pytest.mark.anyio
async def test_request_reply_opens_circuit_breaker_after_repeated_failures():
    client = N8NWebhookClient()
    client._client.post = AsyncMock(side_effect=httpx.TimeoutException("boom"))

    for _ in range(3):
        reply = await client.request_reply(
            "voice-exception-query",
            {"text": "noch da", "intent": "stock_query"},
        )
        assert reply.status == "fallback"
        assert reply.fallback_reason == "timeout"

    fail_fast_reply = await client.request_reply(
        "voice-exception-query",
        {"text": "noch da", "intent": "stock_query"},
    )

    assert fail_fast_reply.status == "fallback"
    assert fail_fast_reply.fallback_reason == "circuit_open"
    assert client._client.post.await_count == 3


def test_connect_timeout_uses_config_value(monkeypatch):
    """N8NWebhookClient.__init__ derives connect timeout from settings.n8n_connect_timeout_ms."""
    from app.config import settings as app_settings

    monkeypatch.setattr(app_settings, "n8n_connect_timeout_ms", 1000)
    client = N8NWebhookClient()

    assert client._client.timeout.connect == 1.0


def test_connect_timeout_custom_value(monkeypatch):
    """Verify a non-default connect timeout is correctly converted from ms to seconds."""
    from app.config import settings as app_settings

    monkeypatch.setattr(app_settings, "n8n_connect_timeout_ms", 2500)
    client = N8NWebhookClient()

    assert client._client.timeout.connect == 2.5
