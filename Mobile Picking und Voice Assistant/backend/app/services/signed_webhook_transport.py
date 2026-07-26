"""Signed v2 event transport: one signed attempt per call, no local retries.

Retry timing belongs exclusively to the Odoo outbox (Task 8 backoff table);
this transport signs the EXACT stored envelope bytes, sends them once, and
reports acceptance only when the receiver echoes the same event ID. The
legacy v1 transport lives untouched in `n8n_webhook.py`.
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass
from typing import Callable
from uuid import uuid4

import httpx

from app.models.webhook_security import HmacKey
from app.services.hmac_signing import sign_request

# Allowlist, not denylist: a deliverable target is exactly one /webhook/
# segment made of lowercase letters, digits and hyphens (the same charset
# `load_event_targets` enforces on the registry side). Everything else —
# absolute URLs, query strings, fragments, traversal, extra segments,
# header-injection attempts — fails closed before any network I/O.
_ALLOWED_TARGET = re.compile(r"^/webhook/[a-z0-9][a-z0-9-]*$")


@dataclass(frozen=True)
class WebhookAcceptanceResult:
    accepted: bool
    event_id: str
    status_code: int | None
    error_code: str | None
    error_message: str | None


class SignedWebhookTransport:
    def __init__(
        self,
        *,
        base_url: str,
        native_header_secret: str,
        signing_key: HmacKey,
        client: httpx.AsyncClient | None = None,
        now_seconds: Callable[[], int] = lambda: int(time.time()),
        nonce_factory: Callable[[], str] = lambda: str(uuid4()),
    ):
        self._base_url = base_url.rstrip("/")
        self._native_secret = native_header_secret
        self._key = signing_key
        self._client = client or httpx.AsyncClient(
            timeout=httpx.Timeout(connect=1.0, read=10.0, write=10.0, pool=5.0)
        )
        self._now_seconds = now_seconds
        self._nonce_factory = nonce_factory

    async def deliver_event(
        self,
        *,
        target: str,
        event_id: str,
        delivery_generation: int,
        raw_body: bytes,
    ) -> WebhookAcceptanceResult:
        if not _ALLOWED_TARGET.fullmatch(target):
            return WebhookAcceptanceResult(
                False, event_id, None, "invalid_target", "Target is not registered."
            )
        signed = sign_request(
            method="POST",
            target=target,
            delivery_generation=delivery_generation,
            timestamp=self._now_seconds(),
            nonce=self._nonce_factory(),
            raw_body=raw_body,
            key=self._key,
        )
        headers = {
            **signed.as_http_headers(),
            "Content-Type": "application/json",
            "Idempotency-Key": event_id,
            "X-PWR-Webhook-Secret": self._native_secret,
        }
        try:
            response = await self._client.post(
                f"{self._base_url}{target}",
                content=raw_body,
                headers=headers,
                follow_redirects=False,
            )
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            status = (
                exc.response.status_code
                if isinstance(exc, httpx.HTTPStatusError)
                else None
            )
            return WebhookAcceptanceResult(
                False,
                event_id,
                status,
                "transport_error",
                type(exc).__name__,
            )
        # Exact allowlisted acceptance body. `is True` (not ==) because JSON 1
        # would otherwise compare equal to True.
        acceptance_ok = (
            isinstance(payload, dict)
            and set(payload) == {"accepted", "event_id"}
            and payload["accepted"] is True
            and payload["event_id"] == event_id
        )
        if not acceptance_ok:
            return WebhookAcceptanceResult(
                False,
                event_id,
                response.status_code,
                "ambiguous_acceptance",
                "Acceptance body did not echo the event ID.",
            )
        return WebhookAcceptanceResult(
            True, event_id, response.status_code, None, None
        )
