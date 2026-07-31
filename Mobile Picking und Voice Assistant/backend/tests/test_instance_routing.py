"""Instanz-Routing am HTTP-Layer ist Principal-first: ohne Session -> 401,
`X-Odoo-Instance` ist bei Principal-gebundenen Routen nie autoritativ."""
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from app import dependencies
from app.config import settings
from app.dependencies import get_current_principal, get_request_odoo_client, get_session_service
from app.main import app


class _UnusedSessions:
    """Constructible stand-in so `get_current_principal` can fail on the
    missing cookie without needing real session-service secrets configured."""


def test_missing_session_rejects_unknown_instance_without_odoo_call(monkeypatch):
    """BEWUSSTE AUSNAHME (2026-07-26): der Produktbild-Endpunkt haengt an
    `get_request_odoo_client_or_grace`, nicht mehr am strikten
    `get_request_odoo_client`.

    Grund: `<img src>` kann keine Custom-Header setzen, und bis das PWA-Login-UI
    kommt (Task 16) existiert kein Session-Cookie -- die Bilder waren dadurch
    live komplett tot. Preis dieser Ausnahme: im Dev-Profil sind Produktbilder
    ohne Session lesbar. In production ist Grace-Mode fail-closed, dort gilt
    weiterhin 401 -- siehe `test_missing_session_returns_401_in_production`.

    Die Instanz-Zusage dieses Moduls bleibt trotzdem intakt: eine unbekannte
    `X-Odoo-Instance` wird abgelehnt, bevor irgendein Odoo-Call zustande kommt.

    Grace-Mode ist seit Task 1 (Security Boundaries) standardmaessig aus; dieser
    Test aktiviert es explizit, weil er genau dieses Verhalten prueft.
    """
    monkeypatch.setattr(settings, "runtime_profile", "development")
    monkeypatch.setattr(settings, "mobile_header_grace_mode", True)
    app.dependency_overrides[get_session_service] = lambda: _UnusedSessions()
    try:
        with TestClient(app) as client:
            resp = client.get("/api/products/1/image", headers={"X-Odoo-Instance": "bogus"})
    finally:
        app.dependency_overrides.pop(get_session_service, None)
    assert resp.status_code == 400


def test_missing_session_returns_401_in_production(monkeypatch):
    """Gegenprobe zur Ausnahme oben: sobald Grace-Mode aus ist -- immer in
    production -- faellt der Bildendpunkt auf die Task-7-Invariante zurueck,
    also 401 ohne Session und ohne Odoo-Call."""
    monkeypatch.setattr(settings, "runtime_profile", "production")
    monkeypatch.setattr(settings, "mobile_header_grace_mode", False)
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
