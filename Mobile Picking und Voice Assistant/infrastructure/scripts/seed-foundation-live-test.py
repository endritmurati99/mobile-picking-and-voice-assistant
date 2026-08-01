"""Seed fuer die Live-Gates -- laeuft in `odoo shell`, NICHT ueber RPC.

    odoo shell -d DATENBANK < infrastructure/scripts/seed-foundation-live-test.py

Warum Odoo-Shell und kein RPC-Client: der Seed legt Benutzer an und setzt
Passwoerter. Es gibt bewusst keinen Seed-Endpunkt -- ein Endpunkt, der
Benutzer anlegen kann, waere in production genau die Hintertuer, gegen die das
ganze Programm arbeitet. Die Shell laeuft als der normale
Odoo-Anwendungsdienst, nicht als Datenbank-Superuser.

Eingaben ueber die kurzlebige Prozessumgebung:

* `PWR_SEED_INSTANCE`     kanonischer Instanzname dieser Datenbank
* `PWR_TEST_SERVICE_PASSWORD`  Testpasswort, vom Host aus einer 0400-Datei

Ausgabe: **genau eine** Zeile auf stdout mit dem Praefix `PWR_SEED_METADATA=`.
Odoo-Logs duerfen sie umgeben; der Host verlangt genau einen Marker je Aufruf.
Die Zeile enthaelt nur IDs und Zaehler -- keine Passwoerter, keine Tokens, keine
Event-Bodies, keine Artefaktbytes.

Beide Datenbanken bekommen ABSICHTLICH dieselbe numerische Aggregat-ID. Waeren
sie verschieden, koennte ein Routing-Fehler unentdeckt bleiben, weil die
falsche Datenbank die ID gar nicht kennt.
"""
import hashlib
import json
import os
import sys
import uuid

# `env` stellt die Odoo-Shell bereit.
env = env  # noqa: F821  (Shell-Global)

INSTANCE = os.environ.get("PWR_SEED_INSTANCE")
PASSWORD = os.environ.get("PWR_TEST_SERVICE_PASSWORD")
if not INSTANCE or not PASSWORD:
    print(
        "seed: PWR_SEED_INSTANCE and PWR_TEST_SERVICE_PASSWORD are required",
        file=sys.stderr,
    )
    raise SystemExit(2)

# Feste Aggregat-ID, in BEIDEN Datenbanken identisch.
AGGREGATE_REF = "pwr.foundation.live.aggregate"
TWENTY = 20
# Nur die primaere Instanz traegt die Nebenlaeufigkeits- und Restart-Saat.
IS_PRIMARY = INSTANCE.endswith("-a") or INSTANCE.endswith("_a")


def _ensure_user(login, name, groups):
    user = env["res.users"].sudo().search([("login", "=", login)], limit=1)
    values = {
        "name": name,
        "login": login,
        "password": PASSWORD,
        "groups_id": [(6, 0, [env.ref(group).id for group in groups])],
    }
    if user:
        user.write(values)
        return user
    return env["res.users"].sudo().create(values)


def _ensure_aggregate():
    """Ein Picking als Aggregat, mit fester externer ID -- damit beide
    Datenbanken dieselbe numerische ID vergeben."""
    existing = env.ref(AGGREGATE_REF, raise_if_not_found=False)
    if existing:
        return existing
    picking_type = env["stock.picking.type"].sudo().search(
        [("code", "=", "outgoing")], limit=1
    )
    picking = env["stock.picking"].sudo().create(
        {
            "picking_type_id": picking_type.id,
            "origin": "pwr-foundation-live",
        }
    )
    env["ir.model.data"].sudo().create(
        {
            "module": AGGREGATE_REF.split(".")[0],
            "name": AGGREGATE_REF.split(".", 1)[1],
            "model": "stock.picking",
            "res_id": picking.id,
            "noupdate": True,
        }
    )
    return picking


