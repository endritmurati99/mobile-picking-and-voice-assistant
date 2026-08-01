"""Echte Datenbank-Races gegen Odoo 19.

Warum das nur live geht: Odoo bindet eine Transaktion an eine Verbindung, und
die hier gemessenen Garantien entstehen aus `FOR UPDATE SKIP LOCKED`, aus
Unique-Constraints und aus dem Serialisierungsverhalten von PostgreSQL unter
REPEATABLE READ. Nichts davon existiert in einem Fake. Ein Test, der beide
Aufrufe ueber DIESELBE Verbindung schickt, misst ebenfalls nichts -- er laeuft
seriell. Deshalb `independent_rpc_clients` mit `max_keepalive_connections=0`.
"""
import asyncio
import uuid

import pytest


@pytest.mark.odoo19_live
@pytest.mark.asyncio
async def test_two_dispatchers_lease_disjoint_union(
    live_config, seeded_twenty_events, rpc_call, independent_rpc_clients
):
    """Zwei Dispatcher, 20 faellige Events, keine Ueberschneidung und kein Verlust.

    Disjunkt allein waere zu schwach: zwei Worker, die je nichts bekommen, sind
    ebenfalls disjunkt. Die Vereinigung muss die volle Menge sein.
    """
    first, second = independent_rpc_clients
    leases_a, leases_b = await asyncio.gather(
        rpc_call(
            first,
            live_config["ODOO19_LIVE_DB_A"],
            "picking.assistant.outbox",
            "api_lease_due",
            ["worker-a", 20, 60],
        ),
        rpc_call(
            second,
            live_config["ODOO19_LIVE_DB_A"],
            "picking.assistant.outbox",
            "api_lease_due",
            ["worker-b", 20, 60],
        ),
    )
    ids_a = {item["event_id"] for item in leases_a}
    ids_b = {item["event_id"] for item in leases_b}
    assert ids_a.isdisjoint(ids_b)
    assert ids_a | ids_b == set(seeded_twenty_events)


@pytest.mark.odoo19_live
@pytest.mark.asyncio
async def test_acceptance_race_starts_exactly_one_processing_attempt(
    live_config, seeded_event, rpc_call, independent_rpc_clients
):
    """Zwei gleichzeitige Annahmen desselben Events: genau EINE verarbeitet.

    Beide Aufrufe sind gueltig und beide bekommen eine Antwort -- der
    Unterschied liegt allein in `process`. Ein Aufruf, der stattdessen einen
    Fehler bekaeme, waere ein anderes (schlechteres) Verhalten: n8n wuerde ihn
    wiederholen.
    """
    first, second = independent_rpc_clients
    common = [
        seeded_event["event_id"],
        seeded_event["job_id"],
        seeded_event["fingerprint"],
        "b2n-live",
    ]
    results = await asyncio.gather(
        rpc_call(
            first,
            live_config["ODOO19_LIVE_DB_A"],
            "picking.assistant.event.receipt",
            "api_accept_event",
            [*common, str(uuid.uuid4()), 1, "n2b-live", str(uuid.uuid4())],
        ),
        rpc_call(
            second,
            live_config["ODOO19_LIVE_DB_A"],
            "picking.assistant.event.receipt",
            "api_accept_event",
            [*common, str(uuid.uuid4()), 1, "n2b-live", str(uuid.uuid4())],
        ),
    )
    assert sorted(result["process"] for result in results) == [False, True]


@pytest.mark.odoo19_live
@pytest.mark.asyncio
async def test_concurrent_scoped_reserve_yields_one_row(
    live_config, rpc_call, independent_rpc_clients
):
    """Zwei gleichzeitige Reservierungen desselben Schluessels im selben Scope.

    Erwartung: genau ein `reserved`, der andere sieht `pending` oder `replay` --
    und es entsteht GENAU EINE Zeile. Die Zeilenzahl ist der eigentliche Punkt:
    zwei Zeilen mit demselben Schluessel wuerden bedeuten, dass der
    Unique-Constraint den Scope nicht enthaelt, und der zweite Aufruf haette die
    Geschaeftswirkung ein zweites Mal ausgeloest.

    Diese Race wurde im Cutover einmal falsch behandelt: nach einer
    Unique-Verletzung ist unter REPEATABLE READ die Zeile des Gewinners fuer
    diese Transaktion unsichtbar, ein Re-SELECT-Retry laeuft also ewig.
    """
    first, second = independent_rpc_clients
    key = f"live-gate-{uuid.uuid4()}"
    scope = "user:live-gate"
    args = ["/api/live/gate", key, "fingerprint-live", scope]

    results = await asyncio.gather(
        rpc_call(
            first,
            live_config["ODOO19_LIVE_DB_A"],
            "picking.assistant.idempotency",
            "api_reserve_request",
            args,
        ),
        rpc_call(
            second,
            live_config["ODOO19_LIVE_DB_A"],
            "picking.assistant.idempotency",
            "api_reserve_request",
            args,
        ),
    )
    states = sorted(result["state"] for result in results)
    assert states.count("reserved") == 1, states
    assert states[0] in ("pending", "replay", "reserved"), states

    rows = await rpc_call(
        first,
        live_config["ODOO19_LIVE_DB_A"],
        "picking.assistant.idempotency",
        "search_count",
        [[["key", "=", key], ["principal_scope", "=", scope]]],
    )
    assert rows == 1


@pytest.mark.odoo19_live
@pytest.mark.asyncio
async def test_generation_rollover_rejects_the_stale_lease(
    live_config, seeded_event, rpc_call, independent_rpc_clients
):
    """Watchdog-Rollover: der Callback der ALTEN Generation darf nicht wirken.

    Nach `_recover_expired_lease` traegt der Job Generation 2 und ein neues
    Lease-Token. Ein spaet eintreffender Callback der Generation 1 ist genau der
    Fall, den ein abgestuerzter und neu gestarteter Worker erzeugt -- er darf
    den Job nicht terminal machen, sonst gibt es die Geschaeftswirkung zweimal.
    Am Ende steht GENAU EIN terminaler Job.
    """
    first, second = independent_rpc_clients
    database = live_config["ODOO19_LIVE_DB_A"]

    job_before = await rpc_call(
        first,
        database,
        "picking.assistant.integration.job",
        "api_get_job",
        [seeded_event["job_id"]],
    )
    assert job_before["delivery_generation"] >= 2, (
        "the seed must have driven this job through a watchdog recovery; "
        f"generation is {job_before['delivery_generation']}"
    )

    stale = await rpc_call(
        second,
        database,
        "picking.assistant.callback.receipt",
        "api_apply_callback",
        [
            {
                "job_id": seeded_event["job_id"],
                "delivery_generation": 1,
                "processing_lease_token": seeded_event["stale_lease_token"],
                "status": "succeeded",
            },
            f"stale-{uuid.uuid4()}",
            "n2b-live",
            str(uuid.uuid4()),
        ],
    )
    assert stale.get("applied") is False, stale

    job_after = await rpc_call(
        first,
        database,
        "picking.assistant.integration.job",
        "api_get_job",
        [seeded_event["job_id"]],
    )
    assert job_after["delivery_generation"] == job_before["delivery_generation"]
    assert job_after["state"] == job_before["state"]
