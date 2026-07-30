import hashlib
from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest
from starlette.datastructures import Headers
from starlette.requests import Request

from app.models.auth import PickerSessionLoginRequest, Principal
from app.services.auth_sessions import (
    AuthenticationFailed,
    CsrfFailed,
    SessionService,
    parse_session_token,
    request_source_ip,
)


def _request(*, peer: str, headers: dict[str, str] | None = None) -> Request:
    scope = {
        "type": "http",
        "client": (peer, 12345),
        "headers": Headers(headers or {}).raw,
    }
    return Request(scope)


class FakeOdoo:
    def __init__(self, *, instance="o19", uid=7, allowed=True, csrf_hash=None):
        self.instance = instance
        self.uid = uid
        self.allowed = allowed
        self.calls = []
        self.session = None
        self.csrf_hash = csrf_hash
        self.revoked_session_ids = []

    async def authenticate_credentials(self, login, password):
        self.calls.append(("authenticate_credentials", login, password))
        return self.uid if password == "correct" else None

    async def execute_kw(self, model, method, args, kwargs=None):
        self.calls.append((model, method, args))
        if method == "api_check_login":
            return {"allowed": True, "failure_count": 0, "locked_until": False}
        if method == "api_begin_login_attempt":
            return {"allowed": True, "attempt_token": "test-attempt-token"}
        if method == "api_get_picker_principal":
            return {
                "allowed": self.allowed,
                "picker_user_id": self.uid,
                "picker_name": "Mina Muster",
                "roles": ["picker"],
            }
        if method in ("api_record_login_result", "api_finish_login_attempt"):
            return {"allowed": True, "failure_count": 0, "locked_until": False}
        if method == "api_create_session":
            self.session = {
                "session_id": args[0],
                "picker_user_id": self.uid,
                "picker_name": "Mina Muster",
                "device_id": args[4],
                "roles": ["picker"],
                "expires_at": args[6],
                "revoked_at": False,
                "roles_checked_at": "2026-07-23 12:00:00",
            }
            return self.session
        if method == "api_get_session":
            return self.session
        if method == "api_validate_csrf":
            _session_id, token_hash = args
            return token_hash == self.csrf_hash
        if method == "api_rotate_csrf":
            session_id, token_hash = args
            self.csrf_hash = token_hash
            return {"session_id": session_id, "csrf_token_hash": token_hash}
        if method == "api_revoke_session":
            self.revoked_session_ids.append(args[0])
            return None
        raise AssertionError((model, method, args))


def _principal(*, session_id: str = "4ddb2442-e58a-47fe-9a6f-1ec1d779ef88") -> Principal:
    return Principal(
        picker_user_id=7,
        picker_name="Mina Muster",
        device_id="123e4567-e89b-42d3-a456-426614174000",
        odoo_instance="o19",
        roles=frozenset({"picker"}),
        session_id=session_id,
        expires_at=datetime(2026, 7, 23, 20, 0, tzinfo=timezone.utc),
    )


@pytest.mark.asyncio
async def test_create_session_stores_only_hashes_and_binds_instance():
    odoo = FakeOdoo()
    service = SessionService(
        client_factory=lambda name: odoo if name == "o19" else None,
        instance_names={"o19"},
        throttle_secret=b"t" * 32,
        allowed_origins={"https://picking.test"},
        now=lambda: datetime(2026, 7, 23, 12, 0, tzinfo=timezone.utc),
    )
    created = await service.create_session(
        PickerSessionLoginRequest(
            login="mina",
            password="correct",
            device_id="123e4567-e89b-42d3-a456-426614174000",
            odoo_instance="o19",
        ),
        source_ip="192.0.2.10",
        origin="https://picking.test",
    )
    hint = parse_session_token(created.cookie_token)
    assert hint.odoo_instance == "o19"
    assert created.cookie_token.startswith("v1.o19.")
    create_call = next(call for call in odoo.calls if call[1] == "api_create_session")
    assert created.cookie_token not in create_call[2]
    assert created.csrf_token not in create_call[2]
    assert create_call[2][6] == "2026-07-23 20:00:00"
    resolved = await service.resolve_principal(created.cookie_token)
    assert resolved.expires_at.tzinfo is timezone.utc


