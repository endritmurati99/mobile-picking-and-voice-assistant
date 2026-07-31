"""Task 16 -- die Sicherheitshaltung der PRODUKTIVEN App, am App-Zusammenbau.

Diese Datei beweist Eigenschaften der ganzen Anwendung, nicht einzelner
Handler. Sie besitzt keinen Router-Body und darf keinen brauchen.

Register-Befund #2b: `require_browser_csrf` war definiert, aber an keinen
Router verdrahtet. Ein Guard, der nur "ohne Origin -> 403" prueft, beweist
fast nichts; deshalb prueft `test_csrf_rejects_*` gezielt die Faelle, an denen
ein `startswith`/Substring-Vergleich auffliegen wuerde.
"""
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app.dependencies import get_current_principal, get_session_service
from app.main import create_app
from app.models.auth import Principal
from app.services.auth_sessions import CsrfFailed
from tests.security_settings import make_secure_settings

ALLOWED_ORIGIN = "https://picking.warehouse.test"

PRINCIPAL = Principal(
    picker_user_id=7,
    picker_name="Mina Muster",
    device_id="device-42",
    odoo_instance="local",
    roles=frozenset({"picker"}),
    session_id="4ddb2442-e58a-47fe-9a6f-1ec1d779ef88",
    expires_at=datetime(2026, 7, 23, 20, 0, tzinfo=timezone.utc),
)


class StubSessions:
    """Nachbildung der EXAKTEN Origin-Semantik von `SessionService`.

    Der Stub darf nicht grosszuegiger sein als der echte Service, sonst
    beweisen die Origin-Tests nichts ueber die Produktion.
    """

    def __init__(self, allowed_origins=(ALLOWED_ORIGIN,)):
        self._allowed = set(allowed_origins)

    async def validate_csrf(self, principal, token, origin):
        if origin not in self._allowed:
            raise CsrfFailed("Origin ist nicht erlaubt.")
        if token != "csrf-ok":
            raise CsrfFailed("CSRF-Token ist ungueltig.")


@pytest.fixture
def app():
    return create_app(make_secure_settings())


@pytest.fixture
def anonymous(app):
    """Client OHNE Sitzung, aber MIT konfiguriertem Session-Service.

    Ohne den Override antwortet die Testumgebung 503 ("Session service ist
    nicht konfiguriert") und wuerde damit jede Aussage darueber verdecken, ob
    das Auth-Gate oder blosse Fehlkonfiguration abgelehnt hat.
    """
    app.dependency_overrides[get_session_service] = lambda: StubSessions()
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


@pytest.fixture
def authenticated(app):
    app.dependency_overrides[get_current_principal] = lambda: PRINCIPAL
    app.dependency_overrides[get_session_service] = lambda: StubSessions()
    try:
        # `raise_server_exceptions=False`: hinter dem Gate liegt echte
        # Fachlogik, die ohne Odoo scheitert. Das ist hier egal -- geprueft
        # wird ausschliesslich, OB das Gate durchgelassen hat. Ein 500 aus dem
        # Handler ist der Beweis, dass es durchgelassen hat.
        yield TestClient(app, raise_server_exceptions=False)
    finally:
        app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# 1. Exakte Pre-Auth-Allowlist -- aus den ECHTEN Routen der App abgeleitet
# ---------------------------------------------------------------------------

# Die einzigen Endpunkte, die eine produktive App ohne Sitzung bedienen darf.
# Eine handgeschriebene Liste driftet; deshalb prueft der Test unten JEDE
# tatsaechlich registrierte Route und nicht nur diese Eintraege.
EXPECTED_PRE_AUTH = {
    ("GET", "/api/health/live"),
    ("GET", "/api/auth/instances"),
    ("POST", "/api/auth/picker-session"),
}

