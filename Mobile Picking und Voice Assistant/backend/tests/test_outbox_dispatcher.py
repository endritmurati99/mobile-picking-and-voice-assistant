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

@pytest.fixture(autouse=True)
def skip_instance_name_check(monkeypatch):
    """Die Startpruefung der Instanznamen spricht echtes Odoo an.

    Diese Datei prueft Lifespan-MECHANIK -- Guard, Task-Aufraeumen, Abbruch --
    und nicht, ob eine Instanz richtig benannt ist. Dass die Pruefung greift,
    beweist `tests/test_instance_name_startup.py`; hier wuerde sie nur einen
    Netzwerkaufruf gegen ein nicht existierendes Odoo erzwingen.
    """
    from app import main as main_module

    async def _accept_all(client_factory, instance_names, **kwargs):
        return None

    monkeypatch.setattr(main_module, "verify_instance_names", _accept_all)


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
        self.recover_skipped = 0

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
            return {"recovered": 2, "skipped": self.recover_skipped}
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
async def test_ack_failure_after_successful_delivery_never_nacks_or_aborts():
    """HTTP 200 then ack raises: the delivered row must NOT be marked failed
    (no nack, no backoff, no dead-letter path) and its sibling rows must
    still be processed."""

    class AckExplodingOdoo(FakeOdoo):
        def __init__(self):
            super().__init__()
            self.pending = [
                dict(EVENT),
                dict(
                    EVENT,
                    event_id="b4ff5ca2-4546-4ea4-8e6c-b75bc003ca33",
                ),
            ]
            self.lease_served = False

        async def execute_kw(self, model, method, args, kwargs=None):
            if method == "api_lease_due":
                if self.lease_served:
                    return []
                self.lease_served = True
                rows, self.pending = self.pending, []
                return rows
            if method == "api_ack_delivery":
                raise RuntimeError("Outbox lease is not owned by this worker.")
            return await super().execute_kw(model, method, args, kwargs)

    odoo = AckExplodingOdoo()
    transport = FakeTransport(accepted=True)
    dispatcher = make_dispatcher(odoo, transport)
    stats = await dispatcher.run_once("o19")
    assert len(transport.calls) == 2  # sibling row was not aborted
    assert stats.leased == 2
    assert stats.delivered == 2  # both HTTP deliveries succeeded
    assert stats.ack_failed == 2
    assert odoo.nacked == []  # a delivered event is never marked failed
    assert odoo.acked == []


@pytest.mark.asyncio
async def test_exhausted_lease_budget_leaves_remaining_rows_untouched():
    """When the safe work budget of the lease window is used up, no NEW
    delivery may start: remaining rows are neither delivered, acked, nor
    nacked — their lease simply expires and a later cycle re-leases them."""

    class TwoRowOdoo(FakeOdoo):
        def __init__(self):
            super().__init__()
            self.pending = [
                dict(EVENT),
                dict(
                    EVENT,
                    event_id="b4ff5ca2-4546-4ea4-8e6c-b75bc003ca33",
                ),
            ]
            self.lease_served = False

        async def execute_kw(self, model, method, args, kwargs=None):
            if method == "api_lease_due":
                if self.lease_served:
                    return []
                self.lease_served = True
                rows, self.pending = self.pending, []
                return rows
            return await super().execute_kw(model, method, args, kwargs)

    # Clock: 0.0 at budget start, 0.0 before row 1, 1000.0 before row 2.
    ticks = iter([0.0, 0.0, 1000.0])
    last = [0.0]

    def fake_monotonic():
        try:
            last[0] = next(ticks)
        except StopIteration:
            pass
        return last[0]

    odoo = TwoRowOdoo()
    transport = FakeTransport(accepted=True)
    dispatcher = OutboxDispatcher(
        client_factory=lambda _name: odoo,
        instance_names=("o19",),
        transport=transport,
        targets=TARGETS,
        worker_id="worker-a",
        lease_seconds=60,
        now_monotonic=fake_monotonic,
    )
    stats = await dispatcher.run_once("o19")
    assert len(transport.calls) == 1
    assert [ack[0] for ack in odoo.acked] == [EVENT["event_id"]]
    assert odoo.nacked == []
    assert stats.leased == 2
    assert stats.delivered == 1
    assert stats.skipped == 1


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
    assert stats == WatchdogStats(recovered=2, skipped=0)
    assert odoo.recover_calls == [
        ("picking.assistant.integration.job", (200,))
    ]


