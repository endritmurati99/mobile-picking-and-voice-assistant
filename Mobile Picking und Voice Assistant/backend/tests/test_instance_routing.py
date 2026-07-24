"""Instanz-Routing am HTTP-Layer ist Principal-first: ohne Session -> 401,
`X-Odoo-Instance` ist bei Principal-gebundenen Routen nie autoritativ."""
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from app import dependencies
from app.dependencies import get_current_principal, get_request_odoo_client, get_session_service
from app.main import app


class _UnusedSessions:
    """Constructible stand-in so `get_current_principal` can fail on the
    missing cookie without needing real session-service secrets configured."""


def test_missing_session_returns_401_before_odoo():
    # Produktbild-Endpunkt haengt jetzt an `get_request_odoo_client` ->
    # `get_current_principal`; ohne `pwr_session`-Cookie kommt kein Odoo-Call
    # zustande, egal was `X-Odoo-Instance` behauptet.
    app.dependency_overrides[get_session_service] = lambda: _UnusedSessions()
    try:
        with TestClient(app) as client:
            resp = client.get("/api/products/1/image", headers={"X-Odoo-Instance": "bogus"})
    finally:
        app.dependency_overrides.pop(get_session_service, None)
    assert resp.status_code == 401


def test_known_instance_is_accepted_additively(as_sample_principal):
    fake = AsyncMock()
    fake.search_read.return_value = []  # -> 404 "Kein Bild", aber Instanz akzeptiert
    app.dependency_overrides[get_request_odoo_client] = lambda: fake
    try:
        with TestClient(app) as client:
            resp = client.get("/api/products/1/image", headers={"X-Odoo-Instance": "local"})
    finally:
        app.dependency_overrides.pop(get_request_odoo_client, None)
    assert resp.status_code == 404  # Endpunkt lief, kein Bild vorhanden


def test_spoofed_instance_header_is_ignored_and_principal_instance_wins(
    as_sample_principal, monkeypatch
):
    # `as_sample_principal` (o19) does not match the spoofed header (other-instance);
    # only a call for "o19" is allowed through the client cache.
    fake = AsyncMock()
    fake.search_read.return_value = []
    monkeypatch.setattr(
        dependencies,
        "_get_cached_client",
        lambda name: fake if name == "o19" else (_ for _ in ()).throw(AssertionError(name)),
    )
    with TestClient(app) as client:
        resp = client.get(
            "/api/products/1/image",
            headers={"X-Odoo-Instance": "other-instance"},
        )
    assert resp.status_code == 404  # Endpunkt lief mit der Principal-Instanz "o19"
