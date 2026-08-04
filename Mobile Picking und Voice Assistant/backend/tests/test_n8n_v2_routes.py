"""Tests fuer die signierten v2-Routen (/api/internal/n8n/v2/...).

Leitmotiv: JEDE Ablehnung muss VOR jedem Odoo-Aufruf passieren. Deshalb
behauptet praktisch jeder Negativtest zusaetzlich `calls == []` auf allen
Fake-Clients -- ein spaeterer Refactor, der die Signaturpruefung hinter einen
Seiteneffekt schiebt, bricht diese Tests sofort.

Zweites Leitmotiv: Paritaet. Die beiden Routen (`/events/accept` und
`/callbacks/status`) werden fuer jede Transport-Abwehr parametrisiert getestet,
damit eine Verteidigung nicht in einer Route sitzt und in der anderen fehlt.
"""
import hashlib
import json
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app import dependencies
from app.config import OdooProfile
from app.dependencies import get_n8n_to_backend_keyring, get_signature_now
from app.main import app
from app.models.webhook_security import HmacKey, HmacKeyring
from app.services.hmac_signing import sign_request
from app.services.odoo_client import OdooAPIError

CALLBACK_TARGET = "/api/internal/n8n/v2/callbacks/status"
ACCEPT_TARGET = "/api/internal/n8n/v2/events/accept"

SIGNING_KEY = HmacKey("n2b-test", b"2" * 32)
FIXED_TS = 1760000000
NONCE = "123e4567-e89b-42d3-a456-426614174000"

CALLBACK = {
    "schema_version": "v2",
    "callback_name": "quality.assessment.status.v1",
    "callback_id": "cbdc037f-8458-4be0-938a-4bc8242116af",
    "source_event_id": "a4ff5ca2-4546-4ea4-8e6c-b75bc003ca32",
    "correlation_id": "0b2f7909-4ad9-44c1-8527-e775fe6d4bec",
    "odoo_instance": "o19-a",
    "job_id": "4ddb2442-e58a-47fe-9a6f-1ec1d779ef88",
    "sequence": 1,
    "attempt": 1,
    "delivery_generation": 1,
    "processing_lease_token": "lease-" + ("x" * 40),
    "status": "running",
    "execution_id": "execution-1",
    "occurred_at": "2026-07-23T12:00:04Z",
    "next_retry_at": None,
    "result": {},
    "error": None,
    "metrics": {},
}

ACCEPT = {
    "schema_version": "v2",
    "event_id": "a4ff5ca2-4546-4ea4-8e6c-b75bc003ca32",
    "job_id": "4ddb2442-e58a-47fe-9a6f-1ec1d779ef88",
    "odoo_instance": "o19-a",
    "payload_fingerprint": "a" * 64,
    "ingress_key_id": "b2n-active",
    "ingress_nonce": "123e4567-e89b-42d3-a456-426614174001",
    "delivery_generation": 1,
}

CALLBACK_APPLIED = {
    "status": "applied",
    "callback_id": CALLBACK["callback_id"],
    "job_id": CALLBACK["job_id"],
    "sequence": 1,
    "job_state": "running",
}

ACCEPT_PROCESS = {
    "accepted": True,
    "event_id": ACCEPT["event_id"],
    "job_id": ACCEPT["job_id"],
    "process": True,
    "processing_lease_token": "lease-" + ("y" * 40),
}


def body_for(target: str, overrides: dict | None = None) -> bytes:
    payload = dict(CALLBACK if target == CALLBACK_TARGET else ACCEPT)
    payload.update(overrides or {})
    return json.dumps(payload, separators=(",", ":")).encode()


def idempotency_for(target: str, payload: dict | None = None) -> str:
    source = payload or (CALLBACK if target == CALLBACK_TARGET else ACCEPT)
    return source["callback_id"] if target == CALLBACK_TARGET else source["event_id"]


class FakeOdoo:
    """Minimaler Odoo-Doppelgaenger. `calls` ist die Beweisliste: bleibt sie
    leer, hat die Route vor jedem Seiteneffekt abgelehnt."""

    def __init__(self, name, response=None, error=None):
        self.name = name
        self.calls = []
        self.response = response
        self.error = error

    async def execute_kw(self, model, method, args, kwargs=None):
        self.calls.append((model, method, args))
        if self.error is not None:
            raise self.error
        if self.response is not None:
            return self.response
        return (
            dict(CALLBACK_APPLIED)
            if model == "picking.assistant.callback.receipt"
            else dict(ACCEPT_PROCESS)
        )