@pytest.mark.asyncio
async def test_bad_password_and_disallowed_user_have_same_public_error():
    for uid, allowed, password in ((None, True, "bad"), (7, False, "correct")):
        service = SessionService(
            client_factory=lambda _name, uid=uid, allowed=allowed: FakeOdoo(
                uid=uid, allowed=allowed
            ),
            instance_names={"o19"},
            throttle_secret=b"t" * 32,
            allowed_origins={"https://picking.test"},
        )
        with pytest.raises(AuthenticationFailed, match="Anmeldung fehlgeschlagen"):
            await service.create_session(
                PickerSessionLoginRequest(
                    login="mina",
                    password=password,
                    device_id="123e4567-e89b-42d3-a456-426614174000",
                    odoo_instance="o19",
                ),
                source_ip="192.0.2.10",
                origin="https://picking.test",
            )


@pytest.mark.asyncio
async def test_manipulated_instance_hint_never_falls_back():
    clients = {"o19": FakeOdoo(instance="o19")}
    service = SessionService(
        client_factory=lambda name: clients[name],
        instance_names={"o19"},
        throttle_secret=b"t" * 32,
        allowed_origins={"https://picking.test"},
    )
    with pytest.raises(AuthenticationFailed):
        await service.resolve_principal("v1.local." + ("a" * 43))
    assert clients["o19"].calls == []


def test_request_source_ip_trusts_right_most_xff_segment_from_trusted_peer():
    # Caddy's bare `reverse_proxy backend:8000` (no trusted_proxies /
    # header-overwrite config) only APPENDS the real client IP to the right
    # of any client-supplied X-Forwarded-For value -- it never strips
    # attacker-controlled entries. An attacker who directly reaches Caddy
    # could inject "X-Forwarded-For: 1.2.3.4" to make Caddy forward
    # "1.2.3.4, <real-ip>". The left-most entry ("1.2.3.4") must NOT be
    # trusted -- only the right-most, Caddy-appended entry is authoritative.
    request = _request(
        peer="127.0.0.1",
        headers={"X-Forwarded-For": "1.2.3.4, 203.0.113.9"},
    )
    source_ip = request_source_ip(request, {"127.0.0.1"})
    assert source_ip == "203.0.113.9"
    assert source_ip != "1.2.3.4"


def test_request_source_ip_ignores_xff_from_untrusted_direct_peer():
    # If the direct TCP peer is not the configured Caddy peer, any
    # X-Forwarded-For header is attacker-controlled noise and must be
    # ignored entirely in favor of the real socket peer.
    request = _request(
        peer="198.51.100.5",
        headers={"X-Forwarded-For": "1.2.3.4, 203.0.113.9"},
    )
    source_ip = request_source_ip(request, {"127.0.0.1"})
    assert source_ip == "198.51.100.5"


def _service(odoo: FakeOdoo) -> SessionService:
    return SessionService(
        client_factory=lambda _name: odoo,
        instance_names={"o19"},
        throttle_secret=b"t" * 32,
        allowed_origins={"https://picking.test"},
    )


def _login_body(**overrides) -> PickerSessionLoginRequest:
    values = {
        "login": "mina",
        "password": "wrong",
        "device_id": "123e4567-e89b-42d3-a456-426614174000",
        "odoo_instance": "o19",
    }
    values.update(overrides)
    return PickerSessionLoginRequest(**values)


@pytest.mark.asyncio
async def test_validate_csrf_accepts_matching_token_and_sends_only_hash():
    token = "s" * 43
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    odoo = FakeOdoo(csrf_hash=token_hash)
    service = _service(odoo)
    await service.validate_csrf(_principal(), token, "https://picking.test")
    validate_call = next(c for c in odoo.calls if c[1] == "api_validate_csrf")
    assert validate_call[2][1] == token_hash
    assert token not in validate_call[2]