_PATH_PARAM_SAMPLES = {
    "picking_id": "42",
    "batch_id": "5",
    "product_id": "3",
    "odoo_instance": "local",
    "job_id": "1",
    "processing_lease_token": "lease-token",
    "source_event_id": "event-1",
    "artifact_kind": "label",
    "media_ref": "media-1",
}

_REFUSAL_CODES = {401, 403, 503}


def _concrete(path: str) -> str:
    concrete = path
    for name, value in _PATH_PARAM_SAMPLES.items():
        concrete = concrete.replace("{" + name + "}", value)
    return concrete


def _real_routes(app):
    seen = []
    for route in app.routes:
        methods = getattr(route, "methods", None)
        if not methods:
            continue
        for method in sorted(methods & {"GET", "POST", "PUT", "PATCH", "DELETE"}):
            seen.append((method, route.path))
    return sorted(set(seen))


def test_no_route_outside_the_allowlist_serves_an_unauthenticated_request(app):
    """Der Kern-Beweis: JEDE registrierte Route wird angefasst.

    Nicht "die Liste, von der ich glaube, dass sie stimmt" -- die Liste, die
    der Router tatsaechlich haelt. Eine neue ungeschuetzte Route faellt hier
    auf, ohne dass jemand diese Datei anfassen muss.
    """
    client = TestClient(app)
    leaked = []
    for method, path in _real_routes(app):
        if (method, path) in EXPECTED_PRE_AUTH:
            continue
        response = client.request(method, _concrete(path), json={})
        if response.status_code not in _REFUSAL_CODES:
            leaked.append((method, path, response.status_code))
    assert leaked == []


def test_the_allowlist_contains_no_stale_entry(app, anonymous):
    """Jeder Allowlist-Eintrag existiert wirklich UND ist wirklich pre-auth."""
    real = set(_real_routes(app))
    assert EXPECTED_PRE_AUTH <= real
    assert anonymous.get("/api/health/live").status_code == 200
    assert anonymous.get("/api/auth/instances").status_code == 200
    # Login: erreicht den Handler (422 = Body-Validierung), kein Auth-Gate davor.
    assert anonymous.post("/api/auth/picker-session", json={}).status_code == 422


def test_spoofed_legacy_identity_headers_carry_no_authority(anonymous):
    assert anonymous.get(
        "/api/pickings",
        headers={
            "X-Picker-User-Id": "7",
            "X-Device-Id": "spoof",
            "X-Odoo-Instance": "local",
        },
    ).status_code == 401


@pytest.mark.parametrize(
    "path",
    [
        "/docs",
        "/redoc",
        "/openapi.json",
        "/api/docs",
        "/api/redoc",
        "/api/openapi.json",
        "/api/demo/traceability",
        "/api/obsidian/search?q=test",
        "/api/instances",
        "/api/health",
    ],
)
def test_removed_production_surfaces_are_404(app, path):
    assert TestClient(app).get(path).status_code == 404


# ---------------------------------------------------------------------------
# 2. CSRF / Origin -- die Faelle, an denen ein loser Vergleich auffliegt
# ---------------------------------------------------------------------------

CSRF_PATH = "/api/cluster/batches"
CSRF_BODY = {"picking_ids": [1]}


@pytest.mark.parametrize(
    "origin",
    [
        None,                                              # gar kein Origin
        "null",                                            # sandboxed iframe / data: URL
        "https://evil.test",                               # fremd
        "https://picking.warehouse.test.attacker.example",  # PRAEFIX der Allowlist
        "https://evil-picking.warehouse.test",             # SUFFIX der Allowlist
        "http://picking.warehouse.test",                   # gleiches Host, falsches Schema
        "https://picking.warehouse.test:8443",             # gleiches Host, fremder Port
        "https://picking.warehouse.test/",                 # Trailing Slash
        "HTTPS://PICKING.WAREHOUSE.TEST",                  # Case
    ],
)
def test_csrf_rejects_every_origin_that_is_not_exactly_allowed(authenticated, origin):
    headers = {"X-CSRF-Token": "csrf-ok", "Idempotency-Key": "key-1"}
    if origin is not None:
        headers["Origin"] = origin
    response = authenticated.post(CSRF_PATH, json=CSRF_BODY, headers=headers)
    assert response.status_code == 403


