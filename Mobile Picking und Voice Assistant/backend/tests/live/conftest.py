"""Fixtures fuer die Live-Gates (Foundation Task 17).

Diese Datei hat eine einzige Aufgabe: **es darf keinen Weg geben, auf dem ein
Live-Gate ohne die echte Umgebung gruen wird.** Deshalb gilt hier durchgaengig:

* Fehlende Umgebung ist ein `pytest.fail`, **kein** `pytest.skip`. Ein Skip liest
  sich in jedem CI-Bericht wie ein bestandener Lauf, und genau diese Tests
  existieren, weil sie gegen Mocks nicht bestehen koennen.
* Keine Fixture gibt jemals einen Mock, einen Default oder eine `local`-Instanz
  zurueck. Ein stiller `local`-Fallback wuerde die Zwei-Datenbank-Isolation --
  das, was hier gemessen werden soll -- unbemerkt aushebeln.
* Ein RPC-`error` ist ein Fehlschlag, kein leeres Ergebnis. Sonst laesst sich ein
  Test durch eine kaputte Verbindung "bestehen".
"""
import base64
import json
import os
import stat
import time
from pathlib import Path
from typing import NoReturn
from uuid import uuid4

import httpx
import pytest
import pytest_asyncio

REQUIRED = (
    "ODOO19_LIVE_URL",
    "ODOO19_LIVE_DB_A",
    "ODOO19_LIVE_DB_B",
    "ODOO19_LIVE_USER",
    "ODOO19_LIVE_PASSWORD_FILE",
    "FOUNDATION_API_URL",
    "FOUNDATION_CA_FILE",
    "FOUNDATION_N2B_KEY_ID",
    "FOUNDATION_N2B_SECRET_FILE",
    "FOUNDATION_SEED_METADATA",
)

SEED_SCHEMA = {"instances", "twenty_event_ids", "restart_event"}

# Loopback-Literale. Ein nicht-Loopback-Ziel ueber Klartext-HTTP wird abgelehnt:
# der Live-Backend-Port ist im isolierten Override bewusst nur lokal gebunden,
# und ein Gate, das versehentlich gegen einen LAN-Host laeuft, misst eine andere
# Anlage als die, die es zu pruefen glaubt.
_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})


def _fail_closed(reason: str) -> NoReturn:
    pytest.fail(reason, pytrace=False)


@pytest.fixture(scope="session")
def live_config():
    missing = [name for name in REQUIRED if not os.environ.get(name)]
    if missing:
        _fail_closed(f"live gate requires environment: {', '.join(missing)}")
    config = {name: os.environ[name] for name in REQUIRED}

    api = httpx.URL(config["FOUNDATION_API_URL"])
    if api.scheme == "http" and api.host not in _LOOPBACK_HOSTS:
        _fail_closed(
            "FOUNDATION_API_URL is plain HTTP on a non-loopback host "
            f"({api.host}); the live backend port is loopback-only"
        )
    if api.scheme not in ("http", "https"):
        _fail_closed(f"FOUNDATION_API_URL has an unusable scheme: {api.scheme}")
    if config["ODOO19_LIVE_DB_A"] == config["ODOO19_LIVE_DB_B"]:
        _fail_closed(
            "ODOO19_LIVE_DB_A and ODOO19_LIVE_DB_B name the same database; the "
            "two-instance isolation gate would compare a database with itself"
        )
    return config


def _read_restricted_secret(path_value: str, label: str) -> str:
    path = Path(path_value)
    try:
        mode = path.stat().st_mode
    except OSError as exc:
        _fail_closed(f"{label} is unreadable: {exc}")
    if mode & 0o077:
        _fail_closed(
            f"{label} permissions are too broad ({stat.filemode(mode)}); "
            "a live credential readable by group or others is not a credential"
        )
    return path.read_text(encoding="utf-8").strip()


