import base64
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
    InvalidPickerIdentityError,
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


def test_product_image_uses_requested_variant_and_falls_back_to_original():
    odoo = MagicMock()
    original_png = base64.b64encode(b"\x89PNG\r\n\x1a\nfallback-image").decode()
    odoo.search_read = AsyncMock(
        return_value=[
            {
                "image_512": None,
                "image_1920": original_png,
            }
        ]
    )
    _override_dependencies(odoo=odoo)

    try:
        with TestClient(app) as client:
            response = client.get("/api/products/44/image?size=512")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    assert response.headers["x-image-variant"] == "512"
    odoo.search_read.assert_awaited_once_with(
        "product.product",
        [("id", "=", 44)],
        ["image_512", "image_1920"],
        limit=1,
    )


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
                headers={
                    "X-Picker-User-Id": "7",
                    "X-Device-Id": "device-1",
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
                headers={
                    "Idempotency-Key": "dup-1",
                    "X-Picker-User-Id": "7",
                    "X-Device-Id": "device-1",
                },
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
    n8n.fire_event = AsyncMock()
    _override_dependencies(workflow=workflow, odoo=odoo, n8n=n8n)

    try:
        with TestClient(app) as client:
            response = client.post(
                "/api/quality-alerts",
                data={"description": "Palette beschaedigt", "priority": "2"},
                headers={
                    "Idempotency-Key": "qa-1",
                    "X-Picker-User-Id": "7",
                    "X-Device-Id": "device-1",
                },
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json() == {"alert_id": 42, "name": "QA-100", "photo_count": 0}
    odoo.execute_kw.assert_not_awaited()
    n8n.fire_event.assert_not_awaited()


def test_list_pickings_requires_picker_header():
    workflow = _create_workflow_mock()
    picking_service = MagicMock()
    picking_service.get_open_pickings = AsyncMock(return_value=[])
    _override_dependencies(workflow=workflow, picking_service=picking_service)

    try:
        with TestClient(app) as client:
            response = client.get("/api/pickings")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 400
    assert response.json()["detail"] == "X-Picker-User-Id ist erforderlich."
    picking_service.get_open_pickings.assert_not_awaited()


def test_list_pickings_returns_403_for_inactive_picker():
    workflow = _create_workflow_mock()
    workflow.resolve_identity = AsyncMock(side_effect=InvalidPickerIdentityError(99))
    picking_service = MagicMock()
    picking_service.get_open_pickings = AsyncMock(return_value=[])
    _override_dependencies(workflow=workflow, picking_service=picking_service)

    try:
        with TestClient(app) as client:
            response = client.get("/api/pickings", headers={"X-Picker-User-Id": "99"})
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 403
    assert response.json()["detail"] == "Unbekannter oder inaktiver Picker."
    picking_service.get_open_pickings.assert_not_awaited()


def test_confirm_line_requires_full_identity_headers():
    workflow = _create_workflow_mock()
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
                headers={"X-Picker-User-Id": "7"},
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 400
    assert response.json()["detail"] == "X-Picker-User-Id und X-Device-Id sind fuer diese Aktion erforderlich."
    picking_service.confirm_pick_line.assert_not_awaited()


def test_quality_alert_requires_full_identity_headers():
    workflow = _create_workflow_mock()
    odoo = MagicMock()
    odoo.execute_kw = AsyncMock()
    n8n = MagicMock()
    n8n.fire_event = AsyncMock()
    _override_dependencies(workflow=workflow, odoo=odoo, n8n=n8n)

    try:
        with TestClient(app) as client:
            response = client.post(
                "/api/quality-alerts",
                data={"description": "Palette beschaedigt", "priority": "2"},
                headers={"X-Picker-User-Id": "7"},
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 400
    assert response.json()["detail"] == "X-Picker-User-Id und X-Device-Id sind fuer diese Aktion erforderlich."
    odoo.execute_kw.assert_not_awaited()
    n8n.fire_event.assert_not_awaited()
