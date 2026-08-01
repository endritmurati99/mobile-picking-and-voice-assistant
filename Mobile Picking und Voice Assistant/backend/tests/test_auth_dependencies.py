from datetime import datetime, timezone

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from app.dependencies import (
    get_current_principal,
    get_request_odoo_client,
    get_required_picker_identity,
    require_roles,
)
from app.models.auth import Principal


PRINCIPAL = Principal(
    picker_user_id=7,
    picker_name="Mina Muster",
    device_id="device-42",
    odoo_instance="o19",
    roles=frozenset({"picker"}),
    session_id="4ddb2442-e58a-47fe-9a6f-1ec1d779ef88",
    expires_at=datetime(2026, 7, 23, 20, 0, tzinfo=timezone.utc),
)


def test_spoofed_headers_do_not_change_identity_or_instance(monkeypatch):
    from app.config import settings as app_settings
    from app.runtime import RuntimeServices

    app = FastAPI()
    sentinel = object()
    app.dependency_overrides[get_current_principal] = lambda: PRINCIPAL
    # Task 16: der Client-Cache haengt an der App, also wird er hier an der App
    # gesetzt. Ein Aufruf fuer eine andere Instanz als die des Principals lässt
    # den Test hart fallen -- genau das ist die Behauptung.
    runtime = RuntimeServices(app_settings)
    runtime.odoo_client = (
        lambda name: sentinel if name == "o19" else (_ for _ in ()).throw(AssertionError(name))
    )
    app.state.runtime = runtime

    @app.get("/probe")
    async def probe(
        identity=Depends(get_required_picker_identity),
        odoo=Depends(get_request_odoo_client),
    ):
        return {
            "user_id": identity.user_id,
            "device_id": identity.device_id,
            "instance": identity.odoo_instance,
            "client": odoo is sentinel,
        }

    response = TestClient(app).get(
        "/probe",
        headers={
            "X-Picker-User-Id": "999",
            "X-Device-Id": "attacker",
            "X-Odoo-Instance": "local",
        },
    )
    assert response.json() == {
        "user_id": 7,
        "device_id": "device-42",
        "instance": "o19",
        "client": True,
    }


def test_picker_cannot_enter_supervisor_dependency():
    app = FastAPI()
    app.dependency_overrides[get_current_principal] = lambda: PRINCIPAL

    @app.post("/supervisor")
    async def supervisor(_principal=Depends(require_roles("supervisor"))):
        return {"ok": True}

    assert TestClient(app).post("/supervisor").status_code == 403
