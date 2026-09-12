#!/usr/bin/env python3
"""T8: isolated Odoo outbox retry proof.

Run this only inside ``bachelor-eval-backend``.  It uses the actual
``OdooClient`` and ``OutboxDispatcher`` against database ``evaluation``.
The only injected boundary is the dispatcher's HTTP transport: httpx's
MockTransport first raises ConnectError, then returns the exact v2 acceptance
body.  MockTransport cannot open a network connection.

Safety rule: before leasing, refuse to run if *any* pending or leased outbox
row is not a selected EVAL-20260910 quality-alert event.  ``api_lease_due``
has no domain argument, so this conservative guard is the minimum safe way to
use the real lease RPC without touching copied production-like work.
"""
from __future__ import annotations

import asyncio
import json
from dataclasses import asdict

import httpx

from app.models.webhook_security import HmacKey
from app.services.odoo_client import OdooClient
from app.services.outbox_dispatcher import OutboxDispatcher
from app.services.signed_webhook_transport import SignedWebhookTransport


MARKER = "EVAL-20260910-"
EVENT_NAME = "quality.assessment.requested.v1"
WORKER_ID = "evaluation-t8-outbox"
RETRY_WAIT_SECONDS = 11  # Odoo's first frozen outbox backoff is 10 seconds.


def _relation_id(value: object) -> int | None:
    return int(value[0]) if isinstance(value, list) and value else None


async def _search(client: OdooClient, model: str, domain: list, fields: list[str]) -> list[dict]:
    return await client.search_read(model, domain, fields, limit=500)


async def _fixtures(client: OdooClient) -> tuple[list[dict], list[dict], list[dict]]:
    alerts = await _search(
        client,
        "quality.alert.custom",
        [("description", "ilike", MARKER)],
        ["id", "name", "description", "picking_id"],
    )
    if not alerts:
        raise AssertionError("no EVAL-20260910 quality alerts found")
    alert_ids = [int(alert["id"]) for alert in alerts]
    jobs = await _search(
        client,
        "picking.assistant.integration.job",
        [("aggregate_model", "=", "quality.alert.custom"), ("aggregate_res_id", "in", alert_ids)],
        ["id", "job_id", "aggregate_res_id", "state"],
    )
    job_ids = [int(job["id"]) for job in jobs]
    if not job_ids:
        raise AssertionError("EVAL alerts have no integration jobs")
    rows = await _search(
        client,
        "picking.assistant.outbox",
        [("job_record_id", "in", job_ids), ("event_name", "=", EVENT_NAME)],
        ["id", "event_id", "job_record_id", "event_name", "state", "attempt_count", "last_error_code"],
    )
    if not rows:
        raise AssertionError("EVAL alerts have no quality-assessment outbox rows")
    return alerts, jobs, rows


async def _guard_only_synthetic_active_rows(client: OdooClient, selected: list[dict]) -> None:
    selected_ids = {int(row["id"]) for row in selected}
    active = await _search(
        client,
        "picking.assistant.outbox",
        [("state", "in", ["pending", "leased"])],
        ["id", "event_name", "state"],
    )
    unsafe = [row for row in active if int(row["id"]) not in selected_ids]
    if unsafe:
        # IDs/counts only: no copied event payload, correlation ID, or private text.
        raise AssertionError(
            f"refusing to lease {len(unsafe)} non-fixture active outbox row(s); "
            f"ids={[int(row['id']) for row in unsafe]}"
        )
    wrong_state = [row for row in selected if row["state"] != "pending"]
    if wrong_state:
        raise AssertionError("selected EVAL outbox rows must start pending")


async def _assert_linked_pickings_exist(client: OdooClient, alerts: list[dict]) -> None:
    picking_ids = sorted(
        picking_id
        for alert in alerts
        if (picking_id := _relation_id(alert.get("picking_id"))) is not None
    )
    if not picking_ids:
        raise AssertionError("T8 requires at least one EVAL alert linked to a synthetic picking")
    pickings = await _search(client, "stock.picking", [("id", "in", picking_ids)], ["id"])
    if {int(row["id"]) for row in pickings} != set(picking_ids):
        raise AssertionError("linked synthetic picking disappeared during failed delivery")


