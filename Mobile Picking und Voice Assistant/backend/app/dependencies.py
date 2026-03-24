"""Dependency Injection fuer FastAPI."""
from functools import lru_cache

from fastapi import Header, HTTPException

from app.services.mobile_workflow import MobileWorkflowService, PickerIdentity, WriteRequestContext
from app.services.n8n_webhook import N8NWebhookClient
from app.services.odoo_client import OdooClient
from app.services.picking_service import PickingService


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
