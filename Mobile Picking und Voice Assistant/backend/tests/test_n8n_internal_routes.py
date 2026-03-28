from unittest.mock import AsyncMock, MagicMock

from fastapi.testclient import TestClient

from app.config import settings
from app.dependencies import get_mobile_workflow_service, get_odoo_client
from app.main import app
from app.services.mobile_workflow import IdempotencyReservation


def _workflow_mock():
    workflow = MagicMock()
    workflow.build_request_fingerprint.return_value = "fingerprint-1"
    workflow.begin_idempotent_request = AsyncMock(
        return_value=IdempotencyReservation(status="reserved", entry_id=11),
    )
    workflow.finalize_idempotent_request = AsyncMock()
    workflow.abort_idempotent_request = AsyncMock()
    return workflow


def test_quality_assessment_callback_writes_ai_fields(monkeypatch):
    monkeypatch.setattr(settings, "n8n_callback_secret", "top-secret")
    workflow = _workflow_mock()
    odoo = MagicMock()
    odoo.write = AsyncMock(return_value=True)
    odoo.execute_kw = AsyncMock(return_value=True)
    app.dependency_overrides[get_mobile_workflow_service] = lambda: workflow
    app.dependency_overrides[get_odoo_client] = lambda: odoo

    try:
        with TestClient(app) as client:
            response = client.post(
                "/api/internal/n8n/quality-assessment",
                json={
                    "correlation_id": "corr-1",
                    "alert_id": 42,
                    "ai_disposition": "scrap",
                    "ai_confidence": 0.93,
                    "ai_summary": "Totalschaden am Karton und Inhalt.",
                    "ai_recommended_action": "Ware sperren und aussondern.",
                    "ai_provider": "openai",
                    "ai_model": "gpt-4o",
                },
                headers={
                    "X-N8N-Callback-Secret": "top-secret",
                    "Idempotency-Key": "corr-1",
                },
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["status"] == "applied"
    odoo.write.assert_awaited_once()
    assert odoo.write.call_args[0][0] == "quality.alert.custom"
    odoo.execute_kw.assert_awaited_once()
    assert odoo.execute_kw.call_args[0][0] == "quality.alert.custom"
    assert odoo.execute_kw.call_args[0][1] == "message_post"


def test_replenishment_callback_replays_without_duplicate_odoo_write(monkeypatch):
    monkeypatch.setattr(settings, "n8n_callback_secret", "top-secret")
    workflow = _workflow_mock()
    workflow.begin_idempotent_request = AsyncMock(
        return_value=IdempotencyReservation(
            status="replay",
            entry_id=11,
            response_payload={
                "status": "applied",
                "correlation_id": "corr-2",
                "detail": "Nachschubauftrag INT/0001 fuer Picking 44 angelegt.",
            },
            status_code=200,
        )
    )
    odoo = MagicMock()
    odoo.execute_kw = AsyncMock()
    app.dependency_overrides[get_mobile_workflow_service] = lambda: workflow
    app.dependency_overrides[get_odoo_client] = lambda: odoo

    try:
        with TestClient(app) as client:
            response = client.post(
                "/api/internal/n8n/replenishment-action",
                json={
                    "correlation_id": "corr-2",
                    "picking_id": 44,
                    "product_id": 5,
                    "location_id": 9,
                    "recommended_location_id": 12,
                    "reason": "Alternative Lagerplaetze gefunden.",
                    "ticket_text": "Bitte Nachschub fuer Produkt 5 pruefen.",
                },
                headers={
                    "X-N8N-Callback-Secret": "top-secret",
                    "Idempotency-Key": "corr-2",
                },
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["correlation_id"] == "corr-2"
    odoo.execute_kw.assert_not_awaited()


def test_replenishment_callback_creates_internal_transfer(monkeypatch):
    monkeypatch.setattr(settings, "n8n_callback_secret", "top-secret")
    workflow = _workflow_mock()
    odoo = MagicMock()
    odoo.execute_kw = AsyncMock(
        return_value={
            "success": True,
            "replenishment_name": "INT/0007",
            "replenishment_picking_id": 71,
        }
    )
    app.dependency_overrides[get_mobile_workflow_service] = lambda: workflow
    app.dependency_overrides[get_odoo_client] = lambda: odoo

    try:
        with TestClient(app) as client:
            response = client.post(
                "/api/internal/n8n/replenishment-action",
                json={
                    "correlation_id": "corr-3",
                    "picking_id": 44,
                    "product_id": 5,
                    "location_id": 9,
                    "recommended_location_id": 12,
                    "recommended_location": "WH/Stock/B-01",
                    "quantity": 2,
                    "reason": "Am Zielplatz ist kein Bestand verfuegbar.",
                    "requested_by_user_id": 7,
                    "requested_by_name": "Mina Muster",
                },
                headers={
                    "X-N8N-Callback-Secret": "top-secret",
                    "Idempotency-Key": "corr-3",
                },
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["status"] == "applied"
    odoo.execute_kw.assert_awaited_once()
    assert odoo.execute_kw.call_args[0][0] == "stock.picking"
    assert odoo.execute_kw.call_args[0][1] == "api_create_replenishment_transfer"


def test_quality_assessment_callback_sets_completed_status(monkeypatch):
    """Verify the quality-assessment callback writes ai_evaluation_status and ai_failure_reason."""
    monkeypatch.setattr(settings, "n8n_callback_secret", "top-secret")
    workflow = _workflow_mock()
    odoo = MagicMock()
    odoo.write = AsyncMock(return_value=True)
    odoo.execute_kw = AsyncMock(return_value=True)
    app.dependency_overrides[get_mobile_workflow_service] = lambda: workflow
    app.dependency_overrides[get_odoo_client] = lambda: odoo

    try:
        with TestClient(app) as client:
            response = client.post(
                "/api/internal/n8n/quality-assessment",
                json={
                    "correlation_id": "corr-status-1",
                    "alert_id": 99,
                    "ai_disposition": "use_as_is",
                    "ai_confidence": 0.88,
                    "ai_summary": "Ware ist in Ordnung.",
                    "ai_provider": "openai",
                    "ai_model": "gpt-4o",
                },
                headers={
                    "X-N8N-Callback-Secret": "top-secret",
                    "Idempotency-Key": "corr-status-1",
                },
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["status"] == "applied"
    odoo.write.assert_awaited_once()
    write_fields = odoo.write.call_args[0][2]
    assert write_fields["ai_evaluation_status"] == "completed"
    assert write_fields["ai_failure_reason"] is False
    chatter_call = odoo.execute_kw.call_args
    assert chatter_call[0][0] == "quality.alert.custom"
    assert chatter_call[0][1] == "message_post"
    assert "KI-Bewertung abgeschlossen" in chatter_call[0][3]["body"]


def test_quality_assessment_failed_sets_failed_status(monkeypatch):
    """POST /quality-assessment-failed sets ai_evaluation_status to 'failed'."""
    monkeypatch.setattr(settings, "n8n_callback_secret", "top-secret")
    odoo = MagicMock()
    odoo.write = AsyncMock(return_value=True)
    odoo.execute_kw = AsyncMock(side_effect=[True, [91], 1])
    app.dependency_overrides[get_odoo_client] = lambda: odoo

    try:
        with TestClient(app) as client:
            response = client.post(
                "/api/internal/n8n/quality-assessment-failed",
                json={
                    "alert_id": 42,
                    "correlation_id": "corr-1",
                    "failure_reason": "Workflow timeout",
                },
                headers={"X-N8N-Callback-Secret": "top-secret"},
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["status"] == "applied"
    odoo.write.assert_awaited_once()
    write_fields = odoo.write.call_args[0][2]
    assert write_fields["ai_evaluation_status"] == "failed"
    assert write_fields["ai_failure_reason"] == "Workflow timeout"
    chatter_call = odoo.execute_kw.call_args_list[0]
    assert chatter_call[0][0] == "quality.alert.custom"
    assert chatter_call[0][1] == "message_post"
    assert "KI-Bewertung fehlgeschlagen" in chatter_call[0][3]["body"]
    model_search_call = odoo.execute_kw.call_args_list[1]
    assert model_search_call[0][0] == "ir.model"
    assert model_search_call[0][1] == "search"
    activity_call = odoo.execute_kw.call_args_list[2]
    assert activity_call[0][0] == "mail.activity"
    assert activity_call[0][1] == "create"
    assert activity_call[0][2][0]["summary"] == "KI-Bewertung fehlgeschlagen"


def test_quality_assessment_failed_rejects_wrong_secret(monkeypatch):
    """POST /quality-assessment-failed with wrong secret returns 403."""
    monkeypatch.setattr(settings, "n8n_callback_secret", "top-secret")
    odoo = MagicMock()
    app.dependency_overrides[get_odoo_client] = lambda: odoo

    try:
        with TestClient(app) as client:
            response = client.post(
                "/api/internal/n8n/quality-assessment-failed",
                json={
                    "alert_id": 42,
                    "correlation_id": "corr-1",
                    "failure_reason": "Workflow timeout",
                },
                headers={"X-N8N-Callback-Secret": "wrong-secret"},
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 403


def test_manual_review_activity_posts_note(monkeypatch):
    """POST /manual-review-activity posts a chatter note via message_post."""
    monkeypatch.setattr(settings, "n8n_callback_secret", "top-secret")
    odoo = MagicMock()
    odoo.execute_kw = AsyncMock(return_value=[1])
    app.dependency_overrides[get_odoo_client] = lambda: odoo

    try:
        with TestClient(app) as client:
            response = client.post(
                "/api/internal/n8n/manual-review-activity",
                json={
                    "picking_id": 10,
                    "correlation_id": "corr-2",
                    "reason": "Shortage workflow failed",
                },
                headers={"X-N8N-Callback-Secret": "top-secret"},
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["status"] == "applied"
    # First call should be message_post
    first_call = odoo.execute_kw.call_args_list[0]
    assert first_call[0][0] == "stock.picking"
    assert first_call[0][1] == "message_post"


def test_manual_review_activity_with_execution_url(monkeypatch):
    """POST /manual-review-activity with execution_url includes URL in chatter note."""
    monkeypatch.setattr(settings, "n8n_callback_secret", "top-secret")
    odoo = MagicMock()
    odoo.execute_kw = AsyncMock(return_value=[1])
    app.dependency_overrides[get_odoo_client] = lambda: odoo

    try:
        with TestClient(app) as client:
            response = client.post(
                "/api/internal/n8n/manual-review-activity",
                json={
                    "picking_id": 10,
                    "correlation_id": "corr-3",
                    "reason": "Shortage workflow failed",
                    "execution_url": "https://n8n.local/execution/123",
                },
                headers={"X-N8N-Callback-Secret": "top-secret"},
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    # First call is message_post; check the HTML body contains the URL
    first_call = odoo.execute_kw.call_args_list[0]
    note_html = first_call[1]["body"] if "body" in (first_call[1] or {}) else first_call[0][3].get("body", "")
    assert "https://n8n.local/execution/123" in note_html
