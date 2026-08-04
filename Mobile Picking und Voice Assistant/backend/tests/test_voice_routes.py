from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.dependencies import get_n8n_client, get_odoo_client, get_picking_service, get_request_odoo_client
from app.main import app
from tests.conftest import BROWSER_GATE_HEADERS
from app.routers import voice as voice_router
from app.services.n8n_webhook import N8NEventResult, N8NReply


@pytest.fixture(autouse=True)
def _mobile_header_grace_mode_enabled(monkeypatch):
    """These route tests authenticate via bare X-Picker-User-Id/X-Device-Id
    headers instead of a session cookie. Since Task 1 (Security Boundaries),
    grace mode defaults to off, so it must be enabled explicitly here to keep
    exercising that header-only identity path in development.
    """
    monkeypatch.setattr(settings, "runtime_profile", "development")
    monkeypatch.setattr(settings, "mobile_header_grace_mode", True)


def test_voice_recognize_returns_additive_fields_and_detail_context(monkeypatch):
    monkeypatch.setattr(voice_router, "convert_to_wav", AsyncMock(return_value=b"wav-bytes"))
    monkeypatch.setattr(
        voice_router.whisper_client,
        "transcribe_audio",
        AsyncMock(return_value="ja"),
    )

    with TestClient(app, headers=BROWSER_GATE_HEADERS) as client:
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

    with TestClient(app, headers=BROWSER_GATE_HEADERS) as client:
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

    with TestClient(app, headers=BROWSER_GATE_HEADERS) as client:
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


def test_voice_recognize_blocks_done_when_last_line_is_still_active(monkeypatch):
    monkeypatch.setattr(voice_router, "convert_to_wav", AsyncMock(return_value=b"wav-bytes"))
    monkeypatch.setattr(
        voice_router.whisper_client,
        "transcribe_audio",
        AsyncMock(return_value="fertig"),
    )

    with TestClient(app, headers=BROWSER_GATE_HEADERS) as client:
        response = client.post(
            "/api/voice/recognize",
            data={
                "context": "awaiting_command",
                "surface": "detail",
                "remaining_line_count": "0",
                "active_line_present": "true",
            },
            files={"audio": ("voice.webm", b"1234", "audio/webm")},
        )

    assert response.status_code == 200
    assert response.json()["intent"] == "unknown"


def test_voice_assist_answers_from_local_context():
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
    app.dependency_overrides[get_request_odoo_client] = lambda: odoo

    try:
        with TestClient(app, headers=BROWSER_GATE_HEADERS) as client:
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
    # Die Antwort kommt aus dem lokalen Kontext, nicht aus n8n: der v1-Workflow
    # `voice-exception-query` ist weg, und ein synchroner Aufruf ins Leere hat
    # jede Sprachanfrage 7 s gekostet, bevor er auf genau diesen Text zurueckfiel.
    assert payload["source"] == "fastapi-local-context"
    assert payload["status"] == "ok"
    assert "LEGO Ente" in payload["tts_text"]
    n8n.request_reply.assert_not_awaited()


def test_voice_assist_returns_local_message_for_fast_path_intents():
    n8n = MagicMock()
    n8n.request_reply = AsyncMock()
    app.dependency_overrides[get_n8n_client] = lambda: n8n

    try:
        with TestClient(app, headers=BROWSER_GATE_HEADERS) as client:
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


def test_voice_assist_reports_the_shortage_without_claiming_an_action():
    """Empfehlung sichtbar, aber nichts wird ausgeloest -- und der Text sagt das auch.

    Der v1-Workflow `shortage-reported` ist weg. Solange kein Nachfolger den
    Nachschub anstoesst, darf die Ansage ihn nicht behaupten: eine Stimme, die
    "ich leite ein" sagt und nichts einleitet, ist schlimmer als eine, die den
    Befund nennt und es dem Picker ueberlaesst.
    """
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
    odoo = MagicMock()
    odoo.search_read = AsyncMock(
        return_value=[
            {"quantity": 0.0, "reserved_quantity": 0.0, "location_id": [9, "WH/Stock/A-01"]},
            {"quantity": 12.0, "reserved_quantity": 0.0, "location_id": [11, "WH/Stock/B-02"]},
        ]
    )
    app.dependency_overrides[get_picking_service] = lambda: picking_service
    app.dependency_overrides[get_odoo_client] = lambda: odoo
    app.dependency_overrides[get_request_odoo_client] = lambda: odoo

    try:
        with TestClient(app, headers=BROWSER_GATE_HEADERS) as client:
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
    assert payload["status"] == "ok"
    assert "B-02" in payload["tts_text"]
    assert "leite" not in payload["tts_text"].lower()
    assert payload["recommendation"]["action"] == "trigger_replenishment"