def _mock_transport(mode: str) -> SignedWebhookTransport:
    async def handler(request: httpx.Request) -> httpx.Response:
        if mode == "fail":
            raise httpx.ConnectError("evaluation injected transport failure", request=request)
        event_id = request.headers.get("Idempotency-Key", "")
        return httpx.Response(200, json={"accepted": True, "event_id": event_id})

    # Test-only key and native secret: these leave this process only as headers
    # consumed by MockTransport. They are not project credentials.
    return SignedWebhookTransport(
        base_url="http://evaluation-mock.invalid",
        native_header_secret="evaluation-test-only",
        signing_key=HmacKey("evaluation-test", b"E" * 32),
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )


async def _run(mode: str, client: OdooClient) -> dict:
    transport = _mock_transport(mode)
    dispatcher = OutboxDispatcher(
        client_factory=lambda _instance: client,
        instance_names=("evaluation",),
        transport=transport,
        targets={EVENT_NAME: "/webhook/evaluation-outbox"},
        worker_id=WORKER_ID,
        lease_seconds=60,
        batch_size=50,
    )
    try:
        return asdict(await dispatcher.run_once("evaluation"))
    finally:
        await transport._client.aclose()  # test-owned MockTransport client


async def main() -> dict:
    client = OdooClient()
    try:
        alerts, jobs, before = await _fixtures(client)
        await _guard_only_synthetic_active_rows(client, before)
        await _assert_linked_pickings_exist(client, alerts)

        failed_stats = await _run("fail", client)
        _, _, after_failure = await _fixtures(client)
        before_attempts = {int(row["id"]): int(row["attempt_count"]) for row in before}
        for row in after_failure:
            assert row["state"] == "pending", "failed delivery must be scheduled for retry"
            assert int(row["attempt_count"]) == before_attempts[int(row["id"])] + 1
            assert row["last_error_code"] == "transport_error"

        # Read the aggregate records after the failure: their existence is the
        # T8 invariant.  No alert/picking write occurs in this script.
        alerts_after_failure, jobs_after_failure, _ = await _fixtures(client)
        assert {int(row["id"]) for row in alerts_after_failure} == {int(row["id"]) for row in alerts}
        assert {int(row["id"]) for row in jobs_after_failure} == {int(row["id"]) for row in jobs}
        await _assert_linked_pickings_exist(client, alerts_after_failure)

        await asyncio.sleep(RETRY_WAIT_SECONDS)
        delivered_stats = await _run("accept", client)
        _, _, after_delivery = await _fixtures(client)
        for row in after_delivery:
            assert row["state"] == "delivered", "matching accepted event ID must acknowledge delivery"
            assert int(row["attempt_count"]) == before_attempts[int(row["id"])] + 2
            assert not row["last_error_code"]

        return {
            "test": "T8-outbox-retry",
            "database": "evaluation",
            "fixture_marker": MARKER,
            "event_name": EVENT_NAME,
            "fixture_counts": {"alerts": len(alerts), "jobs": len(jobs), "outbox_events": len(before)},
            "assertions": {
                "real_odoo_rpc": True,
                "alert_and_linked_picking_persist_after_failed_delivery": True,
                "failure_sets_pending_retry_and_increments_attempt": True,
                "retry_with_matching_acceptance_echo_sets_delivered": True,
            },
            "injected_boundary": {
                "component": "SignedWebhookTransport HTTP client",
                "failure": "httpx.ConnectError via httpx.MockTransport",
                "retry_response": "HTTP 200 {accepted: true, event_id: request Idempotency-Key}",
                "outgoing_network": False,
            },
            "dispatcher_stats": {"failure": failed_stats, "retry": delivered_stats},
        }
    finally:
        await client._client.aclose()  # OdooClient owns this HTTP client.


if __name__ == "__main__":
    try:
        print(json.dumps(asyncio.run(main()), sort_keys=True))
    except Exception as exc:
        # Keep failure evidence useful without emitting envelopes, bodies, credentials, or tracebacks.
        print(json.dumps({"test": "T8-outbox-retry", "status": "failed", "error_type": type(exc).__name__}, sort_keys=True))
        raise SystemExit(1)
