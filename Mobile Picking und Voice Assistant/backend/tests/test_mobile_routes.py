from unittest.mock import AsyncMock, MagicMock

from fastapi.testclient import TestClient

from app.dependencies import (
    get_mobile_workflow_service,
    get_n8n_client,
    get_odoo_client,
    get_picking_service,
)
from app.main import app
from app.services.mobile_workflow import (
    ClaimConflictError,
    IdempotencyReservation,
    PickerIdentity,
)


def _override_dependencies(*, workflow=None, picking_service=None, odoo=None, n8n=None):
    app.dependency_overrides.clear()
    if workflow is not None:
        app.dependency_overrides[get_mobile_workflow_service] = lambda: workflow
    if picking_service is not None:
        app.dependency_overrides[get_picking_service] = lambda: picking_service
    if odoo is not None:
        app.dependency_overrides[get_odoo_client] = lambda: odoo
    if n8n is not None:
        app.dependency_overrides[get_n8n_client] = lambda: n8n


def _create_workflow_mock():
    workflow = MagicMock()
    workflow.build_request_fingerprint.return_value = "fingerprint-1"
    workflow.list_pickers = AsyncMock(return_value=[{"id": 7, "name": "Mina Muster"}])
    workflow.begin_idempotent_request = AsyncMock(
        return_value=IdempotencyReservation(status="reserved", entry_id=11),
    )
    workflow.finalize_idempotent_request = AsyncMock()
    workflow.abort_idempotent_request = AsyncMock()
    workflow.claim_picking = AsyncMock(return_value={"success": True, "status": "claimed"})
    workflow.heartbeat_picking = AsyncMock(return_value={"success": True, "status": "claimed"})
    workflow.release_picking = AsyncMock(return_value={"success": True, "status": "released"})
    workflow.resolve_identity = AsyncMock(
        return_value=PickerIdentity(user_id=7, device_id="device-1", picker_name="Mina Muster"),
    )
    return workflow


def test_list_pickers_returns_workflow_users():
    workflow = _create_workflow_mock()
    _override_dependencies(workflow=workflow)

    try:
        with TestClient(app) as client:
            response = client.get("/api/pickers")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json() == [{"id": 7, "name": "Mina Muster"}]


def test_confirm_line_replays_cached_response_without_duplicate_write():
    workflow = _create_workflow_mock()
    workflow.begin_idempotent_request = AsyncMock(
        return_value=IdempotencyReservation(
            status="replay",
            entry_id=19,
            response_payload={"success": True, "message": "Bestaetigt.", "picking_complete": False},
            status_code=200,
        )
    )
    picking_service = MagicMock()
    picking_service.confirm_pick_line = AsyncMock()
    _override_dependencies(workflow=workflow, picking_service=picking_service)

    try:
        with TestClient(app) as client:
            response = client.post(
                "/api/pickings/44/confirm-line",
                json={
                    "move_line_id": 900,
                    "scanned_barcode": "1234567890",
                    "quantity": 2,
                },
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["success"] is True
    picking_service.confirm_pick_line.assert_not_awaited()


def test_confirm_line_returns_409_for_conflicting_idempotency_key():
    workflow = _create_workflow_mock()
    workflow.begin_idempotent_request = AsyncMock(
        return_value=IdempotencyReservation(
            status="conflict",
            entry_id=19,
            response_payload={"detail": "Idempotency-Key wird bereits fuer einen anderen Request verwendet."},
            status_code=409,
        )
    )
    picking_service = MagicMock()
    picking_service.confirm_pick_line = AsyncMock()
    _override_dependencies(workflow=workflow, picking_service=picking_service)

    try:
        with TestClient(app) as client:
            response = client.post(
                "/api/pickings/44/confirm-line",
                json={
                    "move_line_id": 900,
                    "scanned_barcode": "1234567890",
                    "quantity": 2,
                },
                headers={"Idempotency-Key": "dup-1"},
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 409
    assert response.json()["detail"] == "Idempotency-Key wird bereits fuer einen anderen Request verwendet."
    picking_service.confirm_pick_line.assert_not_awaited()


def test_claim_returns_409_when_another_picker_holds_the_lock():
    workflow = _create_workflow_mock()
    workflow.claim_picking = AsyncMock(
        side_effect=ClaimConflictError(
            {
                "conflict": True,
                "claimed_by_name": "Kollege Schmidt",
                "claim_expires_at": "2026-03-24 10:02:00",
            }
        )
    )
    _override_dependencies(workflow=workflow)

    try:
        with TestClient(app) as client:
            response = client.post(
                "/api/pickings/44/claim",
                headers={
                    "Idempotency-Key": "claim-1",
                    "X-Picker-User-Id": "7",
                    "X-Device-Id": "device-1",
                },
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 409
    assert response.json()["detail"]["claimed_by_name"] == "Kollege Schmidt"


def test_quality_alert_replays_cached_response_without_duplicate_odoo_write():
    workflow = _create_workflow_mock()
    workflow.begin_idempotent_request = AsyncMock(
        return_value=IdempotencyReservation(
            status="replay",
            entry_id=33,
            response_payload={"alert_id": 42, "name": "QA-100", "photo_count": 0},
            status_code=200,
        )
    )
    odoo = MagicMock()
    odoo.execute_kw = AsyncMock()
    n8n = MagicMock()
    n8n.fire = AsyncMock()
    _override_dependencies(workflow=workflow, odoo=odoo, n8n=n8n)

    try:
        with TestClient(app) as client:
            response = client.post(
                "/api/quality-alerts",
                data={"description": "Palette beschaedigt", "priority": "2"},
                headers={"Idempotency-Key": "qa-1"},
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json() == {"alert_id": 42, "name": "QA-100", "photo_count": 0}
    odoo.execute_kw.assert_not_awaited()
    n8n.fire.assert_not_awaited()
