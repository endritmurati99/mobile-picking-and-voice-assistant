import asyncio
import base64
import os
import socket

import pytest

from app.config import Settings
from app.services.outbox_dispatcher import (
    DispatchStats,
    IntegrationWatchdog,
    OutboxDispatcher,
    WatchdogStats,
    build_integration_watchdog,
    build_outbox_dispatcher,
)
from app.services.signed_webhook_transport import (
    SignedWebhookTransport,
    WebhookAcceptanceResult,
)

EVENT = {
    "event_id": "a4ff5ca2-4546-4ea4-8e6c-b75bc003ca32",
    "job_id": "4ddb2442-e58a-47fe-9a6f-1ec1d779ef88",
    "event_name": "quality.assessment.requested.v1",
    "envelope_text": '{"schema_version":"v2","message":"Gruess dich"}',
    "payload_fingerprint": "a" * 64,
    "delivery_generation": 1,
    "attempt_count": 1,
}


class FakeOdoo:
    def __init__(self):
        self.pending = [dict(EVENT)]
        self.acked = []
        self.nacked = []
        self.recover_calls = []

    async def execute_kw(self, model, method, args, kwargs=None):
        if method == "api_lease_due":
            return [self.pending.pop(0)] if self.pending else []
        if method == "api_ack_delivery":
            self.acked.append(tuple(args))
            return {"state": "delivered"}
        if method == "api_nack_delivery":
            self.nacked.append(tuple(args))
            return {"state": "pending"}
        if method == "api_recover_stalled_jobs":
            self.recover_calls.append((model, tuple(args)))
            return {"recovered": 2}
        raise AssertionError((model, method, args))


class FakeTransport:
    def __init__(self, accepted=True):
        self.accepted = accepted
        self.calls = []

    async def deliver_event(self, **kwargs):
        self.calls.append(kwargs)
        return WebhookAcceptanceResult(
            accepted=self.accepted,
            event_id=kwargs["event_id"],
            status_code=200 if self.accepted else None,
            error_code=None if self.accepted else "transport_error",
            error_message=None if self.accepted else "connection failed",
        )


TARGETS = {
    "quality.assessment.requested.v1": "/webhook/quality-assessment-v2"
}


def make_dispatcher(odoo, transport, targets=None, worker_id="worker-a"):
    return OutboxDispatcher(
        client_factory=lambda _name: odoo,
        instance_names=("o19",),
        transport=transport,
        targets=TARGETS if targets is None else targets,
        worker_id=worker_id,
    )


@pytest.mark.asyncio
async def test_dispatcher_acks_only_matching_acceptance_and_keeps_raw_body():
    odoo = FakeOdoo()
    transport = FakeTransport()
    dispatcher = OutboxDispatcher(
        client_factory=lambda name: odoo,
        instance_names=("o19",),
        transport=transport,
        targets={
            "quality.assessment.requested.v1":
                "/webhook/quality-assessment-v2"
        },
        worker_id="worker-a",
    )
    stats = await dispatcher.run_once("o19")
    assert stats.delivered == 1
    assert odoo.acked[0][0] == EVENT["event_id"]
    assert transport.calls[0]["raw_body"] == EVENT["envelope_text"].encode("utf-8")


@pytest.mark.asyncio
async def test_new_dispatcher_instance_resumes_persistent_pending_event():
    odoo = FakeOdoo()
    first = OutboxDispatcher(
        client_factory=lambda _name: odoo,
        instance_names=("o19",),
        transport=FakeTransport(accepted=False),
        targets={"quality.assessment.requested.v1": "/webhook/quality-assessment-v2"},
        worker_id="worker-before-restart",
    )
    await first.run_once("o19")
    assert odoo.nacked
    odoo.pending = [dict(EVENT, attempt_count=2)]
    second_transport = FakeTransport(accepted=True)
    second = OutboxDispatcher(
        client_factory=lambda _name: odoo,
        instance_names=("o19",),
        transport=second_transport,
        targets={"quality.assessment.requested.v1": "/webhook/quality-assessment-v2"},
        worker_id="worker-after-restart",
    )
    assert (await second.run_once("o19")).delivered == 1


@pytest.mark.asyncio
async def test_rejected_delivery_is_nacked_with_transport_error_never_acked():
    odoo = FakeOdoo()
    dispatcher = make_dispatcher(odoo, FakeTransport(accepted=False))
    stats = await dispatcher.run_once("o19")
    assert stats == DispatchStats(leased=1, delivered=0, deferred=1)
    assert not odoo.acked
    assert odoo.nacked == [
        (
            EVENT["event_id"],
            "worker-a",
            "transport_error",
            "connection failed",
        )
    ]


