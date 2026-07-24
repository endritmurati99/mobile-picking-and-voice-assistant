import hashlib
from datetime import datetime, timezone

from fastapi.testclient import TestClient

from app.dependencies import get_current_principal, get_session_service
from app.main import app
from app.models.auth import Principal
from app.services.auth_sessions import CreatedSession, CsrfFailed


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


ALLOWED_ORIGIN = "https://picking.test"


def _principal() -> Principal:
    return Principal(
        picker_user_id=7,
        picker_name="Mina Muster",
        device_id="123e4567-e89b-42d3-a456-426614174000",
        odoo_instance="o19",
        roles=frozenset({"picker"}),
        session_id="4ddb2442-e58a-47fe-9a6f-1ec1d779ef88",
        expires_at=datetime(2026, 7, 23, 20, 0, tzinfo=timezone.utc),
    )


class CsrfFakeSessions:
    """Mirrors SessionService's origin/CSRF gating so router tests exercise
    the real rejection contract (403 on missing/mismatched CSRF or Origin)
    without re-deriving SessionService internals."""

    def __init__(self, *, valid_csrf_token: str):
        self._valid_hash = hashlib.sha256(valid_csrf_token.encode("utf-8")).hexdigest()

    def _require_origin(self, origin):
        if origin != ALLOWED_ORIGIN:
            raise CsrfFailed("Origin ist nicht erlaubt.")

    async def validate_csrf(self, principal, token, origin):
        self._require_origin(origin)
        if not token:
            raise CsrfFailed("CSRF-Token fehlt.")
        if hashlib.sha256(token.encode("utf-8")).hexdigest() != self._valid_hash:
            raise CsrfFailed("CSRF-Token ist ungueltig.")

    async def rotate_csrf(self, principal, origin):
        self._require_origin(origin)
        return "n" * 43

    async def revoke(self, principal):
        pass


def _override_auth(sessions: CsrfFakeSessions) -> None:
    app.dependency_overrides[get_current_principal] = _principal
    app.dependency_overrides[get_session_service] = lambda: sessions


def test_logout_without_csrf_token_is_rejected():
    _override_auth(CsrfFakeSessions(valid_csrf_token="v" * 43))
    try:
        client = TestClient(app, base_url="https://picking.test")
        response = client.post(
            "/api/auth/logout",
            headers={"Origin": ALLOWED_ORIGIN},
        )
        assert response.status_code == 403
    finally:
        app.dependency_overrides.clear()


def test_logout_with_wrong_csrf_token_is_rejected():
    _override_auth(CsrfFakeSessions(valid_csrf_token="v" * 43))
    try:
        client = TestClient(app, base_url="https://picking.test")
        response = client.post(
            "/api/auth/logout",
            headers={"Origin": ALLOWED_ORIGIN, "X-CSRF-Token": "w" * 43},
        )
        assert response.status_code == 403
    finally:
        app.dependency_overrides.clear()


def test_logout_with_mismatched_origin_is_rejected():
    _override_auth(CsrfFakeSessions(valid_csrf_token="v" * 43))
    try:
        client = TestClient(app, base_url="https://picking.test")
        response = client.post(
            "/api/auth/logout",
            headers={"Origin": "https://evil.test", "X-CSRF-Token": "v" * 43},
        )
        assert response.status_code == 403
    finally:
        app.dependency_overrides.clear()


def test_logout_with_valid_csrf_and_origin_succeeds():
    _override_auth(CsrfFakeSessions(valid_csrf_token="v" * 43))
    try:
        client = TestClient(app, base_url="https://picking.test")
        response = client.post(
            "/api/auth/logout",
            headers={"Origin": ALLOWED_ORIGIN, "X-CSRF-Token": "v" * 43},
        )
        assert response.status_code == 204
    finally:
        app.dependency_overrides.clear()


def test_csrf_rotation_endpoint_does_not_require_csrf_token_header():
    _override_auth(CsrfFakeSessions(valid_csrf_token="v" * 43))
    try:
        client = TestClient(app, base_url="https://picking.test")
        response = client.post(
            "/api/auth/csrf",
            headers={"Origin": ALLOWED_ORIGIN},
        )
        assert response.status_code == 200
        assert response.json()["csrf_token"] == "n" * 43
    finally:
        app.dependency_overrides.clear()
