from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest

from app.models.auth import PickerSessionLoginRequest
from app.services.auth_sessions import (
    AuthenticationFailed,
    SessionService,
    parse_session_token,
)


class FakeOdoo:
    def __init__(self, *, instance="o19", uid=7, allowed=True):
        self.instance = instance
        self.uid = uid
        self.allowed = allowed
        self.calls = []
        self.session = None

    async def authenticate_credentials(self, login, password):
        self.calls.append(("authenticate_credentials", login, password))
        return self.uid if password == "correct" else None

    async def execute_kw(self, model, method, args, kwargs=None):
        self.calls.append((model, method, args))
        if method == "api_check_login":
            return {"allowed": True, "failure_count": 0, "locked_until": False}
        if method == "api_get_picker_principal":
            return {
                "allowed": self.allowed,
                "picker_user_id": self.uid,
                "picker_name": "Mina Muster",
                "roles": ["picker"],
            }
        if method == "api_record_login_result":
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
        raise AssertionError((model, method, args))


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