@pytest.mark.asyncio
async def test_unregistered_event_is_nacked_without_transport_call():
    odoo = FakeOdoo()
    transport = FakeTransport()
    dispatcher = make_dispatcher(odoo, transport, targets={})
    stats = await dispatcher.run_once("o19")
    assert stats == DispatchStats(leased=1, delivered=0, deferred=1)
    assert transport.calls == []
    assert not odoo.acked
    assert odoo.nacked[0][2] == "unregistered_event_target"


@pytest.mark.asyncio
async def test_run_loop_stops_promptly_on_stop_event():
    odoo = FakeOdoo()
    dispatcher = make_dispatcher(odoo, FakeTransport())
    stop = asyncio.Event()
    task = asyncio.create_task(dispatcher.run(stop))
    await asyncio.sleep(0)
    stop.set()
    await asyncio.wait_for(task, timeout=1.0)
    assert odoo.acked  # the first cycle ran before the stop


@pytest.mark.asyncio
async def test_run_loop_survives_a_failing_instance_cycle():
    class ExplodingOdoo:
        def __init__(self):
            self.calls = 0

        async def execute_kw(self, model, method, args, kwargs=None):
            self.calls += 1
            raise RuntimeError("odoo down")

    odoo = ExplodingOdoo()
    dispatcher = OutboxDispatcher(
        client_factory=lambda _name: odoo,
        instance_names=("o19",),
        transport=FakeTransport(),
        targets=TARGETS,
        worker_id="worker-a",
        poll_seconds=0.01,
    )
    stop = asyncio.Event()
    task = asyncio.create_task(dispatcher.run(stop))
    await asyncio.sleep(0.05)
    stop.set()
    await asyncio.wait_for(task, timeout=1.0)
    assert odoo.calls >= 2  # kept cycling despite the exception


@pytest.mark.asyncio
async def test_watchdog_run_once_returns_recovered_count():
    odoo = FakeOdoo()
    watchdog = IntegrationWatchdog(
        client_factory=lambda _name: odoo, instance_names=("o19",)
    )
    stats = await watchdog.run_once("o19")
    assert stats == WatchdogStats(recovered=2)
    assert odoo.recover_calls == [
        ("picking.assistant.integration.job", (200,))
    ]


def _candidate_settings(**overrides) -> Settings:
    values = dict(
        n8n_webhook_base="http://n8n-candidate:5678/webhook",
        n8n_webhook_secret="candidate-native-secret-" + "x" * 32,
        pwr_backend_to_n8n_active_key_id="b2n-candidate",
        pwr_backend_to_n8n_active_secret_b64=base64.b64encode(
            b"c" * 32
        ).decode("ascii"),
        pwr_backend_to_n8n_previous_key_id="b2n-old",
        pwr_backend_to_n8n_previous_secret_b64=base64.b64encode(
            b"p" * 32
        ).decode("ascii"),
        dispatcher_poll_seconds=0.5,
        dispatcher_lease_seconds=33,
        dispatcher_batch_size=7,
    )
    values.update(overrides)
    return Settings(_env_file=None, **values)


def test_build_outbox_dispatcher_reads_only_the_candidate_settings():
    candidate = _candidate_settings()
    client_factory = lambda name: FakeOdoo()  # noqa: E731
    dispatcher = build_outbox_dispatcher(
        candidate, client_factory, dict(TARGETS)
    )
    assert dispatcher._client_factory is client_factory
    assert dispatcher._instances == ("local",)
    assert dispatcher._targets == TARGETS
    assert dispatcher._poll_seconds == 0.5
    assert dispatcher._lease_seconds == 33
    assert dispatcher._batch_size == 7
    assert dispatcher._worker_id == f"{socket.gethostname()}:{os.getpid()}"
    transport = dispatcher._transport
    assert isinstance(transport, SignedWebhookTransport)
    # candidate values, never the module-global settings object
    assert transport._base_url == "http://n8n-candidate:5678"
    assert transport._native_secret == candidate.n8n_webhook_secret
    # senders always sign with the ACTIVE key; the previous key never leaves
    # the receiver side
    assert transport._key.key_id == "b2n-candidate"
    assert transport._key.secret == b"c" * 32


def test_build_integration_watchdog_reads_only_the_candidate_settings():
    candidate = _candidate_settings(
        odoo_instances_json=(
            '{"o19": {"url": "http://x", "db": "masterfischer_o19_trial"}}'
        )
    )
    watchdog = build_integration_watchdog(candidate, lambda name: FakeOdoo())
    assert watchdog._instances == ("local", "o19")