@pytest.mark.asyncio
async def test_validate_csrf_rejects_mismatched_token():
    odoo = FakeOdoo(csrf_hash=hashlib.sha256(b"correct-token").hexdigest())
    service = _service(odoo)
    with pytest.raises(CsrfFailed):
        await service.validate_csrf(_principal(), "wrong-token", "https://picking.test")


@pytest.mark.asyncio
async def test_validate_csrf_rejects_missing_token():
    odoo = FakeOdoo(csrf_hash=hashlib.sha256(b"correct-token").hexdigest())
    service = _service(odoo)
    with pytest.raises(CsrfFailed):
        await service.validate_csrf(_principal(), None, "https://picking.test")


@pytest.mark.asyncio
async def test_rotate_csrf_returns_new_token_and_sends_only_hash():
    odoo = FakeOdoo()
    service = _service(odoo)
    principal = _principal()
    new_token = await service.rotate_csrf(principal, "https://picking.test")
    rotate_call = next(c for c in odoo.calls if c[1] == "api_rotate_csrf")
    assert rotate_call[2][0] == principal.session_id
    assert rotate_call[2][1] == hashlib.sha256(new_token.encode("utf-8")).hexdigest()
    assert new_token not in rotate_call[2]
    # The rotated token must subsequently validate via its hash only.
    await service.validate_csrf(principal, new_token, "https://picking.test")


@pytest.mark.asyncio
async def test_revoke_sends_only_session_id_to_odoo():
    odoo = FakeOdoo()
    service = _service(odoo)
    principal = _principal()
    await service.revoke(principal)
    assert odoo.revoked_session_ids == [principal.session_id]
    revoke_call = next(c for c in odoo.calls if c[1] == "api_revoke_session")
    assert revoke_call[2] == [principal.session_id]


@pytest.mark.asyncio
async def test_login_reserves_before_authenticating():
    """The expensive authentication must never run before the attempt is
    booked. Regression cover for finding #10."""
    calls: list[str] = []

    class RecordingOdoo(FakeOdoo):
        async def execute_kw(self, model, method, args, kwargs=None):
            if method in {"api_begin_login_attempt", "api_finish_login_attempt"}:
                calls.append(method)
            return await super().execute_kw(model, method, args, kwargs)

        async def authenticate_credentials(self, login, password):
            calls.append("authenticate")
            return 0

    odoo = RecordingOdoo()
    service = _service(odoo)
    with pytest.raises(AuthenticationFailed):
        await service.create_session(
            _login_body(), source_ip="10.0.0.1", origin="https://picking.test"
        )

    assert calls == ["api_begin_login_attempt", "authenticate", "api_finish_login_attempt"]
    assert "api_check_login" not in calls
    assert "api_record_login_result" not in calls

    # Recording method names alone would not notice a dropped argument:
    # the `attempt_token` `api_begin_login_attempt` returned must be the
    # exact one `api_finish_login_attempt` forwards, or the backend could
    # silently stop proving it is finishing its own reservation.
    finish_call = next(c for c in odoo.calls if c[1] == "api_finish_login_attempt")
    assert finish_call[2][2] == "test-attempt-token"


@pytest.mark.asyncio
async def test_login_releases_the_reservation_when_authentication_raises():
    """A leaked reservation that never expires is a protection that becomes
    an outage: the reservation must be released on EVERY exit path,
    including an unexpected exception from authentication itself, not only
    the "credentials were wrong" branch."""
    calls: list[str] = []

    class ExplodingOdoo(FakeOdoo):
        async def execute_kw(self, model, method, args, kwargs=None):
            if method in {"api_begin_login_attempt", "api_finish_login_attempt"}:
                calls.append(method)
            return await super().execute_kw(model, method, args, kwargs)

        async def authenticate_credentials(self, login, password):
            raise RuntimeError("Odoo transport exploded")

    service = _service(ExplodingOdoo())
    with pytest.raises(RuntimeError):
        await service.create_session(
            _login_body(), source_ip="10.0.0.1", origin="https://picking.test"
        )

    assert calls == ["api_begin_login_attempt", "api_finish_login_attempt"]
