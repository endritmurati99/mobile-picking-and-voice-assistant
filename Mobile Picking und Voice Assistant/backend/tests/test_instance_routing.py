"""Instanz-Selektor am HTTP-Layer: 400 bei unbekannter Instanz, additiv bei bekannter."""
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from app.dependencies import get_request_odoo_client
from app.main import app


def test_unknown_instance_returns_400_before_odoo():
    # Produktbild-Endpunkt braucht keine Picker-Identitaet -> resolve_instance
    # schlaegt VOR jedem Odoo-Call zu.
    with TestClient(app) as client:
        resp = client.get("/api/products/1/image", headers={"X-Odoo-Instance": "bogus"})
    assert resp.status_code == 400
    assert "Unbekannte Odoo-Instanz" in resp.json()["detail"]


def test_known_instance_is_accepted_additively():
    fake = AsyncMock()
    fake.search_read.return_value = []  # -> 404 "Kein Bild", aber Instanz akzeptiert
    app.dependency_overrides[get_request_odoo_client] = lambda: fake
    try:
        with TestClient(app) as client:
            resp = client.get("/api/products/1/image", headers={"X-Odoo-Instance": "local"})
    finally:
        app.dependency_overrides.clear()
    assert resp.status_code == 404  # Endpunkt lief, kein Bild vorhanden