@pytest.fixture(autouse=True)
def signed_env(monkeypatch):
    """Fixierte Signatur-Uhr, fixierter Keyring, Fake-Odoo pro Instanz.

    Die fixierte Uhr macht das Stale-Timestamp-Verhalten deterministisch statt
    von der Wanduhr abhaengig.
    """
    clients = {
        "local": FakeOdoo("local"),
        "o19-a": FakeOdoo("o19-a"),
        "o19-b": FakeOdoo("o19-b"),
    }
    registry = {
        name: OdooProfile(name, name, "http://odoo:8069", name, "admin", "k", "")
        for name in clients
    }
    monkeypatch.setattr(dependencies, "get_instance_registry", lambda: registry)
    # Task 16: der Client-Cache gehoert jetzt der App (`app.state.runtime`), nicht
    # mehr `app.dependencies`. Der Seam wandert damit an dieselbe Stelle, an der
    # der Produktionscode nachschlaegt -- ein gepatchtes Modul-Global koennte eine
    # App, die ihr eigenes Runtime benutzt, gar nicht mehr beeinflussen.
    runtime = app.state.runtime
    monkeypatch.setattr(runtime, "_instances", registry)
    monkeypatch.setattr(runtime, "odoo_client", clients.__getitem__)
    app.dependency_overrides[get_signature_now] = lambda: datetime.fromtimestamp(
        FIXED_TS, tz=timezone.utc
    )
    app.dependency_overrides[get_n8n_to_backend_keyring] = lambda: HmacKeyring(
        active=SIGNING_KEY
    )
    try:
        yield clients
    finally:
        app.dependency_overrides.clear()


def signed_headers(
    body: bytes,
    target: str,
    *,
    generation: int = 1,
    timestamp: int = FIXED_TS,
    nonce: str = NONCE,
    key: HmacKey = SIGNING_KEY,
    idempotency_key: str | None = None,
    method: str = "POST",
) -> dict[str, str]:
    signed = sign_request(
        method=method,
        target=target,
        delivery_generation=generation,
        timestamp=timestamp,
        nonce=nonce,
        raw_body=body,
        key=key,
    )
    headers = {
        **signed.as_http_headers(),
        "Content-Type": "application/json",
    }
    resolved = idempotency_key if idempotency_key is not None else idempotency_for(target)
    if resolved:
        headers["Idempotency-Key"] = resolved
    return headers


def no_odoo_calls(clients) -> bool:
    return all(client.calls == [] for client in clients.values())


BOTH_TARGETS = pytest.mark.parametrize("target", [ACCEPT_TARGET, CALLBACK_TARGET])


# --------------------------------------------------------------------------
# Happy paths
# --------------------------------------------------------------------------


def test_signed_callback_writes_only_named_instance(signed_env):
    body = body_for(CALLBACK_TARGET)
    with TestClient(app) as client:
        response = client.post(
            CALLBACK_TARGET, content=body, headers=signed_headers(body, CALLBACK_TARGET)
        )
    assert response.status_code == 200
    assert len(signed_env["o19-a"].calls) == 1
    assert signed_env["o19-b"].calls == []
    assert signed_env["local"].calls == []
    model, method, args = signed_env["o19-a"].calls[0]
    assert (model, method) == ("picking.assistant.callback.receipt", "api_apply_callback")
    # Die Route reicht Fingerprint/Key-Id/Nonce der VERIFIZIERTEN Signatur weiter,
    # damit Odoo den Replay-Schutz (Nonce-Store, Task 8) fuehren kann.
    assert args[1] == hashlib.sha256(body).hexdigest()
    assert args[2] == SIGNING_KEY.key_id
    assert args[3] == NONCE


def test_signed_acceptance_writes_only_named_instance(signed_env):
    body = body_for(ACCEPT_TARGET)
    with TestClient(app) as client:
        response = client.post(
            ACCEPT_TARGET, content=body, headers=signed_headers(body, ACCEPT_TARGET)
        )
    assert response.status_code == 200
    assert response.json() == {
        "accepted": True,
        "event_id": ACCEPT["event_id"],
        "process": True,
        "processing_lease_token": ACCEPT_PROCESS["processing_lease_token"],
    }
    assert len(signed_env["o19-a"].calls) == 1
    assert signed_env["o19-b"].calls == []
    model, method, args = signed_env["o19-a"].calls[0]
    assert (model, method) == ("picking.assistant.event.receipt", "api_accept_event")
    assert args == [
        ACCEPT["event_id"],
        ACCEPT["job_id"],
        ACCEPT["payload_fingerprint"],
        ACCEPT["ingress_key_id"],
        ACCEPT["ingress_nonce"],
        1,
        SIGNING_KEY.key_id,
        NONCE,
    ]