def test_csrf_rejects_a_missing_or_wrong_token(authenticated):
    assert authenticated.post(
        CSRF_PATH,
        json=CSRF_BODY,
        headers={"Origin": ALLOWED_ORIGIN, "Idempotency-Key": "key-1"},
    ).status_code == 403
    assert authenticated.post(
        CSRF_PATH,
        json=CSRF_BODY,
        headers={
            "Origin": ALLOWED_ORIGIN,
            "X-CSRF-Token": "csrf-wrong",
            "Idempotency-Key": "key-1",
        },
    ).status_code == 403


def test_a_same_site_request_with_a_valid_token_passes_the_gate(authenticated):
    """Gegenprobe: das Gate ist kein pauschales 403."""
    response = authenticated.post(
        CSRF_PATH,
        json=CSRF_BODY,
        headers={
            "Origin": ALLOWED_ORIGIN,
            "X-CSRF-Token": "csrf-ok",
            "Idempotency-Key": "key-1",
        },
    )
    assert response.status_code != 403


def test_reads_are_not_csrf_gated(authenticated):
    """Ein GET darf kein CSRF-Token verlangen -- sonst ist die App tot.

    Der Request hat weder Origin noch Token; er darf trotzdem nicht am Gate
    haengen bleiben (was dahinter passiert, ist hier nicht die Frage).
    """
    assert authenticated.get("/api/cluster/suggestions").status_code != 403


# ---------------------------------------------------------------------------
# 3. Idempotency-Key: Pflicht auf Domain-Mutationen, Syntax fail-closed
# ---------------------------------------------------------------------------

DOMAIN_MUTATIONS = (
    ("POST", "/api/pickings/42/confirm-line"),
    ("POST", "/api/pickings/42/replenishment-request"),
    ("POST", "/api/pickings/42/claim"),
    ("POST", "/api/pickings/42/release"),
    ("POST", "/api/pickings/42/returns/reconcile"),
    ("POST", "/api/quality-alerts"),
    ("POST", "/api/cluster/batches"),
    ("POST", "/api/cluster/batches/5/confirm-line"),
    ("POST", "/api/cluster/batches/5/validate"),
)

IDEMPOTENCY_EXEMPT = (
    ("POST", "/api/pickings/42/heartbeat"),
    ("POST", "/api/voice/recognize"),
    ("POST", "/api/voice/assist"),
    ("POST", "/api/voice/tts"),
    ("POST", "/api/scan/validate"),
)

_CSRF_HEADERS = {"Origin": ALLOWED_ORIGIN, "X-CSRF-Token": "csrf-ok"}


@pytest.mark.parametrize("method,path", DOMAIN_MUTATIONS)
def test_domain_mutation_without_idempotency_key_is_400(authenticated, method, path):
    response = authenticated.request(method, path, json={}, headers=_CSRF_HEADERS)
    assert response.status_code == 400


@pytest.mark.parametrize("method,path", IDEMPOTENCY_EXEMPT)
def test_exempt_mutation_without_idempotency_key_is_not_400(
    authenticated, method, path
):
    response = authenticated.request(method, path, json={}, headers=_CSRF_HEADERS)
    assert response.status_code != 400


@pytest.mark.parametrize(
    "value",
    ["", "contains space", "a" * 129, "tab\there", "del\x7f"],
)
def test_domain_idempotency_key_is_1_to_128_visible_ascii(authenticated, value):
    response = authenticated.post(
        "/api/cluster/batches",
        json=CSRF_BODY,
        headers={**_CSRF_HEADERS, "Idempotency-Key": value},
    )
    assert response.status_code == 400