@pytest.mark.asyncio
async def test_watchdog_run_once_carries_skipped_count_through(caplog):
    """Task 6, step 3b: the Odoo RPC's `skipped` count (candidates the batch
    refused to recover, typically an orphaned receipt with no outbox row)
    used to be silently dropped by `WatchdogStats(recovered=...)`. It must
    reach the stats object, and a non-zero value must be logged."""
    odoo = FakeOdoo()
    odoo.recover_skipped = 3
    watchdog = IntegrationWatchdog(
        client_factory=lambda _name: odoo, instance_names=("o19",)
    )
    with caplog.at_level("WARNING"):
        stats = await watchdog.run_once("o19")
    assert stats == WatchdogStats(recovered=2, skipped=3)
    assert any("skipped 3" in message for message in caplog.messages)


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


@pytest.mark.asyncio
async def test_lifespan_constructs_nothing_while_dispatcher_disabled(monkeypatch):
    from app import main as main_module

    def must_not_be_called(_candidate):
        raise AssertionError("dispatcher must not be constructed when disabled")

    monkeypatch.setattr(main_module, "get_outbox_dispatcher", must_not_be_called)
    monkeypatch.setattr(
        main_module, "get_integration_watchdog", must_not_be_called
    )
    lifespan = main_module.build_lifespan(
        _candidate_settings(dispatcher_enabled=False)
    )
    async with lifespan(main_module.app):
        pass


@pytest.mark.asyncio
async def test_lifespan_starts_and_stops_dispatcher_and_watchdog(monkeypatch):
    from app import main as main_module

    events = []

    class FakeDispatcher:
        async def run(self, stop_event):
            events.append("dispatcher-started")
            await stop_event.wait()
            events.append("dispatcher-stopped")

    class FakeWatchdog:
        async def run_once(self, instance):
            events.append(f"watchdog:{instance}")
            return WatchdogStats(recovered=0)

    candidate = _candidate_settings(dispatcher_enabled=True)
    monkeypatch.setattr(
        main_module, "get_outbox_dispatcher", lambda c: FakeDispatcher()
    )
    monkeypatch.setattr(
        main_module, "get_integration_watchdog", lambda c: FakeWatchdog()
    )
    lifespan = main_module.build_lifespan(candidate)
    async with lifespan(main_module.app):
        await asyncio.sleep(0.05)
    assert "dispatcher-started" in events
    assert "dispatcher-stopped" in events
    assert "watchdog:local" in events


@pytest.mark.asyncio
async def test_second_concurrent_lifespan_start_is_refused(monkeypatch):
    """One dispatcher/watchdog pair per process: a second lifespan entered
    while the first is still running must be refused, not silently double
    the dispatcher under the same hostname:pid worker id."""
    from app import main as main_module

    class FakeDispatcher:
        async def run(self, stop_event):
            await stop_event.wait()

    class FakeWatchdog:
        async def run_once(self, instance):
            return WatchdogStats(recovered=0)

    monkeypatch.setattr(
        main_module, "get_outbox_dispatcher", lambda c: FakeDispatcher()
    )
    monkeypatch.setattr(
        main_module, "get_integration_watchdog", lambda c: FakeWatchdog()
    )
    lifespan = main_module.build_lifespan(
        _candidate_settings(dispatcher_enabled=True)
    )
    first = lifespan(main_module.app)
    await first.__aenter__()
    try:
        with pytest.raises(RuntimeError, match="already running"):
            await lifespan(main_module.app).__aenter__()
    finally:
        await first.__aexit__(None, None, None)
    # After a clean shutdown the guard is released and a restart succeeds.
    again = lifespan(main_module.app)
    await again.__aenter__()
    await again.__aexit__(None, None, None)


