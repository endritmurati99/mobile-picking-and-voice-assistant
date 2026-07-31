"""ASGI middleware owned by Task 15.

Currently exactly one guard: the second layer of the request body limit
(program register §3.8).
"""
from __future__ import annotations

import logging

from starlette.datastructures import Headers
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

logger = logging.getLogger(__name__)

# 413. Starlette spells this REQUEST_ENTITY_TOO_LARGE; RFC 9110 renamed it
# "Content Too Large". Spelled literally so neither name has to be guessed.
_STATUS_CONTENT_TOO_LARGE = 413


class _RequestBodyTooLarge(Exception):
    """Raised out of the wrapped `receive` once the bound is crossed.

    Private to this module: it exists only to unwind the downstream
    application out of its `await request.body()` and is always caught by the
    middleware that raised it, which answers 413 itself. It must never reach
    Starlette's `ServerErrorMiddleware`, which would turn it into a 500.
    """


class RequestBodySizeLimitMiddleware:
    """Bound the bytes actually read from a request body.

    Why a second layer at all, when `infrastructure/caddy/Caddyfile` already
    sets `request_body { max_size 16MB }`:

    * Caddy sees only traffic that reaches the edge. n8n calls the backend
      directly on the private internal network and never passes through
      Caddy, so the edge limit does not exist for that path at all.
    * `Content-Length` is advisory. A chunked request carries no
      `Content-Length` header whatsoever, so any check that reads the header
      is blind to exactly the request an attacker would send.
    * `await request.body()` necessarily precedes HMAC signature
      verification -- the signature is computed over the raw body -- so an
      unauthenticated peer can make the process buffer a body before any
      credential has been checked. The bound therefore has to sit below the
      verification, in the ASGI layer.

    This is a raw ASGI middleware, not a `BaseHTTPMiddleware` subclass:
    `BaseHTTPMiddleware` would itself buffer the stream it is supposed to be
    bounding.
    """

    def __init__(self, app: ASGIApp, max_body_bytes: int) -> None:
        if max_body_bytes < 1:
            raise ValueError("max_body_bytes must be positive")
        self.app = app
        self.max_body_bytes = max_body_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        # Cheap layer: a request that admits to being too large is refused
        # before the application is entered at all. This is a courtesy, NOT
        # the guard -- a chunked request has no Content-Length to inspect.
        declared = Headers(scope=scope).get("content-length")
        if declared is not None:
            try:
                if int(declared) > self.max_body_bytes:
                    await self._refuse(scope, send)
                    return
            except ValueError:
                pass  # A malformed header is the HTTP server's problem.

        received = 0
        response_started = False
        refused = False

        async def limited_receive() -> Message:
            nonlocal received, refused
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_body_bytes:
                    # The 413 is written HERE, before unwinding, and not from
                    # the `except` clause below. Between this middleware and
                    # the route sits Starlette's own `ServerErrorMiddleware`,
                    # which catches any exception, emits a 500 and only then
                    # re-raises: an exception that travels up first would
                    # therefore reach the client as a 500 no matter what this
                    # middleware did afterwards. Writing the refusal first and
                    # discarding everything the unwinding application still
                    # tries to send keeps the answer a 413 regardless of what
                    # sits in between.
                    if not response_started:
                        await self._refuse(scope, send)
                    else:
                        logger.warning(
                            "Request body limit exceeded on %s after the "
                            "response had started; connection dropped",
                            scope.get("path", ""),
                        )
                    refused = True
                    # Stop here. Nothing further is pulled from the client,
                    # so the bytes buffered by this process stay bounded by
                    # the limit plus the single chunk that crossed it.
                    raise _RequestBodyTooLarge
            return message

        async def guarded_send(message: Message) -> None:
            nonlocal response_started
            if refused:
                # The refusal is already on the wire; anything the unwinding
                # application still produces (typically a 500 page) is
                # discarded rather than appended to it.
                return
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self.app(scope, limited_receive, guarded_send)
        except _RequestBodyTooLarge:
            pass  # Already answered with 413 inside `limited_receive`.

    async def _refuse(self, scope: Scope, send: Send) -> None:
        logger.warning(
            "Refused %s %s: request body exceeds the configured limit",
            scope.get("method", ""),
            scope.get("path", ""),
        )
        # The configured limit is deliberately NOT echoed to the caller: it
        # tells an unauthenticated peer exactly how much it may send.
        response = JSONResponse(
            status_code=_STATUS_CONTENT_TOO_LARGE,
            content={"detail": "Request body is too large."},
        )
        await response(scope, _no_more_body, send)


async def _no_more_body() -> Message:
    """A `receive` for the refusal response that never reads the client again."""
    return {"type": "http.disconnect"}
