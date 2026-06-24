"""Route-Tests fuer /api/cluster/* (TestClient, Dependencies gemockt)."""
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from app.dependencies import get_cluster_service, get_required_picker_identity
from app.main import app
from app.services.mobile_workflow import PickerIdentity


@pytest.fixture
def cluster_service():
    return AsyncMock()


@pytest.fixture
def client(cluster_service):
    app.dependency_overrides[get_cluster_service] = lambda: cluster_service
    app.dependency_overrides[get_required_picker_identity] = lambda: PickerIdentity(user_id=7)
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_get_suggestions(client, cluster_service):
    cluster_service.suggest_batches.return_value = [{"zone": "Links", "picking_ids": [1, 2]}]
    resp = client.get("/api/cluster/suggestions", headers={"X-Picker-User-Id": "7"})
    assert resp.status_code == 200
    assert resp.json()[0]["zone"] == "Links"


def test_create_batch(client, cluster_service):
    cluster_service.create_batch.return_value = {"batch_id": 99}
    resp = client.post("/api/cluster/batches", json={"picking_ids": [1, 2]},
                       headers={"X-Picker-User-Id": "7", "X-Device-Id": "d1"})
    assert resp.status_code == 200
    assert resp.json()["batch_id"] == 99
    cluster_service.create_batch.assert_awaited_once()


def test_create_batch_rejects_empty(client, cluster_service):
    resp = client.post("/api/cluster/batches", json={"picking_ids": []},
                       headers={"X-Picker-User-Id": "7", "X-Device-Id": "d1"})
    assert resp.status_code == 400


def test_get_batch_404(client, cluster_service):
    cluster_service.get_batch.return_value = {"error": "Batch nicht gefunden"}
    resp = client.get("/api/cluster/batches/123", headers={"X-Picker-User-Id": "7"})
    assert resp.status_code == 404


def test_confirm_line(client, cluster_service):
    cluster_service.confirm_cluster_line.return_value = {"success": True, "progress": {"done": 1}}
    resp = client.post("/api/cluster/batches/99/confirm-line",
                       json={"picking_id": 1, "move_line_id": 100, "quantity": 1},
                       headers={"X-Picker-User-Id": "7", "X-Device-Id": "d1"})
    assert resp.status_code == 200
    assert resp.json()["success"] is True


def test_validate_batch(client, cluster_service):
    cluster_service.validate_batch.return_value = {"success": True, "batch_complete": True}
    resp = client.post("/api/cluster/batches/99/validate",
                       headers={"X-Picker-User-Id": "7", "X-Device-Id": "d1"})
    assert resp.status_code == 200
    assert resp.json()["batch_complete"] is True


def test_confirm_line_forbidden_returns_403(client, cluster_service):
    # #4: Auth-Fehler (forbidden) -> HTTP 403 statt 200.
    cluster_service.confirm_cluster_line.return_value = {
        "success": False, "forbidden": True, "message": "Kein Zugriff auf diesen Batch.",
        "progress": None}
    resp = client.post("/api/cluster/batches/99/confirm-line",
                       json={"picking_id": 1, "move_line_id": 100, "quantity": 1},
                       headers={"X-Picker-User-Id": "8", "X-Device-Id": "d1"})
    assert resp.status_code == 403


def test_validate_forbidden_returns_403(client, cluster_service):
    # #4: Auth-Fehler (forbidden) -> HTTP 403 statt 200.
    cluster_service.validate_batch.return_value = {
        "success": False, "batch_complete": False, "forbidden": True,
        "message": "Kein Zugriff auf diesen Batch."}
    resp = client.post("/api/cluster/batches/99/validate",
                       headers={"X-Picker-User-Id": "8", "X-Device-Id": "d1"})
    assert resp.status_code == 403