def main():
    _ensure_user("pwr-live-service", "PWR Live Service", ["base.group_user"])
    _ensure_user("pwr-live-picker", "PWR Live Picker", ["stock.group_stock_user"])
    _ensure_user(
        "pwr-live-supervisor", "PWR Live Supervisor", ["stock.group_stock_manager"]
    )

    aggregate = _ensure_aggregate()
    jobs = env["picking.assistant.integration.job"].sudo()

    def enqueue(job_type, event_name, job_id, event_id):
        """Alle Pflichtfelder von `_enqueue_job_event` explizit.

        Der Envelope wird EINMAL serialisiert und sein Fingerprint aus genau
        diesen Bytes gebildet -- ein zweites `json.dumps` fuer den Fingerprint
        waere die klassische Falle: er gaelte dann fuer andere Bytes als die
        gespeicherten.
        """
        envelope = json.dumps(
            {
                "schema_version": "v2",
                "event_id": event_id,
                "event_name": event_name,
                "odoo_instance": INSTANCE,
                "job_id": job_id,
                "aggregate_model": "stock.picking",
                "aggregate_res_id": aggregate.id,
                "aggregate_revision": 1,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        fingerprint = hashlib.sha256(envelope.encode("utf-8")).hexdigest()
        jobs._enqueue_job_event(
            job_type=job_type,
            aggregate_model="stock.picking",
            aggregate_res_id=aggregate.id,
            aggregate_revision=1,
            event_id=event_id,
            event_name=event_name,
            envelope_text=envelope,
            payload_fingerprint=fingerprint,
            correlation_id=str(uuid.uuid4()),
            job_id=job_id,
        )
        return fingerprint

    # Ein Isolations-Job je Datenbank -- gleiche Aggregat-ID, eigene Job-UUID.
    isolation_job_id = str(uuid.uuid4())
    isolation_event_id = str(uuid.uuid4())
    enqueue(
        "foundation.live.isolation",
        "foundation.live.isolation",
        isolation_job_id,
        isolation_event_id,
    )

    # 20 faellige Events fuer den Nebenlaeufigkeitstest -- nur in Datenbank A.
    twenty = []
    restart_event = {}
    if IS_PRIMARY:
        for _ in range(TWENTY):
            event_id = str(uuid.uuid4())
            enqueue(
                "foundation.live.concurrency",
                "foundation.live.concurrency",
                str(uuid.uuid4()),
                event_id,
            )
            twenty.append(event_id)

        # Ein eigenes Event fuer die Annahme-Race und den Generationswechsel.
        # `stale_lease_token` ist ABSICHTLICH ein Token, das nie gueltig war:
        # der Generationstest behauptet, dass ein Callback der alten Generation
        # abgewiesen wird, und ein zufaellig doch gueltiges Token wuerde das
        # Gegenteil beweisen, ohne dass es auffiele.
        restart_job_id = str(uuid.uuid4())
        restart_event_id = str(uuid.uuid4())
        fingerprint = enqueue(
            "foundation.live.restart",
            "foundation.live.restart",
            restart_job_id,
            restart_event_id,
        )
        restart_event = {
            "job_id": restart_job_id,
            "event_id": restart_event_id,
            "fingerprint": fingerprint,
            "processing_lease_token": "pwr-live-lease-" + uuid.uuid4().hex,
            "stale_lease_token": "pwr-live-stale-" + uuid.uuid4().hex,
        }

    metadata = {
        "instance": INSTANCE,
        "database": env.cr.dbname,
        "aggregate_id": aggregate.id,
        "job_id": isolation_job_id,
        "event_id": isolation_event_id,
        "twenty_event_ids": twenty,
        "restart_event": restart_event,
        "counts": {
            "jobs": jobs.search_count([]),
            "outbox": env["picking.assistant.outbox"].sudo().search_count([]),
        },
    }
    env.cr.commit()
    print("PWR_SEED_METADATA=" + json.dumps(metadata, sort_keys=True))


main()
