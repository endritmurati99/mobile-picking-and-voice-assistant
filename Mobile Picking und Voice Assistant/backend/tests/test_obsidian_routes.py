from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from app.config import settings
from app.main import app


def test_obsidian_log_requires_callback_secret(monkeypatch):
    """POST /obsidian/log without X-N8N-Callback-Secret header returns 403."""
    monkeypatch.setattr(settings, "n8n_callback_secret", "top-secret")

    with TestClient(app) as client:
        response = client.post(
            "/api/obsidian/log",
            json={"message": "test", "category": "QA-ALARM"},
        )

    assert response.status_code == 403


def test_obsidian_log_rejects_wrong_secret(monkeypatch):
    """POST /obsidian/log with wrong secret returns 403."""
    monkeypatch.setattr(settings, "n8n_callback_secret", "top-secret")

    with TestClient(app) as client:
        response = client.post(
            "/api/obsidian/log",
            json={"message": "test", "category": "QA-ALARM"},
            headers={"X-N8N-Callback-Secret": "wrong-secret"},
        )

    assert response.status_code == 403


def test_obsidian_log_accepts_correct_secret(monkeypatch, tmp_path):
    """POST /obsidian/log with correct secret succeeds."""
    monkeypatch.setattr(settings, "n8n_callback_secret", "top-secret")
    # Redirect Obsidian path to a temp dir so the test does not write to the real vault
    import app.routers.obsidian as obsidian_mod
    monkeypatch.setattr(obsidian_mod, "DAILY_NOTES_PATH", str(tmp_path))

    with TestClient(app) as client:
        response = client.post(
            "/api/obsidian/log",
            json={"message": "test log entry", "category": "QA-ALARM"},
            headers={"X-N8N-Callback-Secret": "top-secret"},
        )

    assert response.status_code == 200
    assert response.json()["status"] == "success"
