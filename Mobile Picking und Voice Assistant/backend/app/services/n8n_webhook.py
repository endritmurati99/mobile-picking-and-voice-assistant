"""Outbound n8n client with event envelopes and a sync circuit breaker."""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

_ENVELOPE_VERSION = "v1"
_DEFAULT_PICKING_CONTEXT = (
    "picking_id",
    "move_line_id",
    "product_id",
    "location_id",
    "priority",
    "origin",
)


@dataclass
class BreakerState:
    consecutive_failures: int = 0
    opened_until: float | None = None
    probe_in_flight: bool = False


@dataclass(frozen=True)
class N8NReply:
    status: str
    tts_text: str
    source: str
    correlation_id: str
    latency_ms: int
    fallback_reason: str | None = None
    recommendation: dict[str, Any] | None = None

    def asdict(self) -> dict[str, Any]:
        payload = {
            "status": self.status,
            "tts_text": self.tts_text,
            "source": self.source,
            "correlation_id": self.correlation_id,
            "latency_ms": self.latency_ms,
        }
        if self.fallback_reason:
            payload["fallback_reason"] = self.fallback_reason
        if self.recommendation:
            payload["recommendation"] = self.recommendation
        return payload


class N8NWebhookClient:
    def __init__(self):
        self._base = settings.n8n_webhook_base.rstrip("/")
        self._secret = settings.n8n_webhook_secret
        self._path_overrides = {
            "quality-alert-created": settings.n8n_webhook_path_quality_alert_created,
            "voice-exception-query": settings.n8n_webhook_path_voice_exception_query,
            "shortage-reported": settings.n8n_webhook_path_shortage_reported,
            "pick-confirmed": settings.n8n_webhook_path_pick_confirmed,
        }
        self._default_sync_timeout_ms = settings.n8n_sync_timeout_ms
        self._breaker_threshold = max(1, settings.n8n_circuit_breaker_failures)
        self._breaker_open_seconds = max(1, settings.n8n_circuit_breaker_open_seconds)
        self._breaker_states: dict[str, BreakerState] = {}
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(connect=settings.n8n_connect_timeout_ms / 1000.0, read=10.0, write=10.0, pool=5.0),
            limits=httpx.Limits(
                max_keepalive_connections=5,
                max_connections=10,
                keepalive_expiry=30.0,
            ),
        )

    async def fire_event(
        self,
        path: str,
        payload: dict[str, Any],
        *,
        event_name: str | None = None,
        picker: dict[str, Any] | None = None,
        device_id: str | None = None,
        picking_context: dict[str, Any] | None = None,
        correlation_id: str | None = None,
    ) -> str:
        envelope = self._build_envelope(
            path=path,
            event_name=event_name or path,
            payload=payload,
            picker=picker,
            device_id=device_id,
            picking_context=picking_context,
            correlation_id=correlation_id,
        )
        resolved_path = self._resolve_path(path)
        try:
            await self._client.post(
                f"{self._base}/{resolved_path}",
                json=envelope,
                headers=self._build_headers(),
            )
        except Exception as exc:
            logger.warning("n8n Webhook fehlgeschlagen (%s): %s", path, exc)
        return envelope["correlation_id"]

    async def fire(
        self,
        path: str,
        data: dict[str, Any],
        *,
        picker: dict[str, Any] | None = None,
        device_id: str | None = None,
        picking_context: dict[str, Any] | None = None,
        correlation_id: str | None = None,
    ) -> str:
        return await self.fire_event(
            path,
            data,
            picker=picker,
            device_id=device_id,
            picking_context=picking_context,
            correlation_id=correlation_id,
        )

    async def request_reply(
        self,
        path: str,
        payload: dict[str, Any],
        *,
        event_name: str | None = None,
        picker: dict[str, Any] | None = None,
        device_id: str | None = None,
        picking_context: dict[str, Any] | None = None,
        correlation_id: str | None = None,
        timeout_ms: int | None = None,
        fallback_text: str = "Ich kann das gerade nicht sicher beantworten.",
    ) -> N8NReply:
        envelope = self._build_envelope(
            path=path,
            event_name=event_name or path,
            payload=payload,
            picker=picker,
            device_id=device_id,
            picking_context=picking_context,
            correlation_id=correlation_id,
        )
        resolved_path = self._resolve_path(path)
        started_at = time.monotonic()

        breaker_state = self._breaker_states.setdefault(path, BreakerState())
        if self._is_breaker_open(path, breaker_state):
            logger.warning("n8n Circuit Breaker offen fuer %s", path)
            return self._build_fallback_reply(
                correlation_id=envelope["correlation_id"],
                started_at=started_at,
                fallback_text=fallback_text,
                fallback_reason="circuit_open",
            )

        request_timeout_ms = max(1, timeout_ms or self._default_sync_timeout_ms)
        timeout = httpx.Timeout(
            connect=2.0,
            read=request_timeout_ms / 1000.0,
            write=10.0,
            pool=5.0,
        )

        try:
            response = await self._client.post(
                f"{self._base}/{resolved_path}",
                json=envelope,
                headers=self._build_headers(),
                timeout=timeout,
            )
            response.raise_for_status()
            data = response.json()
            reply = self._parse_sync_reply(
                data,
                correlation_id=envelope["correlation_id"],
                started_at=started_at,
            )
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            self._record_failure(path, breaker_state)
            logger.warning("n8n Sync-Call fehlgeschlagen (%s): %s", path, exc)
            return self._build_fallback_reply(
                correlation_id=envelope["correlation_id"],
                started_at=started_at,
                fallback_text=fallback_text,
                fallback_reason="timeout" if isinstance(exc, httpx.TimeoutException) else "transport_error",
            )
        except (httpx.HTTPStatusError, ValueError) as exc:
            self._record_failure(path, breaker_state)
            logger.warning("n8n Sync-Call lieferte ungueltige Antwort (%s): %s", path, exc)
            return self._build_fallback_reply(
                correlation_id=envelope["correlation_id"],
                started_at=started_at,
                fallback_text=fallback_text,
                fallback_reason="contract_error",
            )

        self._reset_breaker(breaker_state)
        return reply

    def _build_headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self._secret:
            headers["X-Webhook-Secret"] = self._secret
        return headers

    def _resolve_path(self, path: str) -> str:
        return (self._path_overrides.get(path) or path).strip("/")

    def _build_envelope(
        self,
        *,
        path: str,
        event_name: str,
        payload: dict[str, Any],
        picker: dict[str, Any] | None,
        device_id: str | None,
        picking_context: dict[str, Any] | None,
        correlation_id: str | None,
    ) -> dict[str, Any]:
        return {
            "event_name": event_name or path,
            "schema_version": _ENVELOPE_VERSION,
            "correlation_id": correlation_id or str(uuid4()),
            "occurred_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "picker": {
                "user_id": (picker or {}).get("user_id"),
                "name": (picker or {}).get("name", ""),
            },
            "device_id": device_id or "",
            "picking_context": self._normalize_picking_context(picking_context or {}),
            "payload": payload,
        }

    def _normalize_picking_context(self, picking_context: dict[str, Any]) -> dict[str, Any]:
        return {
            key: picking_context.get(key)
            for key in _DEFAULT_PICKING_CONTEXT
        }

    def _parse_sync_reply(
        self,
        data: Any,
        *,
        correlation_id: str,
        started_at: float,
    ) -> N8NReply:
        if not isinstance(data, dict):
            raise ValueError("n8n Antwort muss JSON-Objekt sein.")

        missing_keys = [key for key in ("status", "tts_text", "source") if not data.get(key)]
        if missing_keys:
            raise ValueError(f"n8n Antwort ohne Pflichtfelder: {', '.join(missing_keys)}")

        resolved_correlation_id = str(data.get("correlation_id") or correlation_id)
        return N8NReply(
            status=str(data["status"]),
            tts_text=str(data["tts_text"]),
            source=str(data["source"]),
            correlation_id=resolved_correlation_id,
            latency_ms=round((time.monotonic() - started_at) * 1000),
            fallback_reason=None,
            recommendation=data.get("recommendation") if isinstance(data.get("recommendation"), dict) else None,
        )

    def _build_fallback_reply(
        self,
        *,
        correlation_id: str,
        started_at: float,
        fallback_text: str,
        fallback_reason: str,
    ) -> N8NReply:
        return N8NReply(
            status="fallback",
            tts_text=fallback_text,
            source="fastapi-fallback",
            correlation_id=correlation_id,
            latency_ms=round((time.monotonic() - started_at) * 1000),
            fallback_reason=fallback_reason,
            recommendation=None,
        )

    def _is_breaker_open(self, path: str, state: BreakerState) -> bool:
        now = time.monotonic()
        if state.opened_until is None:
            return False
        if now < state.opened_until:
            return True
        if state.probe_in_flight:
            return True
        logger.info("n8n Circuit Breaker Halb-Offen fuer %s", path)
        state.probe_in_flight = True
        return False

    def _record_failure(self, path: str, state: BreakerState) -> None:
        state.consecutive_failures += 1
        state.probe_in_flight = False
        if state.consecutive_failures >= self._breaker_threshold:
            state.opened_until = time.monotonic() + self._breaker_open_seconds
            logger.warning(
                "n8n Circuit Breaker geoeffnet fuer %s nach %d Fehlern",
                path,
                state.consecutive_failures,
            )

    def _reset_breaker(self, state: BreakerState) -> None:
        state.consecutive_failures = 0
        state.opened_until = None
        state.probe_in_flight = False
