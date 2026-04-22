import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.main import app


LOG_PATHS = ("/api/integration/log", "/api/obsidian/log")


@pytest.mark.parametrize("path", LOG_PATHS)
def test_integration_log_requires_callback_secret(monkeypatch, path):
    """Log endpoints reject requests without X-N8N-Callback-Secret."""
    monkeypatch.setattr(settings, "n8n_callback_secret", "top-secret")

    with TestClient(app) as client:
        response = client.post(
            path,
            json={"message": "test", "category": "QA-ALARM"},
        )

    assert response.status_code == 403


@pytest.mark.parametrize("path", LOG_PATHS)
def test_integration_log_rejects_wrong_secret(monkeypatch, path):
    """Log endpoints reject requests with a wrong callback secret."""
    monkeypatch.setattr(settings, "n8n_callback_secret", "top-secret")

    with TestClient(app) as client:
        response = client.post(
            path,
            json={"message": "test", "category": "QA-ALARM"},
            headers={"X-N8N-Callback-Secret": "wrong-secret"},
        )

    assert response.status_code == 403


@pytest.mark.parametrize("path", LOG_PATHS)
def test_integration_log_accepts_correct_secret(monkeypatch, tmp_path, path):
    """Log endpoints write to the daily note with the correct callback secret."""
    monkeypatch.setattr(settings, "n8n_callback_secret", "top-secret")

    import app.services.integration_log as integration_log_mod

    monkeypatch.setattr(integration_log_mod, "DEFAULT_DAILY_NOTES_PATH", tmp_path)

    with TestClient(app) as client:
        response = client.post(
            path,
            json={"message": "test log entry", "category": "QA-ALARM"},
            headers={"X-N8N-Callback-Secret": "top-secret"},
        )

    assert response.status_code == 200
    assert response.json()["status"] == "success"
