import hashlib
import json
from dataclasses import dataclass, field

from app.config import settings
from app.services.odoo_client import OdooClient


@dataclass(frozen=True)
class PickerIdentity:
    user_id: int | None = None
    device_id: str | None = None
    picker_name: str | None = None

    @property
    def is_complete(self) -> bool:
        return self.user_id is not None and bool(self.device_id)


@dataclass(frozen=True)
class WriteRequestContext:
    idempotency_key: str | None = None
    identity: PickerIdentity = field(default_factory=PickerIdentity)


@dataclass(frozen=True)
class IdempotencyReservation:
    status: str
    entry_id: int | None = None
    response_payload: dict | None = None
    status_code: int = 200

    @property
    def should_replay(self) -> bool:
        return self.status in {"replay", "pending", "conflict"}

    @property
    def is_active(self) -> bool:
        return self.entry_id is not None and self.status == "reserved"


class ClaimConflictError(Exception):
    def __init__(self, detail: dict):
        self.detail = detail
        message = detail.get("claimed_by_name") or detail.get("message") or "Picking ist bereits reserviert."
        super().__init__(message)


class InvalidPickerIdentityError(Exception):
    def __init__(self, user_id: int | None = None):
        self.user_id = user_id
        super().__init__("Unbekannter oder inaktiver Picker.")


class MobileWorkflowService:
    def __init__(self, odoo: OdooClient):
        self._odoo = odoo

    @staticmethod
    def build_request_fingerprint(payload: dict) -> str:
        normalized = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(normalized.encode("utf-8")).hexdigest()

    async def list_pickers(self) -> list[dict]:
        users = await self._odoo.search_read(
            "res.users",
            [("active", "=", True), ("share", "=", False)],
            ["name"],
            limit=100,
        )
        return sorted(
            [{"id": user["id"], "name": user.get("name", "")} for user in users],
            key=lambda item: item["name"].lower(),
        )

    async def resolve_identity(self, identity: PickerIdentity) -> PickerIdentity:
        if not identity.user_id or identity.picker_name:
            return identity

        users = await self._odoo.search_read(
            "res.users",
            [("id", "=", identity.user_id), ("active", "=", True), ("share", "=", False)],
            ["name"],
            limit=1,
        )
        if not users:
            raise InvalidPickerIdentityError(identity.user_id)
        picker_name = users[0].get("name", "")
        return PickerIdentity(
            user_id=identity.user_id,
            device_id=identity.device_id,
            picker_name=picker_name,
        )

    async def claim_picking(self, picking_id: int, identity: PickerIdentity) -> dict:
        result = await self._odoo.execute_kw(
            "stock.picking",
            "api_claim_mobile",
            [picking_id, identity.user_id, identity.device_id, settings.mobile_claim_ttl_seconds],
        )
        self._raise_on_claim_conflict(result)
        return result

    async def heartbeat_picking(self, picking_id: int, identity: PickerIdentity) -> dict:
        result = await self._odoo.execute_kw(
            "stock.picking",
            "api_heartbeat_mobile",
            [picking_id, identity.user_id, identity.device_id, settings.mobile_claim_ttl_seconds],
        )
        self._raise_on_claim_conflict(result)
        return result

    async def release_picking(self, picking_id: int, identity: PickerIdentity) -> dict:
        result = await self._odoo.execute_kw(
            "stock.picking",
            "api_release_mobile",
            [picking_id, identity.user_id, identity.device_id],
        )
        self._raise_on_claim_conflict(result)
        return result

    async def begin_idempotent_request(
        self,
        endpoint: str,
        context: WriteRequestContext,
        fingerprint: str,
        picking_id: int | None = None,
    ) -> IdempotencyReservation:
        if not context.idempotency_key:
            return IdempotencyReservation(status="disabled")

        result = await self._odoo.execute_kw(
            "picking.assistant.idempotency",
            "api_reserve_request",
            [
                endpoint,
                context.idempotency_key,
                fingerprint,
                picking_id or False,
                context.identity.user_id or False,
                context.identity.device_id or False,
                settings.mobile_idempotency_ttl_seconds,
            ],
        )
        return IdempotencyReservation(
            status=result.get("status", "disabled"),
            entry_id=result.get("entry_id"),
            response_payload=result.get("response_payload"),
            status_code=int(result.get("status_code", 200)),
        )

    async def finalize_idempotent_request(
        self,
        reservation: IdempotencyReservation,
        response_payload: dict,
        status_code: int = 200,
    ) -> None:
        if not reservation.is_active:
            return
        await self._odoo.execute_kw(
            "picking.assistant.idempotency",
            "api_finalize_request",
            [reservation.entry_id, response_payload, status_code],
        )

    async def abort_idempotent_request(self, reservation: IdempotencyReservation) -> None:
        if not reservation.is_active:
            return
        await self._odoo.execute_kw(
            "picking.assistant.idempotency",
            "api_abort_request",
            [reservation.entry_id],
        )

    @staticmethod
    def _raise_on_claim_conflict(result: dict | None) -> None:
        if result and result.get("conflict"):
            raise ClaimConflictError(result)