def test_acceptance_replay_reports_process_false(signed_env):
    signed_env["o19-a"].response = {
        "accepted": True,
        "event_id": ACCEPT["event_id"],
        "job_id": ACCEPT["job_id"],
        "process": False,
        "processing_lease_token": False,
    }
    body = body_for(ACCEPT_TARGET)
    response = TestClient(app).post(
        ACCEPT_TARGET, content=body, headers=signed_headers(body, ACCEPT_TARGET)
    )
    assert response.status_code == 200
    assert response.json()["process"] is False
    assert response.json()["processing_lease_token"] is None


def test_callback_response_exposes_only_contract_fields(signed_env):
    """Odoo liefert zusaetzlich `callback_id` und `job_state`. Die Antwort darf
    nur die drei Vertragsfelder enthalten -- kein Durchschleifen interner
    Zustandsdetails."""
    body = body_for(CALLBACK_TARGET)
    response = TestClient(app).post(
        CALLBACK_TARGET, content=body, headers=signed_headers(body, CALLBACK_TARGET)
    )
    assert response.status_code == 200
    assert response.json() == {
        "status": "applied",
        "job_id": CALLBACK["job_id"],
        "sequence": 1,
    }


def test_callback_replay_status_passes_through(signed_env):
    signed_env["o19-a"].response = {
        "status": "ignored_stale",
        "callback_id": CALLBACK["callback_id"],
        "job_id": CALLBACK["job_id"],
        "sequence": 0,
        "job_state": "running",
    }
    body = body_for(CALLBACK_TARGET)
    response = TestClient(app).post(
        CALLBACK_TARGET, content=body, headers=signed_headers(body, CALLBACK_TARGET)
    )
    assert response.status_code == 200
    assert response.json() == {
        "status": "ignored_stale",
        "job_id": CALLBACK["job_id"],
        "sequence": 0,
    }


# --------------------------------------------------------------------------
# Transport-Abwehr -- fuer BEIDE Routen identisch
# --------------------------------------------------------------------------


@BOTH_TARGETS
def test_invalid_signature_causes_no_odoo_call(signed_env, target):
    body = body_for(target)
    headers = signed_headers(body, target)
    headers["X-PWR-Signature"] = "v1=" + ("0" * 64)
    response = TestClient(app).post(target, content=body, headers=headers)
    assert response.status_code == 401
    assert no_odoo_calls(signed_env)


@BOTH_TARGETS
def test_missing_signature_headers_reject_before_odoo(signed_env, target):
    body = body_for(target)
    response = TestClient(app).post(
        target,
        content=body,
        headers={
            "Content-Type": "application/json",
            "Idempotency-Key": idempotency_for(target),
        },
    )
    assert response.status_code == 401
    assert no_odoo_calls(signed_env)


@BOTH_TARGETS
def test_legacy_callback_secret_is_not_accepted(signed_env, target):
    """Die v2-Routen kennen `X-N8N-Callback-Secret` nicht -- der Legacy-Pfad
    darf hier keine Autoritaet haben."""
    body = body_for(target)
    response = TestClient(app).post(
        target,
        content=body,
        headers={
            "Content-Type": "application/json",
            "Idempotency-Key": idempotency_for(target),
            "X-N8N-Callback-Secret": "s" * 40,
        },
    )
    assert response.status_code == 401
    assert no_odoo_calls(signed_env)


@BOTH_TARGETS
def test_unknown_key_id_rejected_without_disclosure(signed_env, target):
    body = body_for(target)
    headers = signed_headers(
        body, target, key=HmacKey("attacker-key", b"9" * 32)
    )
    response = TestClient(app).post(target, content=body, headers=headers)
    assert response.status_code == 401
    assert response.json()["detail"] == {"reason_code": "unknown_key_id"}
    assert SIGNING_KEY.key_id not in response.text
    assert no_odoo_calls(signed_env)


