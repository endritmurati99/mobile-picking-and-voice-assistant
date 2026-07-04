"""Tests fuer Demo-only toggles."""
from fastapi.testclient import TestClient

from app import config
from app.main import app
from app.services.demo_traceability import DEMO_MODES, DemoTraceabilityService

client = TestClient(app)


def test_traceability_demo_guard_fails_closed_when_allowlist_empty(monkeypatch):
    monkeypatch.setattr(config.settings, "demo_traceability_enabled", True)
    monkeypatch.setattr(config.settings, "demo_traceability_allowed_dbs", "")
    monkeypatch.setattr(config.settings, "odoo_url", "http://odoo:8069")
    monkeypatch.setattr(config.settings, "odoo_db", "masterfischer")
    monkeypatch.setattr(config.settings, "odoo_user", "admin")
    monkeypatch.setattr(config.settings, "odoo_password", "admin")
    monkeypatch.setattr(config.settings, "odoo_api_key", "")
    monkeypatch.setattr(config.settings, "odoo_instances_json", "")

    response = client.get("/api/demo/traceability")

    assert response.status_code == 200
    payload = response.json()
    assert payload["enabled"] is False
    assert "keine Demo-DB" in payload["reason"]


def test_traceability_demo_exposes_all_finished_component_tracking_combinations():
    service = DemoTraceabilityService(None)

    expected = {
        ("none", "none"),
        ("lot", "none"),
        ("serial", "none"),
        ("none", "lot"),
        ("none", "serial"),
        ("lot", "lot"),
        ("lot", "serial"),
        ("serial", "lot"),
        ("serial", "serial"),
    }

    actual = {service._tracking_for_mode(mode) for mode in DEMO_MODES}

    assert actual == expected
