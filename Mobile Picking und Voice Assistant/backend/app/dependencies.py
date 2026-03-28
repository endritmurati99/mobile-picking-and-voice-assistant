"""Dependency Injection fuer FastAPI."""
from functools import lru_cache
import secrets

from fastapi import Depends, Header, HTTPException

from app.services.mobile_workflow import (
    InvalidPickerIdentityError,
    MobileWorkflowService,
    PickerIdentity,
    WriteRequestContext,
)
from app.services.n8n_webhook import N8NWebhookClient
from app.services.odoo_client import OdooClient
from app.services.picking_service import PickingService
from app.config import settings


@lru_cache()
def get_odoo_client() -> OdooClient:
    return OdooClient()


@lru_cache()
def get_n8n_client() -> N8NWebhookClient:
    return N8NWebhookClient()


def get_picking_service() -> PickingService:
    return PickingService(get_odoo_client(), get_n8n_client())


def get_mobile_workflow_service() -> MobileWorkflowService:
    return MobileWorkflowService(get_odoo_client())


def _parse_picker_user_id(picker_user_id: str | None) -> int:
    if picker_user_id is None:
        raise HTTPException(status_code=400, detail="X-Picker-User-Id ist erforderlich.")
    try:
        return int(picker_user_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="X-Picker-User-Id muss numerisch sein.") from exc


async def get_required_picker_identity(
    picker_user_id: str | None = Header(default=None, alias="X-Picker-User-Id"),
    workflow: MobileWorkflowService = Depends(get_mobile_workflow_service),
) -> PickerIdentity:
    user_id = _parse_picker_user_id(picker_user_id)
    try:
        return await workflow.resolve_identity(PickerIdentity(user_id=user_id))
    except InvalidPickerIdentityError as exc:
        raise HTTPException(status_code=403, detail="Unbekannter oder inaktiver Picker.") from exc


def get_write_request_context(
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    picker_user_id: str | None = Header(default=None, alias="X-Picker-User-Id"),
    device_id: str | None = Header(default=None, alias="X-Device-Id"),
) -> WriteRequestContext:
    user_id: int | None = None
    if picker_user_id is not None:
        try:
            user_id = int(picker_user_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="X-Picker-User-Id muss numerisch sein.") from exc

    return WriteRequestContext(
        idempotency_key=idempotency_key,
        identity=PickerIdentity(user_id=user_id, device_id=device_id),
    )


def require_n8n_callback_secret(
    provided_secret: str | None = Header(default=None, alias="X-N8N-Callback-Secret"),
) -> None:
    expected_secret = settings.n8n_callback_secret
    if not expected_secret:
        raise HTTPException(
            status_code=503,
            detail="N8N callback secret ist nicht konfiguriert.",
        )
    if not provided_secret or not secrets.compare_digest(provided_secret, expected_secret):
        raise HTTPException(status_code=403, detail="Ungueltiges n8n callback secret.")
