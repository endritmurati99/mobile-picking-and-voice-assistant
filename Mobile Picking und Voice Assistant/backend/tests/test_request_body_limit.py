"""The request body limit needs a second, ASGI-level layer in the backend.

Program register §3.8: `await request.body()` necessarily precedes signature
verification, and `Content-Length` is bypassable with chunked transfer
encoding. Caddy's `request_body { max_size 16MB }` protects the edge only --
and a direct n8n -> backend call does not pass through Caddy at all, because
n8n talks to the backend on the private internal network.

The guard that matters is therefore the streaming one: it must bound the bytes
actually read off the wire, not merely inspect a header, and it must answer
413 rather than raise something the application turns into a 500.

A test that only sends an oversized `Content-Length` header proves nothing
about the case the header check cannot see, so the central test here sends a
chunked body (no `Content-Length` at all) and asserts both the refusal and the
bound on bytes consumed.
"""

import json

import httpx
import pytest
from starlette.applications import Starlette
from starlette.responses import PlainTextResponse
from starlette.routing import Route

from app.config import Settings
from app.middleware import RequestBodySizeLimitMiddleware

LIMIT = 1024


async def echo_length(request):
    body = await request.body()
    return PlainTextResponse(str(len(body)))


def build_app(max_body_bytes: int = LIMIT) -> Starlette:
    app = Starlette(routes=[Route("/echo", echo_length, methods=["POST"])])
    return RequestBodySizeLimitMiddleware(app, max_body_bytes=max_body_bytes)


def client_for(app) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://backend"
    )


# ---------------------------------------------------------------------------
# The chunked case -- the one the Content-Length check cannot see
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_chunked_body_over_the_limit_is_refused():
    """No Content-Length header exists on this request at all."""
    sent = []

    async def body_chunks():
        for _ in range(100):
            chunk = b"x" * 256
            sent.append(len(chunk))
            yield chunk

    async with client_for(build_app()) as client:
        response = await client.post("/echo", content=body_chunks())

    assert response.status_code == 413, response.text
    # The framing really was chunked: httpx omits Content-Length for a
    # streamed body, so nothing about this refusal came from a header.
    assert sum(sent) > LIMIT


@pytest.mark.asyncio
async def test_the_refusal_happens_after_a_bounded_number_of_bytes():
    """The generator would produce 8 MiB; the guard must stop pulling from it."""
    produced = 0

    async def body_chunks():
        nonlocal produced
        for _ in range(8192):
            chunk = b"y" * 1024
            produced += len(chunk)
            yield chunk

    async with client_for(build_app()) as client:
        response = await client.post("/echo", content=body_chunks())

    assert response.status_code == 413
    # At most the limit plus the one chunk that crossed it may have been read.
    assert produced <= LIMIT + 1024, f"read {produced} bytes for a {LIMIT}-byte limit"


@pytest.mark.asyncio
async def test_the_handler_never_sees_an_oversized_chunked_body():
    seen = []

    async def record(request):
        seen.append(len(await request.body()))
        return PlainTextResponse("ok")

    inner = Starlette(routes=[Route("/echo", record, methods=["POST"])])
    app = RequestBodySizeLimitMiddleware(inner, max_body_bytes=LIMIT)

    async def body_chunks():
        for _ in range(10):
            yield b"z" * 512

    async with client_for(app) as client:
        response = await client.post("/echo", content=body_chunks())

    assert response.status_code == 413
    assert seen == []


# ---------------------------------------------------------------------------
# The cheap header layer, and the pass-through cases
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_an_oversized_content_length_is_refused_without_calling_the_app():
    called = []

    async def record(request):
        called.append(True)
        return PlainTextResponse("ok")

    inner = Starlette(routes=[Route("/echo", record, methods=["POST"])])
    app = RequestBodySizeLimitMiddleware(inner, max_body_bytes=LIMIT)

    async with client_for(app) as client:
        response = await client.post("/echo", content=b"a" * (LIMIT + 1))

    assert response.status_code == 413
    assert called == []


@pytest.mark.asyncio
async def test_a_body_at_the_limit_is_delivered_unchanged():
    async with client_for(build_app()) as client:
        response = await client.post("/echo", content=b"a" * LIMIT)
    assert response.status_code == 200
    assert response.text == str(LIMIT)


