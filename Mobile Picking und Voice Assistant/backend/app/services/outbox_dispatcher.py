"""Lease-driven outbox dispatcher and integration watchdog.

The dispatcher never builds or reserializes an envelope: it leases due outbox
rows from Odoo (Task 8 `api_lease_due`), hands the STORED envelope bytes to
the signed transport, and acks/nacks under the same worker lease. Double
delivery is fenced on the Odoo side (`_owned_lease` ownership + expiry under
`FOR UPDATE`); this process never acknowledges an event the transport did not
report as accepted with a matching event-ID echo.

The pure construction functions (`build_outbox_dispatcher`,
`build_integration_watchdog`) read ONLY the candidate `Settings` they are
given — Task 16 builds one graph per app from them.
"""
from __future__ import annotations

import asyncio
import logging
import os
import socket
from dataclasses import dataclass

from app.config import Settings, decode_secret_b64, get_instance_registry
from app.models.webhook_security import HmacKey
from app.services.signed_webhook_transport import SignedWebhookTransport

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DispatchStats:
    leased: int = 0
    delivered: int = 0
    deferred: int = 0


@dataclass(frozen=True)
class WatchdogStats:
    recovered: int = 0


class OutboxDispatcher:
    def __init__(
        self,
        *,
        client_factory,
        instance_names: tuple[str, ...],
        transport,
        targets: dict[str, str],
        worker_id: str,
        poll_seconds: float = 2.0,
        lease_seconds: int = 60,
        batch_size: int = 50,
    ):
        self._client_factory = client_factory
        self._instances = instance_names
        self._transport = transport
        self._targets = targets
        self._worker_id = worker_id
        self._poll_seconds = poll_seconds
        self._lease_seconds = lease_seconds
        self._batch_size = batch_size

    async def run_once(self, instance: str) -> DispatchStats:
        odoo = self._client_factory(instance)
        rows = await odoo.execute_kw(
            "picking.assistant.outbox",
            "api_lease_due",
            [self._worker_id, self._batch_size, self._lease_seconds],
        )
        delivered = 0
        deferred = 0
        for row in rows:
            target = self._targets.get(row["event_name"])
            if target is None:
                # Approved event without a landed v2 workflow: defer via the
                # frozen Odoo backoff, never invent a target locally.
                accepted = False
                result_code = "unregistered_event_target"
                result_message = "No v2 target is registered."
            else:
                result = await self._transport.deliver_event(
                    target=target,
                    event_id=row["event_id"],
                    delivery_generation=int(row["delivery_generation"]),
                    raw_body=row["envelope_text"].encode("utf-8"),
                )
                accepted = result.accepted
                result_code = result.error_code or ""
                result_message = result.error_message or ""
            if accepted:
                await odoo.execute_kw(
                    "picking.assistant.outbox",
                    "api_ack_delivery",
                    [row["event_id"], self._worker_id, result.event_id],
                )
                delivered += 1
            else:
                await odoo.execute_kw(
                    "picking.assistant.outbox",
                    "api_nack_delivery",
                    [
                        row["event_id"],
                        self._worker_id,
                        result_code,
                        result_message,
                    ],
                )
                deferred += 1
        return DispatchStats(
            leased=len(rows), delivered=delivered, deferred=deferred
        )

    async def run(self, stop_event: asyncio.Event) -> None:
        while not stop_event.is_set():
            for instance in self._instances:
                try:
                    await self.run_once(instance)
                except Exception:
                    logger.exception("Outbox cycle failed for instance %s", instance)
            try:
                await asyncio.wait_for(
                    stop_event.wait(), timeout=self._poll_seconds
                )
            except TimeoutError:
                pass


class IntegrationWatchdog:
    """Backend-side trigger for the guarded Odoo watchdog batch. The batch
    itself (locking, generation bump, outbox reset) lives in Odoo and returns
    only counts — never lease tokens."""

    def __init__(self, *, client_factory, instance_names: tuple[str, ...]):
        self._client_factory = client_factory
        self._instances = instance_names

    async def run_once(self, instance: str) -> WatchdogStats:
        result = await self._client_factory(instance).execute_kw(
            "picking.assistant.integration.job",
            "api_recover_stalled_jobs",
            [200],
        )
        return WatchdogStats(recovered=int(result.get("recovered", 0)))


def build_outbox_dispatcher(
    candidate: Settings,
    client_factory,
    targets: dict[str, str],
) -> OutboxDispatcher:
    # Senders always sign with the ACTIVE backend-to-n8n key; only receivers
    # accept active AND previous during rotation. The previous key is
    # deliberately never handed to the transport.
    signing_key = HmacKey(
        candidate.pwr_backend_to_n8n_active_key_id,
        decode_secret_b64(
            "PWR_BACKEND_TO_N8N_ACTIVE_SECRET_B64",
            candidate.pwr_backend_to_n8n_active_secret_b64,
        ),
    )
    transport = SignedWebhookTransport(
        base_url=candidate.n8n_webhook_base.removesuffix("/webhook"),
        native_header_secret=candidate.n8n_webhook_secret,
        signing_key=signing_key,
    )
    instances = tuple(get_instance_registry(candidate))
    return OutboxDispatcher(
        client_factory=client_factory,
        instance_names=instances,
        transport=transport,
        targets=targets,
        worker_id=f"{socket.gethostname()}:{os.getpid()}",
        poll_seconds=candidate.dispatcher_poll_seconds,
        lease_seconds=candidate.dispatcher_lease_seconds,
        batch_size=candidate.dispatcher_batch_size,
    )


def build_integration_watchdog(
    candidate: Settings,
    client_factory,
) -> IntegrationWatchdog:
    return IntegrationWatchdog(
        client_factory=client_factory,
        instance_names=tuple(get_instance_registry(candidate)),
    )