@pytest.fixture(scope="session")
def seed_metadata(live_config):
    path = Path(live_config["FOUNDATION_SEED_METADATA"])
    if not path.exists():
        _fail_closed(f"seed metadata missing: {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        _fail_closed(f"seed metadata is unreadable: {exc}")
    if not isinstance(data, dict) or set(data) != SEED_SCHEMA:
        _fail_closed(
            "seed metadata schema mismatch: expected exactly "
            f"{sorted(SEED_SCHEMA)}, got {sorted(data) if isinstance(data, dict) else type(data).__name__}"
        )
    return data


@pytest.fixture
def live_service_password(live_config):
    return _read_restricted_secret(
        live_config["ODOO19_LIVE_PASSWORD_FILE"], "ODOO19_LIVE_PASSWORD_FILE"
    )


@pytest.fixture
def n2b_signing_key(live_config):
    raw = _read_restricted_secret(
        live_config["FOUNDATION_N2B_SECRET_FILE"], "FOUNDATION_N2B_SECRET_FILE"
    )
    try:
        secret = base64.b64decode(raw, validate=True)
    except ValueError as exc:
        _fail_closed(f"FOUNDATION_N2B_SECRET_FILE is not valid base64: {exc}")
    if len(secret) < 32:
        _fail_closed(
            "FOUNDATION_N2B_SECRET_FILE decodes to "
            f"{len(secret)} bytes; the signing contract requires at least 32"
        )
    return live_config["FOUNDATION_N2B_KEY_ID"], secret


@pytest_asyncio.fixture
async def independent_rpc_clients(live_config):
    """ZWEI getrennte HTTP-Clients, jeder ohne Keep-Alive.

    Das ist die ganze Pointe der Race-Tests: Odoo bindet eine Transaktion an
    eine Verbindung. Zwei Aufrufe ueber denselben Pool koennen dieselbe
    Verbindung wiederverwenden und laufen dann seriell -- der Test waere gruen,
    ohne je eine Race gemessen zu haben.
    """
    limits = httpx.Limits(max_connections=1, max_keepalive_connections=0)
    async with (
        httpx.AsyncClient(limits=limits, timeout=60.0) as first,
        httpx.AsyncClient(limits=limits, timeout=60.0) as second,
    ):
        yield first, second


async def json_rpc(client, url, service, method, args):
    """JSON-RPC 2.0 mit eigener UUID pro Aufruf.

    Verlangt HTTP 200, lehnt ein `error`-Member ab und liefert ausschliesslich
    `result`. Ein RPC-Fehler, der als `None` zurueckkaeme, wuerde in einem
    Vergleich wie `assert counts == before` als Erfolg durchgehen.
    """
    payload = {
        "jsonrpc": "2.0",
        "method": "call",
        "id": str(uuid4()),
        "params": {"service": service, "method": method, "args": args},
    }
    response = await client.post(url, json=payload)
    if response.status_code != 200:
        _fail_closed(f"JSON-RPC {service}.{method} returned HTTP {response.status_code}")
    body = response.json()
    if "error" in body:
        _fail_closed(f"JSON-RPC {service}.{method} failed: {body['error']}")
    if "result" not in body:
        _fail_closed(f"JSON-RPC {service}.{method} returned no result member")
    return body["result"]


@pytest.fixture
def rpc_call(live_config, live_service_password):
    async def call(client, database, model, method, args):
        uid = await json_rpc(
            client,
            live_config["ODOO19_LIVE_URL"],
            "common",
            "authenticate",
            [database, live_config["ODOO19_LIVE_USER"], live_service_password, {}],
        )
        if not uid:
            _fail_closed(f"live API authentication failed for {database}")
        return await json_rpc(
            client,
            live_config["ODOO19_LIVE_URL"],
            "object",
            "execute_kw",
            [
                database,
                uid,
                live_service_password,
                model,
                method,
                args,
                {},
            ],
        )

    return call


@pytest_asyncio.fixture
async def single_rpc_client():
    async with httpx.AsyncClient(timeout=60.0) as client:
        yield client


@pytest.fixture
def odoo_probe(rpc_call, single_rpc_client, seed_metadata):
    """Lesender Blick in eine Datenbank -- ueber die GEFUEHRTEN API-Methoden.

    `selector` ist entweder `"seeded"` (die Seed-Metadaten dieser Instanz) oder
    eine Job-UUID, die ueber `api_get_job` gelesen wird.
    """

    async def probe(database, selector):
        if selector == "seeded":
            for instance in seed_metadata["instances"]:
                if instance["database"] == database:
                    return dict(instance)
            _fail_closed(f"seed metadata knows no database {database}")
        return await rpc_call(
            single_rpc_client,
            database,
            "picking.assistant.integration.job",
            "api_get_job",
            [selector],
        )

    return probe


@pytest.fixture
def all_database_write_counts(live_config, rpc_call, single_rpc_client):
    """Schreibzaehler beider Datenbanken.

    Wird als Vorher/Nachher-Klammer um einen Aufruf gelegt, der NICHTS schreiben
    darf. `search_count` ist rein lesend.
    """
    models = (
        "picking.assistant.integration.job",
        "picking.assistant.outbox",
        "picking.assistant.event.receipt",
        "picking.assistant.callback.receipt",
    )

    async def counts():
        result = {}
        for database in (live_config["ODOO19_LIVE_DB_A"], live_config["ODOO19_LIVE_DB_B"]):
            for model in models:
                result[f"{database}:{model}"] = await rpc_call(
                    single_rpc_client, database, model, "search_count", [[]]
                )
        return result

    return counts


@pytest.fixture
def seeded_twenty_events(seed_metadata):
    return tuple(seed_metadata["twenty_event_ids"])


@pytest.fixture
def seeded_event(seed_metadata):
    return dict(seed_metadata["restart_event"])


@pytest.fixture
def signed_callback(live_config, n2b_signing_key, seed_metadata):
    """Baut EINEN CallbackEnvelopeV2, serialisiert ihn GENAU EINMAL und
    signiert diese Bytes.

    Ein zweites `json.dumps` fuer die Signatur waere der klassische Fehler: die
    Signatur gilt dann fuer andere Bytes als die gesendeten, und der Test
    bewiese nur, dass zwei Serialisierungen zufaellig uebereinstimmen.
    """
    from app.models.webhook_security import HmacKey
    from app.services.hmac_signing import sign_request

    key_id, secret = n2b_signing_key
    key = HmacKey(key_id, secret)
    target = "/api/internal/n8n/v2/callbacks/status"

    async def send(
        *,
        instance,
        job_id,
        source_event_id=None,
        aggregate_id=None,
        delivery_generation=1,
    ):
        del aggregate_id  # nur zur Lesbarkeit am Aufrufort
        envelope = {
            "schema_version": "v2",
            "callback_name": "foundation.live.status",
            "callback_id": str(uuid4()),
            "source_event_id": source_event_id or str(uuid4()),
            "correlation_id": str(uuid4()),
            "odoo_instance": instance,
            "job_id": job_id,
            "sequence": 1,
            "attempt": 1,
            "delivery_generation": 1,
            "processing_lease_token": seed_metadata["restart_event"][
                "processing_lease_token"
            ],
            "status": "succeeded",
            "execution_id": "live-gate",
            "occurred_at": "2026-08-01T00:00:00+00:00",
            "next_retry_at": None,
            "result": {},
            "error": None,
            "metrics": {},
        }
        envelope["delivery_generation"] = delivery_generation
        raw_body = json.dumps(envelope, separators=(",", ":")).encode("utf-8")
        signed = sign_request(
            method="POST",
            target=target,
            delivery_generation=delivery_generation,
            timestamp=int(time.time()),
            nonce=str(uuid4()),
            raw_body=raw_body,
            key=key,
        )
        headers = signed.as_http_headers()
        headers["Content-Type"] = "application/json"

        verify = live_config["FOUNDATION_CA_FILE"]
        api = httpx.URL(live_config["FOUNDATION_API_URL"])
        async with httpx.AsyncClient(
            verify=verify if api.scheme == "https" else True, timeout=60.0
        ) as client:
            return await client.post(
                str(api.join(target)), content=raw_body, headers=headers
            )

    return send