@BOTH_TARGETS
def test_stale_timestamp_rejected_before_odoo(signed_env, target):
    body = body_for(target)
    headers = signed_headers(body, target, timestamp=FIXED_TS - 4000)
    response = TestClient(app).post(target, content=body, headers=headers)
    assert response.status_code == 409
    assert response.json()["detail"] == {"reason_code": "timestamp_outside_window"}
    assert no_odoo_calls(signed_env)


@BOTH_TARGETS
def test_malformed_nonce_rejected_before_odoo(signed_env, target):
    body = body_for(target)
    headers = signed_headers(body, target, nonce="not-a-uuid")
    response = TestClient(app).post(target, content=body, headers=headers)
    assert response.status_code == 400
    assert no_odoo_calls(signed_env)


@BOTH_TARGETS
def test_tampered_body_rejected_before_odoo(signed_env, target):
    body = body_for(target)
    headers = signed_headers(body, target)
    tampered = body_for(target, {"odoo_instance": "o19-b"})
    response = TestClient(app).post(target, content=tampered, headers=headers)
    assert response.status_code == 401
    assert no_odoo_calls(signed_env)


@BOTH_TARGETS
def test_query_string_rejected_before_odoo(signed_env, target):
    body = body_for(target)
    headers = signed_headers(body, target)
    response = TestClient(app).post(
        target + "?instance=o19-b", content=body, headers=headers
    )
    assert response.status_code == 400
    assert response.json()["detail"] == {"reason_code": "query_not_allowed"}
    assert no_odoo_calls(signed_env)


def test_signature_for_other_route_is_not_reusable(signed_env):
    """Eine fuer /events/accept gueltige Signatur darf /callbacks/status nicht
    oeffnen (signed target ist Teil der kanonischen Eingabe)."""
    body = body_for(CALLBACK_TARGET)
    headers = signed_headers(body, ACCEPT_TARGET)
    headers["Idempotency-Key"] = CALLBACK["callback_id"]
    response = TestClient(app).post(CALLBACK_TARGET, content=body, headers=headers)
    assert response.status_code == 401
    assert no_odoo_calls(signed_env)


@BOTH_TARGETS
def test_signature_is_verified_before_body_is_parsed(signed_env, target):
    """Unsinniger Body + ungueltige Signatur => 401 (nicht 422). Die
    Signaturpruefung laeuft VOR dem Schema."""
    body = b"this-is-not-json"
    headers = signed_headers(body, target)
    headers["X-PWR-Signature"] = "v1=" + ("0" * 64)
    response = TestClient(app).post(target, content=body, headers=headers)
    assert response.status_code == 401
    assert no_odoo_calls(signed_env)


@BOTH_TARGETS
def test_signed_but_unparseable_body_is_422_before_odoo(signed_env, target):
    body = b"this-is-not-json"
    response = TestClient(app).post(
        target, content=body, headers=signed_headers(body, target)
    )
    assert response.status_code == 422
    assert no_odoo_calls(signed_env)


# --------------------------------------------------------------------------
# Bindung Header <-> signierter Body, Instanz-Routing, Schema
# --------------------------------------------------------------------------


@BOTH_TARGETS
def test_header_generation_must_equal_signed_body(signed_env, target):
    body = body_for(target)
    response = TestClient(app).post(
        target, content=body, headers=signed_headers(body, target, generation=2)
    )
    assert response.status_code == 409
    assert no_odoo_calls(signed_env)


@BOTH_TARGETS
def test_idempotency_key_must_equal_body_identifier(signed_env, target):
    body = body_for(target)
    headers = signed_headers(
        body, target, idempotency_key="11111111-2222-4333-8444-555555555555"
    )
    response = TestClient(app).post(target, content=body, headers=headers)
    assert response.status_code == 409
    assert no_odoo_calls(signed_env)


@BOTH_TARGETS
def test_missing_idempotency_key_rejected_before_odoo(signed_env, target):
    body = body_for(target)
    headers = signed_headers(body, target, idempotency_key="")
    assert "Idempotency-Key" not in headers
    response = TestClient(app).post(target, content=body, headers=headers)
    assert response.status_code == 409
    assert no_odoo_calls(signed_env)


@BOTH_TARGETS
def test_unknown_instance_in_signed_body_is_403(signed_env, target):
    body = body_for(target, {"odoo_instance": "o19-zzz"})
    response = TestClient(app).post(
        target, content=body, headers=signed_headers(body, target)
    )
    assert response.status_code == 403
    assert no_odoo_calls(signed_env)


