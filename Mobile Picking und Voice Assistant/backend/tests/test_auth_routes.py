from datetime import datetime, timezone

from fastapi.testclient import TestClient

from app.dependencies import get_session_service
from app.main import app
from app.models.auth import Principal
from app.services.auth_sessions import CreatedSession


class StubSessions:
    async def create_session(self, body, source_ip, origin):
        return CreatedSession(
            cookie_token="v1.o19." + ("a" * 43),
            csrf_token="b" * 43,
            principal=Principal(
                picker_user_id=7,
                picker_name="Mina Muster",
                device_id=str(body.device_id),
                odoo_instance="o19",
                roles=frozenset({"picker"}),
                session_id="4ddb2442-e58a-47fe-9a6f-1ec1d779ef88",
                expires_at=datetime(2026, 7, 23, 20, 0, tzinfo=timezone.utc),
            ),
        )


def test_login_sets_exact_cookie_contract():
    app.dependency_overrides[get_session_service] = lambda: StubSessions()
    try:
        client = TestClient(app, base_url="https://picking.test")
        response = client.post(
            "/api/auth/picker-session",
            headers={"Origin": "https://picking.test"},
            json={
                "login": "mina",
                "password": "correct",
                "device_id": "123e4567-e89b-42d3-a456-426614174000",
                "odoo_instance": "o19",
            },
        )
        assert response.status_code == 200
        cookie = response.headers["set-cookie"]
        assert "pwr_session=" in cookie
        assert "HttpOnly" in cookie
        assert "Secure" in cookie
        assert "SameSite=strict" in cookie
        assert "Path=/api" in cookie
        assert "Max-Age=28800" in cookie
    finally:
        app.dependency_overrides.clear()
