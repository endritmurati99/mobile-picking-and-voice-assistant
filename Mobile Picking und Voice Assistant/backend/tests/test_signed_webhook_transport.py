import httpx
import pytest

from app.models.webhook_security import HmacKey
from app.services.signed_webhook_transport import SignedWebhookTransport


def make_transport(handler, **overrides):
    kwargs = dict(
        base_url="http://n8n:5678",
        native_header_secret="native-secret-" + ("x" * 32),
        signing_key=HmacKey("b2n-test", b"0" * 32),
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        now_seconds=lambda: 1760000000,
        nonce_factory=lambda: "123e4567-e89b-42d3-a456-426614174000",
    )
    kwargs.update(overrides)
    return SignedWebhookTransport(**kwargs)


@pytest.mark.asyncio
async def test_transport_hashes_and_sends_exact_stored_bytes():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = request.content
        captured["headers"] = dict(request.headers)
        return httpx.Response(
            200,
            json={
                "accepted": True,
                "event_id": "a4ff5ca2-4546-4ea4-8e6c-b75bc003ca32",
            },
        )

    raw = b'{"message":"Gr\\xc3\\xbcss dich","schema_version":"v2"}'
    transport = SignedWebhookTransport(
        base_url="http://n8n:5678",
        native_header_secret="native-secret-" + ("x" * 32),
        signing_key=HmacKey("b2n-test", b"0" * 32),
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        now_seconds=lambda: 1760000000,
        nonce_factory=lambda: "123e4567-e89b-42d3-a456-426614174000",
    )
    result = await transport.deliver_event(
        target="/webhook/quality-assessment-v2",
        event_id="a4ff5ca2-4546-4ea4-8e6c-b75bc003ca32",
        delivery_generation=1,
        raw_body=raw,
    )
    assert result.accepted
    assert captured["body"] == raw
    assert captured["headers"]["idempotency-key"] == result.event_id
    assert captured["headers"]["x-pwr-signed-target"] == (
        "/webhook/quality-assessment-v2"
    )


@pytest.mark.asyncio
async def test_transport_sends_complete_signed_header_set():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["headers"] = dict(request.headers)
        return httpx.Response(
            200, json={"accepted": True, "event_id": "evt-1"}
        )

    transport = make_transport(handler)
    await transport.deliver_event(
        target="/webhook/quality-assessment-v2",
        event_id="evt-1",
        delivery_generation=3,
        raw_body=b"{}",
    )
    headers = captured["headers"]
    assert headers["x-pwr-key-id"] == "b2n-test"
    assert headers["x-pwr-timestamp"] == "1760000000"
    assert headers["x-pwr-nonce"] == "123e4567-e89b-42d3-a456-426614174000"
    assert headers["x-pwr-signed-method"] == "POST"
    assert headers["x-pwr-delivery-generation"] == "3"
    assert headers["x-pwr-signature"].startswith("v1=")
    assert headers["x-pwr-webhook-secret"] == "native-secret-" + ("x" * 32)
    assert headers["content-type"] == "application/json"


@pytest.mark.asyncio
async def test_acceptance_must_echo_the_same_event_id():
    transport = SignedWebhookTransport(
        base_url="http://n8n:5678",
        native_header_secret="native-secret-" + ("x" * 32),
        signing_key=HmacKey("b2n-test", b"0" * 32),
        client=httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda _request: httpx.Response(
                    200, json={"accepted": True, "event_id": "wrong"}
                )
            )
        ),
    )
    result = await transport.deliver_event(
        target="/webhook/quality-assessment-v2",
        event_id="a4ff5ca2-4546-4ea4-8e6c-b75bc003ca32",
        delivery_generation=1,
        raw_body=b"{}",
    )
    assert not result.accepted
    assert result.error_code == "ambiguous_acceptance"


@pytest.mark.asyncio
async def test_acceptance_body_is_matched_exactly_not_by_subset():
    """Extra keys, missing keys, or accepted != True are never acceptance —
    the exact allowlisted body is required."""
    bodies = [
        {"accepted": True, "event_id": "evt-1", "extra": 1},
        {"accepted": True},
        {"accepted": False, "event_id": "evt-1"},
        {"accepted": "true", "event_id": "evt-1"},
        [],
        "accepted",
    ]
    for body in bodies:
        transport = make_transport(
            lambda _request, body=body: httpx.Response(200, json=body)
        )
        result = await transport.deliver_event(
            target="/webhook/quality-assessment-v2",
            event_id="evt-1",
            delivery_generation=1,
            raw_body=b"{}",
        )
        assert not result.accepted, f"body {body!r} must not be acceptance"
        assert result.error_code == "ambiguous_acceptance"


@pytest.mark.asyncio
async def test_invalid_targets_are_rejected_before_any_network_io():
    def handler(_request: httpx.Request) -> httpx.Response:
        raise AssertionError("no HTTP request may be sent for a bad target")

    transport = make_transport(handler)
    bad_targets = [
        "https://evil.example/webhook/x",
        "/other/path",
        "/webhook/",
        "/webhook/x?y=1",
        "/webhook/x#frag",
        "/webhook/../admin",
        "/webhook/a/b",
        "webhook/x",
        "/webhook/UPPER CASE",
        "/webhook/x\r\nHost: evil",
    ]
    for target in bad_targets:
        result = await transport.deliver_event(
            target=target,
            event_id="evt-1",
            delivery_generation=1,
            raw_body=b"{}",
        )
        assert not result.accepted, f"target {target!r} must be rejected"
        assert result.error_code == "invalid_target"


@pytest.mark.asyncio
async def test_http_and_decode_errors_are_transport_errors_never_acceptance():
    cases = [
        lambda _request: httpx.Response(500, json={"accepted": True}),
        lambda _request: httpx.Response(302, headers={"location": "http://e/"}),
        lambda _request: httpx.Response(200, content=b"not json"),
    ]

    def raise_connect(_request):
        raise httpx.ConnectError("connection refused")

    cases.append(raise_connect)
    for handler in cases:
        transport = make_transport(handler)
        result = await transport.deliver_event(
            target="/webhook/quality-assessment-v2",
            event_id="evt-1",
            delivery_generation=1,
            raw_body=b"{}",
        )
        assert not result.accepted
        assert result.error_code == "transport_error"


@pytest.mark.asyncio
async def test_each_delivery_attempt_uses_a_fresh_nonce_by_default():
    nonces = []

    def handler(request: httpx.Request) -> httpx.Response:
        nonces.append(request.headers["x-pwr-nonce"])
        return httpx.Response(
            200, json={"accepted": True, "event_id": "evt-1"}
        )

    transport = SignedWebhookTransport(
        base_url="http://n8n:5678",
        native_header_secret="native-secret-" + ("x" * 32),
        signing_key=HmacKey("b2n-test", b"0" * 32),
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    for _ in range(2):
        await transport.deliver_event(
            target="/webhook/quality-assessment-v2",
            event_id="evt-1",
            delivery_generation=1,
            raw_body=b"{}",
        )
    assert len(nonces) == 2
    assert nonces[0] != nonces[1]