@pytest.mark.parametrize("value", ["a", "a" * 128, "op:cluster-create/1-2#7"])
def test_a_wellformed_idempotency_key_passes_the_gate(authenticated, value):
    response = authenticated.post(
        "/api/cluster/batches",
        json=CSRF_BODY,
        headers={**_CSRF_HEADERS, "Idempotency-Key": value},
    )
    assert response.status_code != 400


@pytest.mark.parametrize(
    "value",
    [None, "", "umlaut-ä", "line\nbreak", "carriage\rreturn", "nul\x00", "a" * 129],
)
def test_validate_idempotency_key_rejects_what_no_client_may_send(value):
    """Werte, die httpx gar nicht erst ueber die Leitung laesst -- ein anderer
    Client aber sehr wohl. Deshalb direkt gegen die Funktion geprueft."""
    from fastapi import HTTPException

    from app.dependencies import validate_idempotency_key

    with pytest.raises(HTTPException) as excinfo:
        validate_idempotency_key(value)
    assert excinfo.value.status_code == 400


def test_every_mutating_browser_route_requires_a_key_unless_exempt(app):
    """Drift-Wache: die Ausnahmeliste zeigt nur auf ECHTE Routen, und jede
    andere Mutation der geschuetzten Router faellt automatisch unter die
    Pflicht -- ohne dass jemand eine zweite Liste pflegen muss.
    """
    from app.route_policy import IDEMPOTENCY_EXEMPT_ROUTES, requires_idempotency_key

    gated = app.state.gated_routes
    assert IDEMPOTENCY_EXEMPT_ROUTES <= gated
    required = {
        (method, path)
        for method, path in gated
        if requires_idempotency_key(method, path)
    }
    # Jede Mutation ist entweder Ausnahme oder pflichtig -- nichts dazwischen.
    mutations = {(m, p) for m, p in gated if m in {"POST", "PUT", "PATCH", "DELETE"}}
    assert required | IDEMPOTENCY_EXEMPT_ROUTES == mutations
    assert required, "es muss echte Domain-Mutationen geben"


BAD_ORIGINS = [
    None,
    "null",
    "https://evil.test",
    "https://picking.warehouse.test.attacker.example",
    "https://evil-picking.warehouse.test",
    "http://picking.warehouse.test",
    "https://picking.warehouse.test:8443",
    "https://picking.warehouse.test/",
    "HTTPS://PICKING.WAREHOUSE.TEST",
]


@pytest.mark.parametrize("origin", BAD_ORIGINS)
def test_the_real_session_service_refuses_the_origin_before_touching_odoo(origin):
    """Beweist die Origin-Semantik am ECHTEN `SessionService`, nicht am Stub.

    Der Stub oben spiegelt diese Regel nur; ohne diesen Test bewiesen die
    Route-Tests bloss, dass der Stub tut, was der Stub tut. Zusaetzlich wird
    festgenagelt, dass die Ablehnung VOR jedem Odoo-Aufruf passiert -- ein
    Origin-Check nach dem RPC waere ein CSRF-wirksamer Seiteneffekt.
    """
    from app.services.auth_sessions import SessionService

    calls = []

    def factory(name):
        calls.append(name)
        raise AssertionError("Odoo darf bei verbotenem Origin nicht erreicht werden")

    service = SessionService(
        client_factory=factory,
        instance_names={"local"},
        throttle_secret=b"0" * 32,
        allowed_origins={ALLOWED_ORIGIN},
        session_seconds=3600,
        revalidate_seconds=300,
    )
    import asyncio

    with pytest.raises(CsrfFailed):
        asyncio.run(service.validate_csrf(PRINCIPAL, "any-token", origin))
    assert calls == []


def test_health_live_is_the_only_health_route(app):
    paths = {path for _, path in _real_routes(app)}
    assert "/api/health/live" in paths
    assert "/api/health" not in paths
