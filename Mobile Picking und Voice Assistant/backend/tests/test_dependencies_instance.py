"""Tests fuer Instanz-Aufloesung und Per-Profil-Client-Cache."""
import pytest
from fastapi import HTTPException

from app import dependencies
from app.config import OdooProfile
from app.dependencies import resolve_instance, get_request_odoo_client, get_odoo_client


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
    a = get_request_odoo_client("logilab")
    b = get_request_odoo_client("logilab")
    assert a is b
    assert a._db == "logilab"
    assert get_request_odoo_client("local") is not a
    assert get_odoo_client() is get_request_odoo_client("local")
