"""Lease-driven outbox dispatcher and integration watchdog.

The dispatcher never builds or reserializes an envelope: it leases due outbox
rows from Odoo (Task 8 `api_lease_due`), hands the STORED envelope bytes to
the signed transport, and acks/nacks under the same worker lease. Double
delivery is fenced on the Odoo side (`_owned_lease` ownership + expiry under
`FOR UPDATE`); this process never acknowledges an event the transport did not
report as accepted with a matching event-ID echo.

DELIVERY CONTRACT — AT-LEAST-ONCE, NOT EXACTLY-ONCE:
A crash, timeout, or lost lease AFTER n8n performed its side effect but
BEFORE `api_ack_delivery` commits leads to lease expiry and a second POST of
the same event. Each redelivery carries a FRESH nonce, timestamp, and
signature, so signature-level replay defence will NOT (and must not) catch
it. The CONSUMER is therefore responsible for deduplication: the n8n-side
ingress must dedupe on `event_id` + `payload_fingerprint` atomically BEFORE
executing the workflow and return the same acceptance body for a replay
(cross-task obligation on Task 15, which owns the n8n workflows). Task 8's
Odoo receipt dedup covers the backend side only — it does not make n8n
workflow side effects idempotent.

Two rules in `run_once` protect delivered events from being falsely failed:
each leased row is handled independently (one row's ack/nack failure never
aborts its siblings), and a row whose HTTP delivery succeeded is NEVER
nacked — losing the lease afterwards must not consume attempts or push an
already-delivered event towards dead-lettering.

The pure construction functions (`build_outbox_dispatcher`,
`build_integration_watchdog`) read ONLY the candidate `Settings` they are
given — Task 16 builds one graph per app from them.
"""
from __future__ import annotations

import asyncio
import logging
import os
import socket
import time
from dataclasses import dataclass
from typing import Callable

from app.config import Settings, decode_secret_b64, get_instance_registry, read_secret
from app.models.webhook_security import HmacKey
from app.services.signed_webhook_transport import SignedWebhookTransport

logger = logging.getLogger(__name__)

# No NEW delivery may start when less than this remains of the lease window:
# a delivery whose ack lands after lease expiry has lost ownership, and the
# combination of transport timeouts (connect 1s + write 10s + read 10s) and
# the Odoo ack RPC must fit into the remainder. Rows left untouched are safe
# — nothing was sent for them, their lease simply expires and a later cycle
# re-leases them.
_LEASE_SAFETY_MARGIN_SECONDS = 15.0


@dataclass(frozen=True)
class DispatchStats:
    leased: int = 0
    delivered: int = 0
    deferred: int = 0
    # delivered-but-ack-lost rows: NOT failures, the event reached n8n and
    # will be redelivered + consumer-deduped (see module docstring).
    ack_failed: int = 0
    # rows returned untouched because the lease work budget ran out.
    skipped: int = 0


@dataclass(frozen=True)
class WatchdogStats:
    recovered: int = 0
    # Candidates the Odoo batch refused to recover -- today practically only
    # a receipt whose outbox row is gone (Task 6, finding #11's watchdog
    # side). A persistently non-zero value is exactly what Task 2 justified
    # skip-not-abort with ("something you can alert on"); until this field
    # existed that alert had nowhere to surface outside Odoo's own log.
    skipped: int = 0


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
        now_monotonic: Callable[[], float] = time.monotonic,
    ):
        self._client_factory = client_factory
        self._instances = instance_names
        self._transport = transport
        self._targets = targets
        self._worker_id = worker_id
        self._poll_seconds = poll_seconds
        self._lease_seconds = lease_seconds
        self._batch_size = batch_size
        self._now_monotonic = now_monotonic

    async def run_once(self, instance: str) -> DispatchStats:
        odoo = self._client_factory(instance)
        rows = await odoo.execute_kw(
            "picking.assistant.outbox",
            "api_lease_due",
            [self._worker_id, self._batch_size, self._lease_seconds],
        )
        # Work budget: the lease window minus a safety margin (never less
        # than half the window), so that every delivery STARTED here can
        # also be acked before ownership expires.
        budget = max(
            self._lease_seconds - _LEASE_SAFETY_MARGIN_SECONDS,
            self._lease_seconds / 2.0,
        )
        deadline = self._now_monotonic() + budget
        delivered = 0
        deferred = 0
        ack_failed = 0
        skipped = 0
        for index, row in enumerate(rows):
            if self._now_monotonic() >= deadline:
                skipped = len(rows) - index
                logger.warning(
                    "Lease work budget exhausted on %s; leaving %d leased "
                    "rows untouched to expire and be re-leased.",
                    instance,
                    skipped,
                )
                break
            target = self._targets.get(row["event_name"])
            if target is None:
                # Approved event without a landed v2 workflow: defer via the
                # frozen Odoo backoff, never invent a target locally.
                result = None
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
            # Each row is handled independently below: an ack/nack failure
            # is logged and never aborts the remaining leased siblings.
            if accepted:
                delivered += 1
                try:
                    await odoo.execute_kw(
                        "picking.assistant.outbox",
                        "api_ack_delivery",
                        [row["event_id"], self._worker_id, result.event_id],
                    )
                except Exception:
                    # The HTTP delivery SUCCEEDED. A lost lease (or any
                    # other ack failure) must never turn that success into
                    # a failure: no nack, no attempt consumed, no path to
                    # dead-letter. The row stays leased until expiry and is
                    # redelivered; the consumer dedupes (module docstring).
                    ack_failed += 1
                    logger.exception(
                        "Ack failed after successful delivery of %s; "
                        "leaving the row for redelivery.",
                        row["event_id"],
                    )
            else:
                deferred += 1
                try:
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
                except Exception:
                    logger.exception(
                        "Nack failed for %s; the lease will expire and the "
                        "row will be re-leased.",
                        row["event_id"],
                    )
        return DispatchStats(
            leased=len(rows),
            delivered=delivered,
            deferred=deferred,
            ack_failed=ack_failed,
            skipped=skipped,
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
        stats = WatchdogStats(
            recovered=int(result.get("recovered", 0)),
            skipped=int(result.get("skipped", 0)),
        )
        if stats.skipped:
            logger.warning(
                "Watchdog on %s skipped %d stalled job(s) it refused to "
                "recover (likely missing outbox rows)",
                instance,
                stats.skipped,
            )
        return stats


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
            read_secret(
                candidate.pwr_backend_to_n8n_active_secret_b64,
                candidate.pwr_backend_to_n8n_active_secret_file,
            ),
        ),
    )
    transport = SignedWebhookTransport(
        base_url=candidate.n8n_webhook_base.removesuffix("/webhook"),
        native_header_secret=read_secret(
            candidate.n8n_webhook_secret, candidate.n8n_webhook_secret_file
        ),
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
