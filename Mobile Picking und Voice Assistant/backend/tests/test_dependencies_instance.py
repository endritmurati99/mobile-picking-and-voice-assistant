"""Tests fuer Instanz-Aufloesung und Per-Profil-Client-Cache."""
from datetime import datetime, timezone

import pytest
from fastapi import HTTPException

from app import dependencies
from app.config import OdooProfile
from app.dependencies import resolve_instance, get_request_odoo_client, get_odoo_client
from app.models.auth import Principal


def _principal_for(instance: str) -> Principal:
    return Principal(
        picker_user_id=7,
        picker_name="Mina Muster",
        device_id="device-42",
        odoo_instance=instance,
        roles=frozenset({"picker"}),
        session_id="4ddb2442-e58a-47fe-9a6f-1ec1d779ef88",
        expires_at=datetime(2026, 7, 23, 20, 0, tzinfo=timezone.utc),
    )


@pytest.fixture(autouse=True)
def _fake_registry(monkeypatch):
    reg = {
        "local": OdooProfile("local", "Lokal", "http://odoo:8069", "picking", "admin", "k", "p"),
        "logilab": OdooProfile("logilab", "LogILab", "https://logilab:8069", "logilab", "bot", "x", ""),
    }
    monkeypatch.setattr(dependencies, "get_instance_registry", lambda: reg)
    dependencies._clients.clear()
    yield
    dependencies._clients.clear()


def test_resolve_instance_defaults_to_local():
    assert resolve_instance(x_odoo_instance=None, instance=None) == "local"


def test_resolve_instance_known_header():
    assert resolve_instance(x_odoo_instance="LogiLab", instance=None) == "logilab"


def test_resolve_instance_query_fallback():
    assert resolve_instance(x_odoo_instance=None, instance="logilab") == "logilab"


def test_resolve_instance_unknown_raises_400():
    with pytest.raises(HTTPException) as exc:
        resolve_instance(x_odoo_instance="bogus", instance=None)
    assert exc.value.status_code == 400


def test_request_client_cached_per_profile():
    a = get_request_odoo_client(_principal_for("logilab"))
    b = get_request_odoo_client(_principal_for("logilab"))
    assert a is b
    assert a._db == "logilab"
    assert get_request_odoo_client(_principal_for("local")) is not a
    assert get_odoo_client() is get_request_odoo_client(_principal_for("local"))


def test_request_client_ignores_instance_header_and_uses_principal_instance():
    """`get_request_odoo_client` resolves the Odoo client from the Principal's
    `odoo_instance` -- a request-scoped `X-Odoo-Instance` header (not part of
    this dependency's signature at all) can never redirect it elsewhere.
    """
    a = get_request_odoo_client(_principal_for("logilab"))
    assert a._db == "logilab"
