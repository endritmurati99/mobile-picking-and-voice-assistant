from __future__ import annotations

import hashlib
import hmac
import ipaddress
import re
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable
from uuid import uuid4

from fastapi import Request

from app.models.auth import (
    PickerSessionLoginRequest,
    Principal,
    SessionTokenHint,
)

_TOKEN_SECRET = re.compile(r"^[A-Za-z0-9_-]{43}$")
_INSTANCE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")


class AuthenticationFailed(Exception):
    pass


class CsrfFailed(Exception):
    pass


@dataclass(frozen=True)
class CreatedSession:
    cookie_token: str
    csrf_token: str
    principal: Principal


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def to_odoo_datetime(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Odoo datetime input must be timezone-aware")
    return value.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def from_odoo_datetime(value: str) -> datetime:
    parsed = datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
    return parsed.replace(tzinfo=timezone.utc)


def parse_session_token(token: str) -> SessionTokenHint:
    parts = token.split(".")
    if (
        len(parts) != 3
        or parts[0] != "v1"
        or not _INSTANCE.fullmatch(parts[1])
        or not _TOKEN_SECRET.fullmatch(parts[2])
    ):
        raise AuthenticationFailed("Ungueltige oder abgelaufene Sitzung.")
    return SessionTokenHint(
        version="v1",
        odoo_instance=parts[1],
        token_hash=_sha256(token),
    )


def _canonical_peer(host: str) -> str:
    # ASGI test harnesses (e.g. Starlette's TestClient) supply a synthetic,
    # non-IP host ("testclient") instead of a real peer address. Real
    # deployments always sit behind Caddy/uvicorn with a genuine IP here, so
    # this only ever falls back to the raw string in tests.
    try:
        return str(ipaddress.ip_address(host))
    except ValueError:
        return host


def request_source_ip(request: Request, trusted_peers: set[str]) -> str:
    if request.client is None:
        raise AuthenticationFailed("Anmeldung fehlgeschlagen.")
    peer = _canonical_peer(request.client.host)
    if peer not in trusted_peers:
        return peer
    forwarded = request.headers.get("X-Forwarded-For", "")
    first = forwarded.split(",", 1)[0].strip()
    return _canonical_peer(first) if first else peer


def source_ip_key(source_ip: str, secret: bytes) -> str:
    packed = ipaddress.ip_address(source_ip).packed
    return hmac.new(secret, packed, hashlib.sha256).hexdigest()


class SessionService:
    def __init__(
        self,
        *,
        client_factory,
        instance_names: set[str],
        throttle_secret: bytes,
        allowed_origins: set[str],
        now: Callable[[], datetime] = _utcnow,
        session_seconds: int = 28800,
        revalidate_seconds: int = 300,
    ):
        self._client_factory = client_factory
        self._instance_names = instance_names
        self._throttle_secret = throttle_secret
        self._allowed_origins = allowed_origins
        self._now = now
        self._session_seconds = session_seconds
        self._revalidate_seconds = revalidate_seconds

    def _require_origin(self, origin: str | None) -> None:
        if origin not in self._allowed_origins:
            raise CsrfFailed("Origin ist nicht erlaubt.")

    async def create_session(
        self,
        body: PickerSessionLoginRequest,
        *,
        source_ip: str,
        origin: str | None,
    ) -> CreatedSession:
        self._require_origin(origin)
        if body.odoo_instance not in self._instance_names:
            raise AuthenticationFailed("Anmeldung fehlgeschlagen.")
        odoo = self._client_factory(body.odoo_instance)
        login_key = body.login.casefold()
        ip_key = source_ip_key(source_ip, self._throttle_secret)
        throttle = await odoo.execute_kw(
            "picking.assistant.auth.throttle",
            "api_check_login",
            [login_key, ip_key],
        )
        if not throttle.get("allowed"):
            raise AuthenticationFailed("Anmeldung fehlgeschlagen.")

        uid = await odoo.authenticate_credentials(body.login, body.password)
        identity = (
            await odoo.execute_kw(
                "res.users", "api_get_picker_principal", [uid]
            )
            if uid
            else {"allowed": False}
        )
        if not uid or not identity.get("allowed"):
            await odoo.execute_kw(
                "picking.assistant.auth.throttle",
                "api_record_login_result",
                [login_key, ip_key, False],
            )
            raise AuthenticationFailed("Anmeldung fehlgeschlagen.")

        await odoo.execute_kw(
            "picking.assistant.auth.throttle",
            "api_record_login_result",
            [login_key, ip_key, True],
        )
        session_id = str(uuid4())
        cookie_token = f"v1.{body.odoo_instance}.{secrets.token_urlsafe(32)}"
        csrf_token = secrets.token_urlsafe(32)
        expires_at = self._now() + timedelta(seconds=self._session_seconds)
        stored = await odoo.execute_kw(
            "picking.assistant.session",
            "api_create_session",
            [
                session_id,
                _sha256(cookie_token),
                _sha256(csrf_token),
                uid,
                str(body.device_id),
                identity["roles"],
                to_odoo_datetime(expires_at),
            ],
        )
        principal = self._principal(body.odoo_instance, stored)
        return CreatedSession(
            cookie_token=cookie_token,
            csrf_token=csrf_token,
            principal=principal,
        )

    async def resolve_principal(
        self,
        token: str,
        *,
        force_revalidate: bool = False,
    ) -> Principal:
        hint = parse_session_token(token)
        if hint.odoo_instance not in self._instance_names:
            raise AuthenticationFailed("Ungueltige oder abgelaufene Sitzung.")
        odoo = self._client_factory(hint.odoo_instance)
        stored = await odoo.execute_kw(
            "picking.assistant.session",
            "api_get_session",
            [hint.token_hash, True],
        )
        if not stored:
            raise AuthenticationFailed("Ungueltige oder abgelaufene Sitzung.")
        principal = self._principal(hint.odoo_instance, stored)
        checked = from_odoo_datetime(stored["roles_checked_at"])
        needs_check = force_revalidate or (
            self._now() - checked
        ).total_seconds() >= self._revalidate_seconds
        if needs_check:
            identity = await odoo.execute_kw(
                "res.users",
                "api_get_picker_principal",
                [principal.picker_user_id],
            )
            if not identity.get("allowed"):
                await odoo.execute_kw(
                    "picking.assistant.session",
                    "api_revoke_user_sessions",
                    [principal.picker_user_id],
                )
                raise AuthenticationFailed("Ungueltige oder abgelaufene Sitzung.")
            stored = await odoo.execute_kw(
                "picking.assistant.session",
                "api_mark_roles_checked",
                [principal.session_id, identity["roles"]],
            )
            principal = self._principal(hint.odoo_instance, stored)
        return principal

    async def rotate_csrf(self, principal: Principal, origin: str | None) -> str:
        self._require_origin(origin)
        token = secrets.token_urlsafe(32)
        odoo = self._client_factory(principal.odoo_instance)
        rotated = await odoo.execute_kw(
            "picking.assistant.session",
            "api_rotate_csrf",
            [principal.session_id, _sha256(token)],
        )
        if not rotated:
            raise AuthenticationFailed("Ungueltige oder abgelaufene Sitzung.")
        return token

    async def validate_csrf(
        self,
        principal: Principal,
        token: str | None,
        origin: str | None,
    ) -> None:
        self._require_origin(origin)
        if not token:
            raise CsrfFailed("CSRF-Token fehlt.")
        odoo = self._client_factory(principal.odoo_instance)
        valid = await odoo.execute_kw(
            "picking.assistant.session",
            "api_validate_csrf",
            [principal.session_id, _sha256(token)],
        )
        if not valid:
            raise CsrfFailed("CSRF-Token ist ungueltig.")

    async def revoke(self, principal: Principal) -> None:
        await self._client_factory(principal.odoo_instance).execute_kw(
            "picking.assistant.session",
            "api_revoke_session",
            [principal.session_id],
        )

    @staticmethod
    def _principal(instance: str, stored: dict) -> Principal:
        return Principal(
            picker_user_id=int(stored["picker_user_id"]),
            picker_name=str(stored["picker_name"]),
            device_id=str(stored["device_id"]),
            odoo_instance=instance,
            roles=frozenset(stored["roles"]),
            session_id=str(stored["session_id"]),
            expires_at=from_odoo_datetime(stored["expires_at"]),
        )