@pytest.mark.asyncio
async def test_a_chunked_body_at_the_limit_is_delivered_unchanged():
    async def body_chunks():
        for _ in range(4):
            yield b"a" * 256

    async with client_for(build_app()) as client:
        response = await client.post("/echo", content=body_chunks())
    assert response.status_code == 200
    assert response.text == str(LIMIT)


@pytest.mark.asyncio
async def test_the_refusal_is_json_and_leaks_no_configuration():
    async with client_for(build_app()) as client:
        response = await client.post("/echo", content=b"a" * (LIMIT + 1))
    payload = json.loads(response.text)
    assert "detail" in payload
    assert str(LIMIT) not in response.text


@pytest.mark.asyncio
async def test_a_bodyless_request_passes_through():
    async def ping(request):
        return PlainTextResponse("pong")

    inner = Starlette(routes=[Route("/ping", ping, methods=["GET"])])
    app = RequestBodySizeLimitMiddleware(inner, max_body_bytes=LIMIT)
    async with client_for(app) as client:
        response = await client.get("/ping")
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_non_http_scopes_are_passed_through_untouched():
    seen = []

    async def inner(scope, receive, send):
        seen.append(scope["type"])

    app = RequestBodySizeLimitMiddleware(inner, max_body_bytes=LIMIT)
    await app({"type": "lifespan"}, None, None)
    assert seen == ["lifespan"]


# ---------------------------------------------------------------------------
# Configuration and wiring
# ---------------------------------------------------------------------------


def test_the_default_limit_matches_the_edge_and_n8n():
    # Caddy: request_body { max_size 16MB }; n8n: N8N_PAYLOAD_SIZE_MAX=16.
    assert Settings().max_request_body_bytes == 16 * 1024 * 1024


def test_the_limit_is_configurable():
    assert Settings(max_request_body_bytes=1234).max_request_body_bytes == 1234


def test_a_non_positive_limit_is_rejected():
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        Settings(max_request_body_bytes=0)


@pytest.mark.asyncio
async def test_the_limit_fires_before_signature_verification_on_the_real_app(
    monkeypatch,
):
    """The whole point of the ASGI layer, exercised end to end.

    `/api/internal/n8n/v2/events/accept` verifies an HMAC signature computed over the
    raw body, so `await request.body()` unavoidably runs first. An unsigned,
    chunked, oversized request must therefore be answered 413 -- not 401 or
    403, which would mean the body had already been buffered in full, and not
    500, which would mean the guard raised something the app converted.
    """
    import base64

    import app.dependencies as dependencies
    import app.main as main
    from app.middleware import RequestBodySizeLimitMiddleware as Limiter

    # The keyring is configured, so the route really does get as far as
    # reading the raw body in order to verify the signature over it. Task 16:
    # the keyring comes from the settings of THIS app, so that is what gets
    # replaced -- a patched module global would no longer reach it.
    monkeypatch.setattr(
        main.app.state.runtime,
        "settings",
        Settings(
            pwr_n8n_to_backend_active_key_id="n2b-test",
            pwr_n8n_to_backend_active_secret_b64=base64.b64encode(b"5" * 32).decode(),
        ),
    )

    small = 4096
    limited = Limiter(main.app, max_body_bytes=small)

    produced = 0

    async def body_chunks():
        nonlocal produced
        for _ in range(4096):
            chunk = b"q" * 1024
            produced += len(chunk)
            yield chunk

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=limited), base_url="http://backend"
    ) as client:
        response = await client.post(
            "/api/internal/n8n/v2/events/accept", content=body_chunks()
        )

    assert response.status_code == 413, response.text
    assert produced <= small + 1024


def test_the_application_wires_the_limit_and_keeps_cors_outside_it():
    from starlette.middleware.cors import CORSMiddleware

    from app.main import app

    classes = [middleware.cls for middleware in app.user_middleware]
    assert RequestBodySizeLimitMiddleware in classes
    # CORS must sit OUTSIDE the limiter so a 413 still carries the CORS
    # headers the PWA needs to read it; user_middleware is ordered
    # outermost-first.
    assert classes.index(CORSMiddleware) < classes.index(
        RequestBodySizeLimitMiddleware
    )
