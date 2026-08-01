"""Grace-Mode-Gate an den grace-faehigen Abhaengigkeiten.

Task-7-Review-Fund (Important): die bestehenden Routen-Tests laufen alle unter
dem Test-Default `mobile_header_grace_mode=True` / `runtime_profile="development"`
und beweisen damit nur, dass Legacy-Header greifen WENN Grace-Mode an ist.
Die eigentliche Sicherheitszusage von Task 7 -- der Legacy-Header-Fallback ist
unerreichbar sobald Grace-Mode aus ist (immer in production) -- war ungetestet.

Diese Tests schalten das Gate real um (via `settings`) und pruefen an jeder der
drei grace-faehigen Abhaengigkeiten, dass dann 401 kommt statt eines
Header-Fallbacks -- und als Gegenprobe, dass bei aktivem Grace-Mode der
Fallback tatsaechlich greift.
"""

from datetime import datetime, timezone

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from app.config import settings
from app.dependencies import (
    get_current_principal,
    get_request_odoo_client_or_grace,
    get_required_picker_identity,
    get_write_request_context,
)
from app.models.auth import Principal


LEGACY_HEADERS = {
    "X-Picker-User-Id": "999",
    "X-Device-Id": "legacy-device",
    "X-Odoo-Instance": "local",
}

PRINCIPAL = Principal(
    picker_user_id=7,
    picker_name="Mina Muster",
    device_id="device-42",
    odoo_instance="o19",
    roles=frozenset({"picker"}),
    session_id="4ddb2442-e58a-47fe-9a6f-1ec1d779ef88",
    expires_at=datetime(2026, 7, 23, 20, 0, tzinfo=timezone.utc),
)


def _grace_off(monkeypatch, *, profile="development"):
    """Grace-Mode aus -- zwei valide Wege: Flag aus (dev) oder production-Profil."""
    monkeypatch.setattr(settings, "runtime_profile", profile)
    monkeypatch.setattr(settings, "mobile_header_grace_mode", False)


def _grace_on(monkeypatch):
    monkeypatch.setattr(settings, "runtime_profile", "development")
    monkeypatch.setattr(settings, "mobile_header_grace_mode", True)


def _write_probe_app(odoo_client=None):
    app = FastAPI()
    _probe_runtime(app, odoo_client)

    @app.post("/write-probe")
    async def write_probe(ctx=Depends(get_write_request_context)):
        return {
            "user_id": ctx.identity.user_id,
            "scope": ctx.principal_scope,
        }

    return app


def _probe_runtime(app, odoo_client=None):
    """Task 16: Dependencies loesen den Odoo-Client ueber `app.state.runtime`
    auf. Eine blanke `FastAPI()` bringt keins mit, also bekommt jede Probe-App
    hier eines -- und der Test patcht genau dieses, statt ein Modul-Global.
    """
    from app.config import settings
    from app.runtime import RuntimeServices

    runtime = RuntimeServices(settings)
    if odoo_client is not None:
        runtime.odoo_client = odoo_client
    app.state.runtime = runtime
    return app


def _identity_probe_app(odoo_client=None):
    app = FastAPI()
    _probe_runtime(app, odoo_client)

    @app.get("/identity-probe")
    async def identity_probe(identity=Depends(get_required_picker_identity)):
        return {"user_id": identity.user_id}

    return app


def _odoo_probe_app(odoo_client=None):
    app = FastAPI()
    _probe_runtime(app, odoo_client)

    @app.get("/odoo-probe")
    async def odoo_probe(_odoo=Depends(get_request_odoo_client_or_grace)):
        return {"ok": True}

    return app


# --- Grace OFF: Fallback muss unerreichbar sein (401), NICHT auf Header zurueckfallen ---

@pytest.mark.parametrize("profile", ["development", "production"])
def test_write_context_refuses_legacy_headers_when_grace_off(monkeypatch, profile):
    _grace_off(monkeypatch, profile=profile)
    response = TestClient(_write_probe_app()).post("/write-probe", headers=LEGACY_HEADERS)
    assert response.status_code == 401


@pytest.mark.parametrize("profile", ["development", "production"])
def test_required_identity_refuses_legacy_headers_when_grace_off(monkeypatch, profile):
    _grace_off(monkeypatch, profile=profile)
    response = TestClient(_identity_probe_app()).get("/identity-probe", headers=LEGACY_HEADERS)
    assert response.status_code == 401


@pytest.mark.parametrize("profile", ["development", "production"])
def test_odoo_client_refuses_legacy_headers_when_grace_off(monkeypatch, profile):
    _grace_off(monkeypatch, profile=profile)
    response = TestClient(_odoo_probe_app()).get("/odoo-probe", headers=LEGACY_HEADERS)
    assert response.status_code == 401


# --- Session gewinnt: auch bei aktivem Grace-Mode schlaegt der Principal die Header ---

def test_session_principal_wins_over_legacy_headers_in_grace_mode(monkeypatch):
    _grace_on(monkeypatch)
    # get_required_picker_identity zieht ueber get_mobile_workflow_service einen
    # Odoo-Client fuer die Principal-Instanz -- keinen echten HTTP-Client bauen.
    app = _identity_probe_app(odoo_client=lambda name: object())
    app.dependency_overrides[get_current_principal] = lambda: PRINCIPAL
    response = TestClient(app).get("/identity-probe", headers=LEGACY_HEADERS)
    assert response.status_code == 200
    assert response.json() == {"user_id": 7}  # Principal (7), nicht Header (999)


# --- Gegenprobe: mit aktivem Grace-Mode greift der Legacy-Header-Fallback wirklich ---

def test_write_context_accepts_legacy_headers_when_grace_on(monkeypatch):
    _grace_on(monkeypatch)
    response = TestClient(_write_probe_app()).post("/write-probe", headers=LEGACY_HEADERS)
    assert response.status_code == 200
    body = response.json()
    assert body["user_id"] == 999
    assert body["scope"] is None
