"""Picking-Endpoints."""
import base64
import logging

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel

from app.config import settings
from app.dependencies import (
    get_mobile_workflow_service,
    get_odoo_client,
    get_picking_service,
    get_required_picker_identity,
    get_write_request_context,
)
from app.services.mobile_workflow import (
    ClaimConflictError,
    IdempotencyReservation,
    InvalidPickerIdentityError,
    MobileWorkflowService,
    PickerIdentity,
    WriteRequestContext,
)
from app.services.odoo_client import OdooClient

logger = logging.getLogger(__name__)
router = APIRouter()


class ConfirmLineRequest(BaseModel):
    move_line_id: int
    scanned_barcode: str = ""
    quantity: float = 0


def _require_identity(context: WriteRequestContext) -> None:
    if not context.identity.is_complete:
        raise HTTPException(
            status_code=400,
            detail="X-Picker-User-Id und X-Device-Id sind fuer diese Aktion erforderlich.",
        )


async def _require_resolved_identity(
    workflow: MobileWorkflowService,
    context: WriteRequestContext,
) -> PickerIdentity:
    _require_identity(context)
    try:
        return await workflow.resolve_identity(context.identity)
    except InvalidPickerIdentityError as exc:
        raise HTTPException(status_code=403, detail="Unbekannter oder inaktiver Picker.") from exc


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


@router.get("/pickers")
async def list_pickers(workflow=Depends(get_mobile_workflow_service)):
    """Aktive Odoo-Benutzer fuer die Picker-Auswahl."""
    return await workflow.list_pickers()


@router.get("/products/{product_id}/image")
async def get_product_image(
    product_id: int,
    odoo: OdooClient = Depends(get_odoo_client),
):
    """Produktbild (128px Thumbnail) aus Odoo als Binary."""
    products = await odoo.search_read(
        "product.product",
        [("id", "=", product_id)],
        ["image_128"],
        limit=1,
    )
    if not products or not products[0].get("image_128"):
        raise HTTPException(status_code=404, detail="Kein Bild vorhanden")

    image_data = base64.b64decode(products[0]["image_128"])
    media_type = "image/jpeg" if image_data[:3] == b"\xff\xd8\xff" else "image/png"
    return Response(
        content=image_data,
        media_type=media_type,
        headers={"Cache-Control": "public, max-age=3600"},
    )


@router.get("/pickings")
async def list_pickings(
    _picker_identity: PickerIdentity = Depends(get_required_picker_identity),
    service=Depends(get_picking_service),
):
    """Offene Pickings mit Move-Lines abrufen."""
    return await service.get_open_pickings()


@router.get("/pickings/{picking_id}")
async def get_picking(
    picking_id: int,
    _picker_identity: PickerIdentity = Depends(get_required_picker_identity),
    service=Depends(get_picking_service),
):
    """Einzelnes Picking mit Details."""
    return await service.get_picking_detail(picking_id)


@router.get("/pickings/{picking_id}/route-plan")
async def get_route_plan(
    picking_id: int,
    _picker_identity: PickerIdentity = Depends(get_required_picker_identity),
    service=Depends(get_picking_service),
):
    """Optimierte Reihenfolge fuer verbleibende Picking-Positionen."""
    return await service.get_picking_route_plan(picking_id)


@router.post("/pickings/{picking_id}/claim")
async def claim_picking(
    picking_id: int,
    workflow=Depends(get_mobile_workflow_service),
    context: WriteRequestContext = Depends(get_write_request_context),
):
    """Picking fuer ein Geraet / einen Picker reservieren."""
    resolved_identity = await _require_resolved_identity(workflow, context)
    fingerprint = workflow.build_request_fingerprint(
        {
            "action": "claim",
            "picking_id": picking_id,
            "picker_user_id": resolved_identity.user_id,
            "device_id": resolved_identity.device_id,
        }
    )
    reservation = await workflow.begin_idempotent_request("pickings.claim", context, fingerprint, picking_id)
    replay = _return_or_raise_replay(reservation)
    if replay is not None:
        return replay

    try:
        result = await workflow.claim_picking(picking_id, resolved_identity)
    except ClaimConflictError as exc:
        await _finalize_error(workflow, reservation, 409, exc.detail)
        raise HTTPException(status_code=409, detail=exc.detail) from exc
    except Exception:
        await workflow.abort_idempotent_request(reservation)
        raise

    await workflow.finalize_idempotent_request(reservation, result, 200)
    return result


