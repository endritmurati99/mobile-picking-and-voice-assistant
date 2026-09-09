"""Route-Tests fuer /api/cluster/* (TestClient, Dependencies gemockt)."""
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi.testclient import TestClient

from app.dependencies import (
    get_cluster_service,
    get_mobile_workflow_service,
    get_required_picker_identity,
    get_write_request_context,
)
from app.main import app
from app.services.mobile_workflow import (
    IdempotencyReservation,
    PickerIdentity,
    WriteRequestContext,
)
from tests.conftest import BROWSER_GATE_HEADERS, install_browser_gate


@pytest.fixture
def cluster_service():
    return AsyncMock()


@pytest.fixture
def client(cluster_service, sample_principal):
    identity = PickerIdentity(user_id=7, device_id="device-42", picker_name="Mina Muster")
    workflow = AsyncMock()
    workflow.resolve_identity.return_value = identity
    workflow.build_request_fingerprint = Mock(return_value="test-fingerprint")
    workflow.begin_idempotent_request.return_value = IdempotencyReservation(status="disabled")
    app.dependency_overrides[get_cluster_service] = lambda: cluster_service
    app.dependency_overrides[get_required_picker_identity] = lambda: identity
    app.dependency_overrides[get_mobile_workflow_service] = lambda: workflow
    app.dependency_overrides[get_write_request_context] = lambda: WriteRequestContext(
        idempotency_key="test-idempotency-key", identity=identity, principal_scope="user:7"
    )
    # Task 16: diese Datei prueft Cluster-FACHLICHKEIT. Das App-weite Gate
    # (Session, Origin/CSRF, Idempotency-Key) wird in
    # tests/test_route_security.py bewiesen und hier nur erfuellt.
    install_browser_gate(app, sample_principal)
    try:
        with TestClient(app, headers=BROWSER_GATE_HEADERS) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.clear()


def test_get_suggestions(client, cluster_service):
    cluster_service.suggest_batches.return_value = [{"zone": "Links", "picking_ids": [1, 2]}]
    resp = client.get("/api/cluster/suggestions", headers={"X-Picker-User-Id": "7"})
    assert resp.status_code == 200
    assert resp.json()[0]["zone"] == "Links"


def test_suggestions_pass_picker_identity(client, cluster_service):
    cluster_service.suggest_batches.return_value = []
    resp = client.get(
        "/api/cluster/suggestions",
        headers={"X-Picker-User-Id": "7", "X-Device-Id": "dev-1"},
    )
    assert resp.status_code == 200
    _, kwargs = cluster_service.suggest_batches.call_args
    assert kwargs["picker_identity"].user_id == 7


def test_create_batch(client, cluster_service):
    cluster_service.create_batch.return_value = {"batch_id": 99}
    resp = client.post("/api/cluster/batches", json={"picking_ids": [1, 2]},
                       headers={"X-Picker-User-Id": "7", "X-Device-Id": "d1"})
    assert resp.status_code == 200
    assert resp.json()["batch_id"] == 99
    cluster_service.create_batch.assert_awaited_once()


def test_create_batch_replays_existing_idempotency_response(client, cluster_service):
    identity = PickerIdentity(user_id=7, device_id="device-42")
    workflow = AsyncMock()
    workflow.resolve_identity.return_value = identity
    workflow.build_request_fingerprint = Mock(return_value="test-fingerprint")
    workflow.begin_idempotent_request.return_value = IdempotencyReservation(
        status="replay", response_payload={"batch_id": 99}
    )
    app.dependency_overrides[get_mobile_workflow_service] = lambda: workflow
    app.dependency_overrides[get_write_request_context] = lambda: WriteRequestContext(
        idempotency_key="test-idempotency-key", identity=identity, principal_scope="picker:7"
    )
    try:
        response = client.post("/api/cluster/batches", json={"picking_ids": [1, 2]})
    finally:
        app.dependency_overrides.pop(get_mobile_workflow_service, None)
        app.dependency_overrides.pop(get_write_request_context, None)

    assert response.status_code == 200
    assert response.json() == {"batch_id": 99}
    cluster_service.create_batch.assert_not_awaited()


def test_create_batch_rejects_empty(client, cluster_service):
    resp = client.post("/api/cluster/batches", json={"picking_ids": []},
                       headers={"X-Picker-User-Id": "7", "X-Device-Id": "d1"})
    assert resp.status_code == 400


def test_create_batch_maps_capacity_error_to_422(client, cluster_service):
    cluster_service.create_batch.return_value = {
        "success": False,
        "error": "Cluster braucht mindestens 2 Auftraege.",
        "message": "Cluster braucht mindestens 2 Auftraege.",
        "code": "cluster_capacity",
    }
    resp = client.post(
        "/api/cluster/batches",
        json={"picking_ids": [1]},
        headers={"X-Picker-User-Id": "7", "X-Device-Id": "dev-1"},
    )
    assert resp.status_code == 422


def test_create_batch_maps_unavailable_error_to_503(client, cluster_service):
    cluster_service.create_batch.return_value = {
        "success": False,
        "error": "Cluster-Picking ist in dieser Odoo-Instanz nicht verfuegbar.",
        "message": "Cluster-Picking ist in dieser Odoo-Instanz nicht verfuegbar.",
        "code": "stock_picking_batch_unavailable",
        "unavailable": True,
    }
    resp = client.post(
        "/api/cluster/batches",
        json={"picking_ids": [1, 2]},
        headers={"X-Picker-User-Id": "7", "X-Device-Id": "dev-1"},
    )
    assert resp.status_code == 503


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
