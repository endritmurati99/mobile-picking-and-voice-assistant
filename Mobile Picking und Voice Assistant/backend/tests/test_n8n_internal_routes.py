import json
from unittest.mock import AsyncMock, MagicMock

from fastapi.testclient import TestClient

from app.config import settings
from app.dependencies import get_mobile_workflow_service, get_odoo_client
from app.main import app
from app.services.quality_shadow_evaluation import classify_quality_alert_shadow
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


def _structured_events(caplog):
    events = []
    for record in caplog.records:
        try:
            payload = json.loads(record.getMessage())
        except (TypeError, json.JSONDecodeError):
            continue
        if isinstance(payload, dict) and "callback_type" in payload:
            events.append(payload)
    return events


def _shadow_events(caplog):
    events = []
    for record in caplog.records:
        try:
            payload = json.loads(record.getMessage())
        except (TypeError, json.JSONDecodeError):
            continue
        if isinstance(payload, dict) and payload.get("event_type") == "quality_shadow_evaluation":
            events.append(payload)
    return events


def test_quality_assessment_callback_writes_ai_fields(monkeypatch, caplog):
    monkeypatch.setattr(settings, "n8n_callback_secret", "top-secret")
    caplog.set_level("INFO", logger="app.routers.n8n_internal")
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
                    "ai_summary": "Totalschaden am Karton <b>und</b> Inhalt.",
                    "ai_enhanced_description": "<strong>Artikel</strong> mit starkem Verpackungsschaden",
                    "ai_photo_analysis": "<p>Eingedrueckte Ecke und Riss an der Aussenverpackung sichtbar.</p>",
                    "ai_recommended_action": "<i>Ware sperren und aussondern.</i>",
                    "ai_provider": "openai",
                    "ai_model": "gpt-4o",
                    "schema_version": "v1",
                    "execution_id": "exec-qa-1",
                    "latency_tracking": {
                        "started_at": "2026-03-31T10:00:00Z",
                        "total_duration_ms": 123,
                        "stages": {
                            "ingest_ms": 5,
                            "heuristic_ms": 14,
                            "callback_ms": 21,
                        },
                        "extra_stages": {
                            "network_ms": 83,
                        },
                    },
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
    write_fields = odoo.write.call_args[0][2]
    assert write_fields["ai_summary"] == "Totalschaden am Karton und Inhalt."
    assert write_fields["ai_enhanced_description"] == "Artikel mit starkem Verpackungsschaden"
    assert write_fields["ai_photo_analysis"] == "Eingedrueckte Ecke und Riss an der Aussenverpackung sichtbar."
    assert write_fields["ai_recommended_action"] == "Ware sperren und aussondern."
    odoo.execute_kw.assert_awaited_once()
    assert odoo.execute_kw.call_args[0][0] == "quality.alert.custom"
    assert odoo.execute_kw.call_args[0][1] == "message_post"
    chatter_body = odoo.execute_kw.call_args[0][3]["body"]
    assert "KI-verbesserte Beschreibung:" in chatter_body
    assert "Fotoanalyse:" in chatter_body
    assert "<" not in chatter_body
    event = next(
        payload
        for payload in _structured_events(caplog)
        if payload["callback_type"] == "quality_assessment" and payload["callback_status"] == "applied"
    )
    assert event["workflow_name"] == "quality-alert-created"
    assert event["schema_version"] == "v1"
    assert event["execution_id"] == "exec-qa-1"
    assert event["legacy_payload"] is False
    assert event["latency_tracking"]["stages"]["heuristic_ms"] == 14
    assert event["latency_tracking"]["extra_stages"]["network_ms"] == 83


