from unittest.mock import AsyncMock, MagicMock

from fastapi.testclient import TestClient

from app.dependencies import get_n8n_client, get_odoo_client, get_picking_service
from app.main import app
from app.routers import voice as voice_router
from app.services.n8n_webhook import N8NReply


def test_voice_recognize_returns_additive_fields_and_detail_context(monkeypatch):
    monkeypatch.setattr(voice_router, "convert_to_wav", AsyncMock(return_value=b"wav-bytes"))
    monkeypatch.setattr(
        voice_router.whisper_client,
        "transcribe_audio",
        AsyncMock(return_value="ja"),
    )

    with TestClient(app) as client:
        response = client.post(
            "/api/voice/recognize",
            data={
                "context": "awaiting_command",
                "surface": "detail",
                "remaining_line_count": "1",
                "active_line_present": "true",
            },
            files={"audio": ("voice.webm", b"1234", "audio/webm")},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["intent"] == "confirm"
    assert payload["normalized_text"] == "ja"
    assert payload["match_strategy"] == "exact"


def test_voice_recognize_blocks_detail_confirm_in_list_context(monkeypatch):
    monkeypatch.setattr(voice_router, "convert_to_wav", AsyncMock(return_value=b"wav-bytes"))
    monkeypatch.setattr(
        voice_router.whisper_client,
        "transcribe_audio",
        AsyncMock(return_value="ja"),
    )

    with TestClient(app) as client:
        response = client.post(
            "/api/voice/recognize",
            data={
                "context": "awaiting_command",
                "surface": "list",
                "remaining_line_count": "3",
                "active_line_present": "false",
            },
            files={"audio": ("voice.webm", b"1234", "audio/webm")},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["intent"] == "unknown"
    assert payload["match_strategy"] == "unknown"


def test_voice_recognize_allows_done_only_when_no_lines_remain(monkeypatch):
    monkeypatch.setattr(voice_router, "convert_to_wav", AsyncMock(return_value=b"wav-bytes"))
    monkeypatch.setattr(
        voice_router.whisper_client,
        "transcribe_audio",
        AsyncMock(return_value="fertig"),
    )

    with TestClient(app) as client:
        done_response = client.post(
            "/api/voice/recognize",
            data={
                "context": "awaiting_command",
                "surface": "complete",
                "remaining_line_count": "0",
                "active_line_present": "false",
            },
            files={"audio": ("voice.webm", b"1234", "audio/webm")},
        )
        blocked_response = client.post(
            "/api/voice/recognize",
            data={
                "context": "awaiting_command",
                "surface": "detail",
                "remaining_line_count": "2",
                "active_line_present": "true",
            },
            files={"audio": ("voice.webm", b"1234", "audio/webm")},
        )

    assert done_response.status_code == 200
    assert done_response.json()["intent"] == "done"
    assert blocked_response.status_code == 200
    assert blocked_response.json()["intent"] == "unknown"


def test_voice_assist_returns_n8n_response():
    picking_service = MagicMock()
    picking_service.get_picking_detail = AsyncMock(
        return_value={
            "id": 44,
            "priority": "2",
            "origin": "[324876] LEGO Ente (BOM 324876)",
            "kit_name": "LEGO Ente",
            "voice_intro": "LEGO Ente. A-01. 10 Stueck. Schraube M8.",
            "move_lines": [
                {
                    "id": 20,
                    "product_id": 5,
                    "location_src_id": 9,
                    "ui_display": "Schraube M8",
                }
            ],
        }
    )
    n8n = MagicMock()
    n8n.request_reply = AsyncMock(
        return_value=N8NReply(
            status="ok",
            tts_text="Du baust die LEGO Ente.",
            source="n8n",
            correlation_id="corr-1",
            latency_ms=321,
        )
    )
    odoo = MagicMock()
    odoo.search_read = AsyncMock(return_value=[])
    app.dependency_overrides[get_picking_service] = lambda: picking_service
    app.dependency_overrides[get_n8n_client] = lambda: n8n
    app.dependency_overrides[get_odoo_client] = lambda: odoo

    try:
        with TestClient(app) as client:
            response = client.post(
                "/api/voice/assist",
                json={
                    "text": "Was baue ich hier?",
                    "intent": "unknown",
                    "surface": "detail",
                    "picking_id": 44,
                    "move_line_id": 20,
                    "remaining_line_count": 0,
                },
                headers={
                    "X-Picker-User-Id": "7",
                    "X-Device-Id": "device-1",
                },
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    payload = response.json()
    assert payload["tts_text"] == "Du baust die LEGO Ente."
    assert payload["source"] == "n8n"
    n8n.request_reply.assert_awaited_once()
    assert n8n.request_reply.call_args[1]["picking_context"]["location_id"] == 9


def test_voice_assist_returns_local_message_for_fast_path_intents():
    n8n = MagicMock()
    n8n.request_reply = AsyncMock()
    app.dependency_overrides[get_n8n_client] = lambda: n8n

    try:
        with TestClient(app) as client:
            response = client.post(
                "/api/voice/assist",
                json={
                    "text": "bestaetigen",
                    "intent": "confirm",
                    "surface": "detail",
                },
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "not_applicable"
    assert payload["fallback_reason"] == "local_intent"
    n8n.request_reply.assert_not_awaited()


def test_voice_assist_triggers_shortage_event_from_local_fallback():
    picking_service = MagicMock()
    picking_service.get_picking_detail = AsyncMock(
        return_value={
            "id": 44,
            "priority": "2",
            "origin": "[324876] LEGO Ente (BOM 324876)",
            "kit_name": "LEGO Ente",
            "voice_intro": "LEGO Ente. A-01. 10 Stueck. Schraube M8.",
            "move_lines": [
                {
                    "id": 20,
                    "product_id": 5,
                    "location_src_id": 9,
                    "location_src": "WH/Stock/A-01",
                    "ui_display": "Schraube M8",
                }
            ],
        }
    )
    n8n = MagicMock()
    n8n.request_reply = AsyncMock(
        return_value=N8NReply(
            status="fallback",
            tts_text="Ich kann das gerade nicht sicher beantworten.",
            source="fastapi-fallback",
            correlation_id="corr-9",
            latency_ms=120,
            fallback_reason="timeout",
        )
    )
    n8n.fire_event = AsyncMock(return_value="corr-shortage")
    odoo = MagicMock()
    odoo.search_read = AsyncMock(
        return_value=[
            {"quantity": 0, "reserved_quantity": 0, "location_id": [9, "WH/Stock/A-01"]},
            {"quantity": 4, "reserved_quantity": 0, "location_id": [12, "WH/Stock/B-01"]},
        ]
    )
    app.dependency_overrides[get_picking_service] = lambda: picking_service
    app.dependency_overrides[get_n8n_client] = lambda: n8n
    app.dependency_overrides[get_odoo_client] = lambda: odoo

    try:
        with TestClient(app) as client:
            response = client.post(
                "/api/voice/assist",
                json={
                    "text": "Fehlmenge bei Schraube M8",
                    "intent": "problem",
                    "surface": "detail",
                    "picking_id": 44,
                    "move_line_id": 20,
                    "remaining_line_count": 0,
                },
                headers={
                    "X-Picker-User-Id": "7",
                    "X-Device-Id": "device-1",
                },
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    payload = response.json()
    assert "Nachschub" in payload["tts_text"]
    assert payload["source"] == "fastapi-local-context"
    n8n.fire_event.assert_awaited_once()
    fired_payload = n8n.fire_event.call_args[0][1]
    assert fired_payload["recommendation"]["recommended_location_id"] == 12