@router.post("/pickings/{picking_id}/heartbeat")
async def heartbeat_picking(
    picking_id: int,
    workflow=Depends(get_mobile_workflow_service),
    context: WriteRequestContext = Depends(get_write_request_context),
):
    """Aktiven Claim verlaengern."""
    resolved_identity = await _require_resolved_identity(workflow, context)
    fingerprint = workflow.build_request_fingerprint(
        {
            "action": "heartbeat",
            "picking_id": picking_id,
            "picker_user_id": resolved_identity.user_id,
            "device_id": resolved_identity.device_id,
        }
    )
    reservation = await workflow.begin_idempotent_request("pickings.heartbeat", context, fingerprint, picking_id)
    replay = _return_or_raise_replay(reservation)
    if replay is not None:
        return replay

    try:
        result = await workflow.heartbeat_picking(picking_id, resolved_identity)
    except ClaimConflictError as exc:
        await _finalize_error(workflow, reservation, 409, exc.detail)
        raise HTTPException(status_code=409, detail=exc.detail) from exc
    except Exception:
        await workflow.abort_idempotent_request(reservation)
        raise

    await workflow.finalize_idempotent_request(reservation, result, 200)
    return result


@router.post("/pickings/{picking_id}/release")
async def release_picking(
    picking_id: int,
    workflow=Depends(get_mobile_workflow_service),
    context: WriteRequestContext = Depends(get_write_request_context),
):
    """Aktiven Claim freigeben."""
    resolved_identity = await _require_resolved_identity(workflow, context)
    fingerprint = workflow.build_request_fingerprint(
        {
            "action": "release",
            "picking_id": picking_id,
            "picker_user_id": resolved_identity.user_id,
            "device_id": resolved_identity.device_id,
        }
    )
    reservation = await workflow.begin_idempotent_request("pickings.release", context, fingerprint, picking_id)
    replay = _return_or_raise_replay(reservation)
    if replay is not None:
        return replay

    try:
        result = await workflow.release_picking(picking_id, resolved_identity)
    except ClaimConflictError as exc:
        await _finalize_error(workflow, reservation, 409, exc.detail)
        raise HTTPException(status_code=409, detail=exc.detail) from exc
    except Exception:
        await workflow.abort_idempotent_request(reservation)
        raise

    await workflow.finalize_idempotent_request(reservation, result, 200)
    return result


@router.post("/pickings/{picking_id}/confirm-line")
async def confirm_line(
    picking_id: int,
    body: ConfirmLineRequest,
    service=Depends(get_picking_service),
    workflow=Depends(get_mobile_workflow_service),
    context: WriteRequestContext = Depends(get_write_request_context),
):
    """Pick-Zeile per Scan bestaetigen."""
    resolved_identity = await _require_resolved_identity(workflow, context)
    fingerprint = workflow.build_request_fingerprint(
        {
            "picking_id": picking_id,
            "move_line_id": body.move_line_id,
            "scanned_barcode": body.scanned_barcode,
            "quantity": body.quantity,
        }
    )
    reservation = await workflow.begin_idempotent_request("pickings.confirm-line", context, fingerprint, picking_id)
    replay = _return_or_raise_replay(reservation)
    if replay is not None:
        return replay

    picker_identity = None
    try:
        await workflow.heartbeat_picking(picking_id, resolved_identity)
        picker_identity = resolved_identity

        result = await service.confirm_pick_line(
            picking_id,
            body.move_line_id,
            body.scanned_barcode,
            body.quantity,
            picker_identity=picker_identity,
        )
    except ClaimConflictError as exc:
        await _finalize_error(workflow, reservation, 409, exc.detail)
        raise HTTPException(status_code=409, detail=exc.detail) from exc
    except HTTPException:
        raise
    except Exception:
        await workflow.abort_idempotent_request(reservation)
        raise

    await workflow.finalize_idempotent_request(reservation, result, 200)
    return result


@router.get("/pickings/{picking_id}/stock")
async def get_stock_for_line(
    picking_id: int,  # noqa: ARG001 - kept for URL consistency
    product_id: int,
    location_id: int,
    _picker_identity: PickerIdentity = Depends(get_required_picker_identity),
    odoo: OdooClient = Depends(get_odoo_client),
):
    """
    Gibt den aktuellen Lagerbestand fuer ein Produkt an einem Standort zurueck.
    Wird von der PWA aufgerufen wenn der Picker fragt 'Wie viele noch da?'
    """
    domain = [("product_id", "=", product_id)]
    if location_id > 0:
        domain.append(("location_id", "=", location_id))
    quants = await odoo.search_read(
        "stock.quant",
        domain,
        ["quantity", "reserved_quantity"],
    )
    available = sum(q.get("quantity", 0) - q.get("reserved_quantity", 0) for q in quants)
    total = sum(q.get("quantity", 0) for q in quants)
    return {
        "product_id": product_id,
        "location_id": location_id,
        "quantity_available": round(available, 2),
        "quantity_total": round(total, 2),
    }