def test_quality_assessment_ai_callback_logs_shadow_evaluation_without_odoo_write(monkeypatch, caplog):
    monkeypatch.setattr(settings, "n8n_callback_secret", "top-secret")
    caplog.set_level("INFO", logger="app.routers.n8n_internal")
    workflow = _workflow_mock()
    odoo = MagicMock()
    odoo.search_read = AsyncMock(
        return_value=[
            {
                "id": 42,
                "name": "QA/0042",
                "description": "Artikel beschaedigt, Karton gerissen.",
                "priority": "0",
                "photo_count": 2,
                "product_id": [7, "Brick 2x2"],
                "location_id": [15, "WH/Stock/A-01"],
            }
        ]
    )
    odoo.write = AsyncMock()
    odoo.execute_kw = AsyncMock()
    app.dependency_overrides[get_mobile_workflow_service] = lambda: workflow
    app.dependency_overrides[get_odoo_client] = lambda: odoo

    try:
        with TestClient(app) as client:
            response = client.post(
                "/api/internal/n8n/quality-assessment-ai",
                json={
                    "schema_version": "v1",
                    "execution_id": "exec-ai-1",
                    "latency_tracking": {
                        "started_at": "2026-03-31T11:00:00Z",
                        "total_duration_ms": 430,
                        "stages": {
                            "ingest_ms": 25,
                            "callback_ms": 9,
                        },
                        "extra_stages": {
                            "ai_shadow_ms": 412,
                        },
                    },
                    "correlation_id": "corr-ai-1",
                    "alert_id": 42,
                    "category": "damage",
                    "confidence": 0.81,
                    "reason": "Beschreibung spricht klar fuer einen Verpackungsschaden.",
                    "model": "gpt-4o-mini",
                },
                headers={
                    "X-N8N-Callback-Secret": "top-secret",
                    "Idempotency-Key": "corr-ai-1",
                },
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["status"] == "applied"
    odoo.search_read.assert_awaited_once()
    odoo.write.assert_not_awaited()
    odoo.execute_kw.assert_not_awaited()
    callback_event = next(
        payload
        for payload in _structured_events(caplog)
        if payload["callback_type"] == "quality_assessment_ai" and payload["callback_status"] == "applied"
    )
    assert callback_event["workflow_name"] == "quality-alert-ai-evaluation"
    shadow_event = _shadow_events(caplog)[0]
    assert shadow_event["alert_id"] == 42
    assert shadow_event["heuristic_category"] == "damage"
    assert shadow_event["ai_category"] == "damage"
    assert shadow_event["match"] is True
    assert shadow_event["ai_latency_ms"] == 412
    assert shadow_event["text_length"] == len("Artikel beschaedigt, Karton gerissen.")
    assert shadow_event["has_photo"] is True
    assert shadow_event["photo_count"] == 2
    assert shadow_event["model"] == "gpt-4o-mini"


def test_quality_assessment_ai_callback_rejects_empty_reason(monkeypatch):
    monkeypatch.setattr(settings, "n8n_callback_secret", "top-secret")
    workflow = _workflow_mock()
    odoo = MagicMock()
    app.dependency_overrides[get_mobile_workflow_service] = lambda: workflow
    app.dependency_overrides[get_odoo_client] = lambda: odoo

    try:
        with TestClient(app) as client:
            response = client.post(
                "/api/internal/n8n/quality-assessment-ai",
                json={
                    "schema_version": "v1",
                    "execution_id": "exec-ai-2",
                    "latency_tracking": {
                        "started_at": "2026-03-31T11:00:00Z",
                        "total_duration_ms": 300,
                        "stages": {
                            "callback_ms": 4,
                        },
                    },
                    "correlation_id": "corr-ai-2",
                    "alert_id": 77,
                    "category": "damage",
                    "confidence": 0.74,
                    "reason": "   ",
                    "model": "gpt-4o-mini",
                },
                headers={
                    "X-N8N-Callback-Secret": "top-secret",
                    "Idempotency-Key": "corr-ai-2",
                },
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 422


def test_quality_assessment_ai_callback_requires_matching_idempotency_key(monkeypatch):
    monkeypatch.setattr(settings, "n8n_callback_secret", "top-secret")
    workflow = _workflow_mock()
    odoo = MagicMock()
    app.dependency_overrides[get_mobile_workflow_service] = lambda: workflow
    app.dependency_overrides[get_odoo_client] = lambda: odoo

    try:
        with TestClient(app) as client:
            response = client.post(
                "/api/internal/n8n/quality-assessment-ai",
                json={
                    "schema_version": "v1",
                    "execution_id": "exec-ai-3",
                    "latency_tracking": {
                        "started_at": "2026-03-31T11:00:00Z",
                        "total_duration_ms": 300,
                        "stages": {
                            "callback_ms": 4,
                        },
                    },
                    "correlation_id": "corr-ai-3",
                    "alert_id": 77,
                    "category": "unclear",
                    "confidence": 0.41,
                    "reason": "Keine klaren Signale im Text.",
                    "model": "gpt-4o-mini",
                },
                headers={
                    "X-N8N-Callback-Secret": "top-secret",
                    "Idempotency-Key": "different-key",
                },
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 409
    assert response.json()["detail"] == "correlation_id und Idempotency-Key muessen identisch sein."


def test_shadow_heuristic_classifies_research_categories_deterministically():
    assert classify_quality_alert_shadow({"description": "Artikel beschaedigt und gerissen"}).category == "damage"
    assert classify_quality_alert_shadow({"description": "Ein Teil fehlt, Fehlmenge im Karton"}).category == "shortage"
    assert classify_quality_alert_shadow({"description": "Falscher Artikel geliefert, anderes Produkt im Karton"}).category == "wrong_item"
    assert classify_quality_alert_shadow({"description": "Bitte pruefen"}).category == "unclear"


def test_quality_assessment_callback_accepts_legacy_payload_and_ignores_unknown_telemetry_fields(
    monkeypatch,
    caplog,
):
    monkeypatch.setattr(settings, "n8n_callback_secret", "top-secret")
    caplog.set_level("INFO", logger="app.routers.n8n_internal")
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
                    "correlation_id": "corr-legacy-1",
                    "alert_id": 77,
                    "ai_disposition": "quarantine",
                    "ai_confidence": 0.72,
                    "ai_summary": "Verdacht auf Feuchtigkeitsschaden.",
                    "producer_timestamp": "2026-03-31T10:02:00Z",
                    "latency_tracking": {
                        "started_at": "2026-03-31T10:01:58Z",
                        "total_duration_ms": 48,
                        "stages": {
                            "ingest_ms": 4,
                            "heuristic_ms": 9,
                            "callback_ms": 11,
                        },
                        "extra_stages": {
                            "upstream_ms": 24,
                        },
                        "unexpected_metric_bundle": {
                            "ignored": True,
                        },
                    },
                },
                headers={
                    "X-N8N-Callback-Secret": "top-secret",
                    "Idempotency-Key": "corr-legacy-1",
                },
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["status"] == "applied"
    event = next(
        payload
        for payload in _structured_events(caplog)
        if payload["callback_type"] == "quality_assessment" and payload["correlation_id"] == "corr-legacy-1"
    )
    assert event["callback_status"] == "applied"
    assert event["schema_version"] is None
    assert event["legacy_payload"] is True
    assert event["latency_tracking"]["total_duration_ms"] == 48
    assert "unexpected_metric_bundle" not in event["latency_tracking"]


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
    assert write_fields["ai_enhanced_description"] is False
    assert write_fields["ai_photo_analysis"] is False
    chatter_call = odoo.execute_kw.call_args
    assert chatter_call[0][0] == "quality.alert.custom"
    assert chatter_call[0][1] == "message_post"
    assert "KI-Bewertung abgeschlossen" in chatter_call[0][3]["body"]
    assert "<" not in chatter_call[0][3]["body"]


def test_quality_assessment_failed_sets_failed_status(monkeypatch):
    """POST /quality-assessment-failed sets ai_evaluation_status to 'failed'."""
    monkeypatch.setattr(settings, "n8n_callback_secret", "top-secret")
    workflow = _workflow_mock()
    odoo = MagicMock()
    odoo.write = AsyncMock(return_value=True)
    odoo.execute_kw = AsyncMock(side_effect=[True, [91], 1])
    app.dependency_overrides[get_mobile_workflow_service] = lambda: workflow
    app.dependency_overrides[get_odoo_client] = lambda: odoo

    try:
        with TestClient(app) as client:
            response = client.post(
                "/api/internal/n8n/quality-assessment-failed",
                json={
                    "alert_id": 42,
                    "correlation_id": "corr-1",
                    "failure_reason": "<b>Workflow timeout</b>",
                    "schema_version": "v1",
                    "execution_id": "exec-error-1",
                    "latency_tracking": {
                        "started_at": "2026-03-31T10:03:00Z",
                        "total_duration_ms": 88,
                        "stages": {
                            "callback_ms": 12,
                        },
                    },
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
    write_fields = odoo.write.call_args[0][2]
    assert write_fields["ai_evaluation_status"] == "failed"
    assert write_fields["ai_failure_reason"] == "Workflow timeout"
    chatter_call = odoo.execute_kw.call_args_list[0]
    assert chatter_call[0][0] == "quality.alert.custom"
    assert chatter_call[0][1] == "message_post"
    assert "KI-Bewertung fehlgeschlagen" in chatter_call[0][3]["body"]
    assert "<" not in chatter_call[0][3]["body"]
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
    workflow = _workflow_mock()
    odoo = MagicMock()
    app.dependency_overrides[get_mobile_workflow_service] = lambda: workflow
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
                headers={
                    "X-N8N-Callback-Secret": "wrong-secret",
                    "Idempotency-Key": "corr-1",
                },
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 403


def test_quality_assessment_failed_requires_idempotency_key(monkeypatch):
    monkeypatch.setattr(settings, "n8n_callback_secret", "top-secret")
    workflow = _workflow_mock()
    odoo = MagicMock()
    app.dependency_overrides[get_mobile_workflow_service] = lambda: workflow
    app.dependency_overrides[get_odoo_client] = lambda: odoo

    try:
        with TestClient(app) as client:
            response = client.post(
                "/api/internal/n8n/quality-assessment-failed",
                json={
                    "alert_id": 42,
                    "correlation_id": "corr-missing-idem",
                    "failure_reason": "Workflow timeout",
                },
                headers={"X-N8N-Callback-Secret": "top-secret"},
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 400
    assert response.json()["detail"] == "Idempotency-Key ist erforderlich."
    workflow.begin_idempotent_request.assert_not_awaited()


def test_manual_review_activity_posts_note(monkeypatch):
    """POST /manual-review-activity posts a chatter note via message_post."""
    monkeypatch.setattr(settings, "n8n_callback_secret", "top-secret")
    workflow = _workflow_mock()
    odoo = MagicMock()
    odoo.execute_kw = AsyncMock(return_value=[1])
    app.dependency_overrides[get_mobile_workflow_service] = lambda: workflow
    app.dependency_overrides[get_odoo_client] = lambda: odoo

    try:
        with TestClient(app) as client:
            response = client.post(
                "/api/internal/n8n/manual-review-activity",
                json={
                    "picking_id": 10,
                    "correlation_id": "corr-2",
                    "reason": "Shortage workflow failed",
                    "schema_version": "v1",
                },
                headers={
                    "X-N8N-Callback-Secret": "top-secret",
                    "Idempotency-Key": "corr-2",
                },
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
    workflow = _workflow_mock()
    odoo = MagicMock()
    odoo.execute_kw = AsyncMock(return_value=[1])
    app.dependency_overrides[get_mobile_workflow_service] = lambda: workflow
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
                headers={
                    "X-N8N-Callback-Secret": "top-secret",
                    "Idempotency-Key": "corr-3",
                },
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    # First call is message_post; check the HTML body contains the URL
    first_call = odoo.execute_kw.call_args_list[0]
    note_html = first_call[1]["body"] if "body" in (first_call[1] or {}) else first_call[0][3].get("body", "")
    assert "https://n8n.local/execution/123" in note_html


def test_manual_review_activity_requires_idempotency_key(monkeypatch):
    monkeypatch.setattr(settings, "n8n_callback_secret", "top-secret")
    workflow = _workflow_mock()
    odoo = MagicMock()
    app.dependency_overrides[get_mobile_workflow_service] = lambda: workflow
    app.dependency_overrides[get_odoo_client] = lambda: odoo

    try:
        with TestClient(app) as client:
            response = client.post(
                "/api/internal/n8n/manual-review-activity",
                json={
                    "picking_id": 10,
                    "correlation_id": "corr-missing-manual-idem",
                    "reason": "Shortage workflow failed",
                },
                headers={"X-N8N-Callback-Secret": "top-secret"},
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 400
    assert response.json()["detail"] == "Idempotency-Key ist erforderlich."
    workflow.begin_idempotent_request.assert_not_awaited()


def test_manual_review_activity_replay_returns_cached_response_without_duplicate_write(monkeypatch):
    monkeypatch.setattr(settings, "n8n_callback_secret", "top-secret")
    workflow = _workflow_mock()
    workflow.begin_idempotent_request = AsyncMock(
        return_value=IdempotencyReservation(
            status="replay",
            entry_id=17,
            response_payload={
                "status": "applied",
                "correlation_id": "corr-manual-replay",
                "detail": "Review-Notiz und Aktivitaet fuer Picking 10 erstellt.",
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
                "/api/internal/n8n/manual-review-activity",
                json={
                    "picking_id": 10,
                    "correlation_id": "corr-manual-replay",
                    "reason": "Shortage workflow failed",
                    "schema_version": "v1",
                },
                headers={
                    "X-N8N-Callback-Secret": "top-secret",
                    "Idempotency-Key": "corr-manual-replay",
                },
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["correlation_id"] == "corr-manual-replay"
    odoo.execute_kw.assert_not_awaited()