@BOTH_TARGETS
def test_instance_header_cannot_redirect_the_write(signed_env, target):
    """`X-Odoo-Instance` ist auf den v2-Routen nie autoritativ: der Schreibweg
    folgt ausschliesslich `odoo_instance` aus dem signierten Body."""
    body = body_for(target)
    headers = signed_headers(body, target)
    headers["X-Odoo-Instance"] = "o19-b"
    response = TestClient(app).post(target, content=body, headers=headers)
    assert response.status_code == 200
    assert len(signed_env["o19-a"].calls) == 1
    assert signed_env["o19-b"].calls == []
    assert signed_env["local"].calls == []


def test_malformed_callback_schema_is_422_before_odoo(signed_env):
    body = body_for(CALLBACK_TARGET, {"status": "queued"})
    response = TestClient(app).post(
        CALLBACK_TARGET, content=body, headers=signed_headers(body, CALLBACK_TARGET)
    )
    assert response.status_code == 422
    assert no_odoo_calls(signed_env)


def test_unregistered_callback_name_is_422_before_odoo(signed_env):
    body = body_for(CALLBACK_TARGET, {"callback_name": "pick.confirmed.v9"})
    response = TestClient(app).post(
        CALLBACK_TARGET, content=body, headers=signed_headers(body, CALLBACK_TARGET)
    )
    assert response.status_code == 422
    assert no_odoo_calls(signed_env)


def test_malformed_acceptance_instance_name_is_422_before_odoo(signed_env):
    """`odoo_instance` wird im Acceptance-Body genauso streng validiert wie im
    Callback-Envelope -- gleiche Abwehr in beiden Modellen."""
    body = body_for(ACCEPT_TARGET, {"odoo_instance": "../local"})
    response = TestClient(app).post(
        ACCEPT_TARGET, content=body, headers=signed_headers(body, ACCEPT_TARGET)
    )
    assert response.status_code == 422
    assert no_odoo_calls(signed_env)


def test_malformed_acceptance_fingerprint_is_422_before_odoo(signed_env):
    body = body_for(ACCEPT_TARGET, {"payload_fingerprint": "zz"})
    response = TestClient(app).post(
        ACCEPT_TARGET, content=body, headers=signed_headers(body, ACCEPT_TARGET)
    )
    assert response.status_code == 422
    assert no_odoo_calls(signed_env)


@BOTH_TARGETS
def test_extra_body_field_is_422_before_odoo(signed_env, target):
    body = body_for(target, {"database": "must-not-leak"})
    response = TestClient(app).post(
        target, content=body, headers=signed_headers(body, target)
    )
    assert response.status_code == 422
    assert no_odoo_calls(signed_env)


@BOTH_TARGETS
def test_validation_detail_does_not_echo_submitted_values(signed_env, target):
    body = body_for(target, {"database": "must-not-leak"})
    response = TestClient(app).post(
        target, content=body, headers=signed_headers(body, target)
    )
    assert response.status_code == 422
    assert "must-not-leak" not in response.text


# --------------------------------------------------------------------------
# Odoo-Fehler und Job-Bindung
# --------------------------------------------------------------------------


@BOTH_TARGETS
def test_odoo_error_maps_to_409_without_leaking_existence(signed_env, target):
    signed_env["o19-a"].error = OdooAPIError(
        {"data": {"message": "Unknown job: 4ddb2442 does not exist."}}
    )
    body = body_for(target)
    response = TestClient(app).post(
        target, content=body, headers=signed_headers(body, target)
    )
    assert response.status_code == 409
    assert "Unknown job" not in response.text
    assert "does not exist" not in response.text


@BOTH_TARGETS
def test_job_mismatch_in_odoo_result_is_409(signed_env, target):
    other_job = "9999aaaa-e58a-47fe-9a6f-1ec1d779ef88"
    signed_env["o19-a"].response = (
        {**CALLBACK_APPLIED, "job_id": other_job}
        if target == CALLBACK_TARGET
        else {**ACCEPT_PROCESS, "job_id": other_job}
    )
    body = body_for(target)
    response = TestClient(app).post(
        target, content=body, headers=signed_headers(body, target)
    )
    assert response.status_code == 409


@BOTH_TARGETS
def test_incomplete_odoo_result_fails_closed_with_409(signed_env, target):
    signed_env["o19-a"].response = {"status": "applied"}
    body = body_for(target)
    response = TestClient(app).post(
        target, content=body, headers=signed_headers(body, target)
    )
    assert response.status_code == 409