@pytest.mark.asyncio
async def test_failed_startup_stops_partial_tasks_and_frees_the_guard(monkeypatch):
    """Watchdog construction failing AFTER the dispatcher task was created:
    the half-started pair must be shut down (no orphan task) and the process
    guard must be free so a later start succeeds."""
    from app import main as main_module

    events = []

    class FakeDispatcher:
        async def run(self, stop_event):
            events.append("dispatcher-started")
            await stop_event.wait()
            events.append("dispatcher-stopped")

    monkeypatch.setattr(
        main_module, "get_outbox_dispatcher", lambda c: FakeDispatcher()
    )

    def broken_watchdog(_candidate):
        raise ValueError("watchdog construction boom")

    monkeypatch.setattr(main_module, "get_integration_watchdog", broken_watchdog)
    lifespan = main_module.build_lifespan(
        _candidate_settings(dispatcher_enabled=True)
    )
    with pytest.raises(ValueError, match="watchdog construction boom"):
        await lifespan(main_module.app).__aenter__()
    assert events == ["dispatcher-started", "dispatcher-stopped"]

    # Guard is free: a subsequent healthy start succeeds.
    class FakeWatchdog:
        async def run_once(self, instance):
            return WatchdogStats(recovered=0)

    monkeypatch.setattr(
        main_module, "get_integration_watchdog", lambda c: FakeWatchdog()
    )
    healthy = lifespan(main_module.app)
    await healthy.__aenter__()
    await healthy.__aexit__(None, None, None)


@pytest.mark.asyncio
async def test_cancelled_shutdown_cancels_tasks_and_frees_the_guard(monkeypatch):
    """Cancellation while awaiting shutdown must still cancel the pair and
    release the guard — otherwise one cancelled shutdown permanently refuses
    every later enabled lifespan in this process."""
    from app import main as main_module

    class HangingDispatcher:
        async def run(self, stop_event):
            await stop_event.wait()
            await asyncio.Event().wait()  # never finishes shutdown on its own

    class FakeWatchdog:
        async def run_once(self, instance):
            return WatchdogStats(recovered=0)

    monkeypatch.setattr(
        main_module, "get_outbox_dispatcher", lambda c: HangingDispatcher()
    )
    monkeypatch.setattr(
        main_module, "get_integration_watchdog", lambda c: FakeWatchdog()
    )
    lifespan = main_module.build_lifespan(
        _candidate_settings(dispatcher_enabled=True)
    )

    async def runner():
        async with lifespan(main_module.app):
            pass  # shutdown begins immediately and hangs in the dispatcher

    task = asyncio.create_task(runner())
    await asyncio.sleep(0.05)  # let it reach the hanging shutdown await
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    # Guard is free and no orphan task blocks a fresh start.
    class CleanDispatcher:
        async def run(self, stop_event):
            await stop_event.wait()

    monkeypatch.setattr(
        main_module, "get_outbox_dispatcher", lambda c: CleanDispatcher()
    )
    healthy = lifespan(main_module.app)
    await healthy.__aenter__()
    await healthy.__aexit__(None, None, None)


def test_build_integration_watchdog_reads_only_the_candidate_settings():
    candidate = _candidate_settings(
        odoo_instances_json=(
            '{"o19": {"url": "http://x", "db": "masterfischer_o19_trial"}}'
        )
    )
    watchdog = build_integration_watchdog(candidate, lambda name: FakeOdoo())
    assert watchdog._instances == ("local", "o19")
