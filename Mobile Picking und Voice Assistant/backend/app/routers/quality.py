"""
Quality-Alert-Endpoints.
Erstellt quality.alert.custom Records in Odoo 18 mit optionalem Foto-Attachment.
Loest anschliessend n8n-Workflow (fire-and-forget) aus.
"""
import base64
import hashlib
import logging
from typing import List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile

from app.dependencies import get_mobile_workflow_service, get_n8n_client, get_odoo_client, get_write_request_context
from app.services.mobile_workflow import (
    IdempotencyReservation,
    InvalidPickerIdentityError,
    MobileWorkflowService,
    WriteRequestContext,
)
from app.services.n8n_webhook import N8NWebhookClient
from app.services.odoo_client import OdooAPIError, OdooClient

logger = logging.getLogger(__name__)
router = APIRouter()


def _cached_detail(payload: dict | None):
    if isinstance(payload, dict) and "detail" in payload:
        return payload["detail"]
    return payload or "Anfrage konnte nicht verarbeitet werden."


def _return_or_raise_replay(reservation: IdempotencyReservation):
    if not reservation.should_replay:
        return None
    payload = reservation.response_payload or {}
    if reservation.status_code >= 400:
        raise HTTPException(status_code=reservation.status_code, detail=_cached_detail(payload))
    return payload


async def _finalize_error(
    workflow: MobileWorkflowService,
    reservation: IdempotencyReservation,
    status_code: int,
    detail,
) -> None:
    await workflow.finalize_idempotent_request(
        reservation,
        {"detail": detail},
        status_code,
    )


@router.post("/quality-alerts")
async def create_quality_alert(
    description: str = Form(...),
    picking_id: Optional[int] = Form(None),
    product_id: Optional[int] = Form(None),
    location_id: Optional[int] = Form(None),
    priority: str = Form("0"),
    photos: List[UploadFile] = File(default=[]),
    context: WriteRequestContext = Depends(get_write_request_context),
    odoo: OdooClient = Depends(get_odoo_client),
    n8n: N8NWebhookClient = Depends(get_n8n_client),
    workflow: MobileWorkflowService = Depends(get_mobile_workflow_service),
):
    """
    Quality Alert mit optionalen Fotos erstellen (beliebig viele).
    Alle Fotos werden gebuendelt an Odoo gesendet und dort als
    ir.attachment gespeichert.
    """
    photo_list = []
    photo_fingerprint = []
    for photo in photos:
        if not photo or not photo.filename:
            continue
        photo_bytes = await photo.read()
        if not photo_bytes:
            continue
        digest = hashlib.sha256(photo_bytes).hexdigest()
        photo_list.append(
            {
                "filename": photo.filename,
                "data_b64": base64.b64encode(photo_bytes).decode("utf-8"),
            }
        )
        photo_fingerprint.append(
            {
                "filename": photo.filename,
                "sha256": digest,
                "size": len(photo_bytes),
            }
        )

    fingerprint = workflow.build_request_fingerprint(
        {
            "description": description,
            "picking_id": picking_id,
            "product_id": product_id,
            "location_id": location_id,
            "priority": priority,
            "photos": photo_fingerprint,
        }
    )
    reservation = await workflow.begin_idempotent_request(
        "quality-alerts.create",
        context,
        fingerprint,
        picking_id,
    )
    replay = _return_or_raise_replay(reservation)
    if replay is not None:
        return replay

    if not context.identity.is_complete:
        detail = "X-Picker-User-Id und X-Device-Id sind fuer diese Aktion erforderlich."
        await _finalize_error(workflow, reservation, 400, detail)
        raise HTTPException(status_code=400, detail=detail)
    try:
        picker_identity = await workflow.resolve_identity(context.identity)
    except InvalidPickerIdentityError as exc:
        detail = "Unbekannter oder inaktiver Picker."
        await _finalize_error(workflow, reservation, 403, detail)
        raise HTTPException(status_code=403, detail=detail) from exc

    vals: dict = {"description": description, "priority": priority}
    if picking_id:
        vals["picking_id"] = picking_id
    if product_id:
        vals["product_id"] = product_id
    if location_id:
        vals["location_id"] = location_id
    if photo_list:
        vals["photos"] = photo_list
    if picker_identity and picker_identity.user_id:
        vals["user_id"] = picker_identity.user_id

    try:
        result = await odoo.execute_kw(
            "quality.alert.custom",
            "api_create_alert",
            [vals],
        )
    except OdooAPIError as exc:
        logger.error("Odoo Quality Alert Fehler: %s", exc.message)
        detail = f"Odoo-Fehler: {exc.message}"
        await _finalize_error(workflow, reservation, 502, detail)
        raise HTTPException(status_code=502, detail=detail) from exc
    except Exception:
        await workflow.abort_idempotent_request(reservation)
        raise

    alert_id = result.get("alert_id") if isinstance(result, dict) else None
    name = result.get("name", "") if isinstance(result, dict) else ""

    # Set AI evaluation to pending before firing the async n8n event
    if alert_id:
        try:
            await odoo.write("quality.alert.custom", [alert_id], {"ai_evaluation_status": "pending"})
        except Exception:
            logger.warning("Could not set ai_evaluation_status=pending for alert %s", alert_id)

    reported_by = "mobile-picking-assistant"
    reported_by_user_id = False
    reported_by_device_id = ""
    if picker_identity and picker_identity.user_id:
        reported_by = picker_identity.picker_name or reported_by
        reported_by_user_id = picker_identity.user_id
        reported_by_device_id = picker_identity.device_id or ""

    await n8n.fire_event(
        "quality-alert-created",
        {
            "alert_id": alert_id,
            "name": name,
            "picking_id": picking_id,
            "priority": priority,
            "photo_count": len(photo_list),
            "reported_by": reported_by,
            "reported_by_user_id": reported_by_user_id,
            "reported_by_device_id": reported_by_device_id,
            "description": description,
            "product_id": product_id,
            "location_id": location_id,
        },
        picker={
            "user_id": reported_by_user_id or None,
            "name": reported_by,
        },
        device_id=reported_by_device_id or None,
        picking_context={
            "picking_id": picking_id,
            "move_line_id": None,
            "product_id": product_id,
            "location_id": location_id,
            "priority": priority,
            "origin": None,
        },
    )

    response = {"alert_id": alert_id, "name": name, "photo_count": len(photo_list), "ai_evaluation_status": "pending"}
    await workflow.finalize_idempotent_request(reservation, response, 200)
    return response
