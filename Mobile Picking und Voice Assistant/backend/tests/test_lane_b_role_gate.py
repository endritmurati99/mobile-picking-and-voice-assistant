"""Das Rollen-Gate am Router-Einschluss (Befund 2026-08-19).

`require_roles` war implementiert, aber an keinen Router verdrahtet -- es gab
faktisch keine Rollenautorisierung. Diese Datei beweist die Eigenschaft an der
ECHTEN App (`create_app`), nicht an einer nachgebauten Probe-App: nur so ist
bewiesen, dass das Gate an allen fuenf Browser-Routern haengt und nicht bloss
an dem einen, den ein Test zufaellig anfasst.

Die Rolle selbst kommt aus Odoo: `res.users.api_get_picker_principal`
(odoo/addons/picking_assistant_integration/models/api_security.py) vergibt
"picker" und "supervisor"; ohne mindestens eine davon ist eine Anmeldung gar
nicht erlaubt. Deshalb ist "picker" die Anforderung -- `supervisor` impliziert
`group_picker` und traegt sie immer mit.
"""
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app.dependencies import get_current_principal, get_session_service
from app.main import create_app
from app.models.auth import Principal
from tests.security_settings import make_secure_settings


def _principal(roles: frozenset[str]) -> Principal:
    return Principal(
        picker_user_id=7,
        picker_name="Mina Muster",
        device_id="device-42",
        odoo_instance="local",
        roles=roles,
        session_id="4ddb2442-e58a-47fe-9a6f-1ec1d779ef88",
        expires_at=datetime(2026, 7, 23, 20, 0, tzinfo=timezone.utc),
    )


PICKER = _principal(frozenset({"picker"}))
SUPERVISOR = _principal(frozenset({"picker", "supervisor"}))
ROLELESS = _principal(frozenset())
FOREIGN_ROLE_ONLY = _principal(frozenset({"supervisor"}))


class StubSessions:
    """Nur so viel Session-Service, wie das Gate braucht."""

    async def validate_csrf(self, principal, token, origin):
        return None


@pytest.fixture
def app():
    return create_app(make_secure_settings())


def _client(app, principal):
    app.dependency_overrides[get_current_principal] = lambda: principal
    app.dependency_overrides[get_session_service] = lambda: StubSessions()
    # `raise_server_exceptions=False`: hinter dem Gate liegt echte Fachlogik,
    # die ohne Odoo scheitert. Geprueft wird ausschliesslich, OB das Gate
    # durchgelassen hat -- ein 500 aus dem Handler ist genau dieser Beweis.
    return TestClient(app, raise_server_exceptions=False)


# Je eine Sonde pro Browser-Router. Fuer die Router ohne Leseroute wird eine
# Mutation benutzt -- dann aber mit vollstaendigen Gate-Headern, damit ein
# 403 im positiven Fall nicht aus CSRF/Idempotenz stammen kann.
GATE_HEADERS = {
    "Origin": "https://picking.warehouse.test",
    "X-CSRF-Token": "csrf-ok",
    "Idempotency-Key": "lane-b-role-gate",
}

BROWSER_PROBES = [
    ("pickings", "GET", "/api/pickings"),
    ("cluster", "GET", "/api/cluster/suggestions"),
    ("quality", "POST", "/api/quality-alerts"),
    ("voice", "POST", "/api/voice/assist"),
    ("scan", "POST", "/api/scan/validate"),
]


def _probe(client, method, path):
    if method == "GET":
        return client.get(path, headers=GATE_HEADERS)
    return client.post(path, headers=GATE_HEADERS, json={})


def test_the_probe_paths_are_real_routes(app):
    """Sonst beweist ein 403/Nicht-403 unten nur, dass es die Route nicht gibt."""
    real = {
        (method, route.path)
        for route in app.routes
        for method in (getattr(route, "methods", None) or set())
    }
    missing = [(m, p) for _tag, m, p in BROWSER_PROBES if (m, p) not in real]
    assert not missing, (
        f"Diese Sondenpfade zeigen ins Leere: {missing}. Pfad korrigieren -- "
        "eine 404-Sonde wuerde das Rollen-Gate nicht mehr pruefen."
    )


@pytest.mark.parametrize("principal", [PICKER, SUPERVISOR], ids=["picker", "supervisor"])
def test_a_principal_with_the_picker_role_passes_every_browser_router(app, principal):
    client = _client(app, principal)
    for tag, method, path in BROWSER_PROBES:
        response = _probe(client, method, path)
        assert response.status_code != 403, (
            f"{tag}: {method} {path} hat einen Benutzer MIT Picker-Rolle abgewiesen "
            "-- das Gate sperrt die Vorfuehrbenutzer (lena.lager, max.picker) aus."
        )


@pytest.mark.parametrize(
    "principal", [ROLELESS, FOREIGN_ROLE_ONLY], ids=["keine_rollen", "nur_supervisor"]
)
def test_a_principal_without_the_picker_role_is_403_on_every_browser_router(
    app, principal
):
    client = _client(app, principal)
    for tag, method, path in BROWSER_PROBES:
        response = _probe(client, method, path)
        assert response.status_code == 403, (
            f"{tag}: {method} {path} hat einen Benutzer OHNE Picker-Rolle mit "
            f"{response.status_code} bedient -- das Rollen-Gate haengt dort nicht."
        )


def test_the_refusal_names_the_role_and_leaks_nothing_else(app):
    client = _client(app, ROLELESS)
    response = _probe(client, "GET", "/api/pickings")
    assert response.status_code == 403
    assert response.json() == {"detail": "Rolle nicht erlaubt."}