@BOTH_TARGETS
def test_ill_typed_odoo_result_fails_closed_with_409(signed_env, target):
    """Beide Routen muessen eine schemawidrige Odoo-Antwort als 409 abweisen --
    nicht eine als 409 und die andere als 500."""
    signed_env["o19-a"].response = (
        {**CALLBACK_APPLIED, "sequence": "not-an-int"}
        if target == CALLBACK_TARGET
        else {**ACCEPT_PROCESS, "processing_lease_token": 12345}
    )
    body = body_for(target)
    response = TestClient(app).post(
        target, content=body, headers=signed_headers(body, target)
    )
    assert response.status_code == 409


@BOTH_TARGETS
def test_non_dict_odoo_result_fails_closed_with_409(signed_env, target):
    signed_env["o19-a"].response = False
    body = body_for(target)
    response = TestClient(app).post(
        target, content=body, headers=signed_headers(body, target)
    )
    assert response.status_code == 409


def test_non_boolean_process_flag_fails_closed_with_409(signed_env):
    """`process` steuert, ob n8n den Job wirklich ausfuehrt. Ein truthy String
    aus Odoo darf nicht stillschweigend zu `True` werden."""
    signed_env["o19-a"].response = {**ACCEPT_PROCESS, "process": "false"}
    body = body_for(ACCEPT_TARGET)
    response = TestClient(app).post(
        ACCEPT_TARGET, content=body, headers=signed_headers(body, ACCEPT_TARGET)
    )
    assert response.status_code == 409


@BOTH_TARGETS
def test_unconfigured_keyring_fails_closed_with_503(signed_env, target):
    """Ohne konfiguriertes n8n->Backend-Secret gibt es keinen Pfad zu einem
    Default-Key: die Route antwortet 503 und ruft Odoo nicht auf (gleiches
    Verhalten wie `require_n8n_callback_secret` fuer den Legacy-Pfad)."""
    app.dependency_overrides.pop(get_n8n_to_backend_keyring, None)
    body = body_for(target)
    response = TestClient(app).post(
        target, content=body, headers=signed_headers(body, target)
    )
    assert response.status_code == 503
    assert no_odoo_calls(signed_env)


def test_v2_router_has_no_browser_or_legacy_dependencies():
    """Regressionsgitter: keine der v2-Routen darf an Session-, CSRF-,
    Grace-Mode- oder Legacy-Secret-Abhaengigkeiten haengen."""
    from app.dependencies import (
        get_current_principal,
        get_demo_odoo_client,
        get_odoo_client,
        get_request_odoo_client,
        get_request_odoo_client_or_grace,
        get_write_request_context,
        require_browser_csrf,
        require_n8n_callback_secret,
        resolve_instance,
        resolve_legacy_header_identity,
    )

    forbidden = {
        get_current_principal,
        get_demo_odoo_client,
        get_odoo_client,
        get_request_odoo_client,
        get_request_odoo_client_or_grace,
        get_write_request_context,
        require_browser_csrf,
        require_n8n_callback_secret,
        resolve_instance,
        resolve_legacy_header_identity,
    }
    def transitive_calls(dependant) -> set:
        """Rekursiv, nicht nur die oberste Ebene: eine verbotene Abhaengigkeit
        waere sonst schon dadurch unsichtbar, dass sie eine Ebene tiefer
        eingehaengt wird."""
        found = set()
        for dep in dependant.dependencies:
            found.add(dep.call)
            found |= transitive_calls(dep)
        return found

    v2_routes = [
        route
        for route in app.routes
        if getattr(route, "path", "").startswith("/api/internal/n8n/v2/")
    ]
    # Vollstaendige Aufzaehlung, kein Teilmengen-Vergleich: eine neu
    # angehaengte v2-Route soll diesen Test brechen und damit durch die
    # Pruefungen darunter gezwungen werden.
    assert {route.path for route in v2_routes} == {
        ACCEPT_TARGET,
        CALLBACK_TARGET,
        "/api/internal/n8n/v2/assessments/quality",
    }
    for route in v2_routes:
        used = transitive_calls(route.dependant)
        assert not (used & forbidden), route.path
        # Die Signaturpruefung MUSS an jeder v2-Route haengen.
        assert dependencies.verify_n8n_to_backend_request in used, route.path
