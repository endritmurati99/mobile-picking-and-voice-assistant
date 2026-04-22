"""
Quality-Alert-Endpoints.
Erstellt quality.alert.custom Records in Odoo 18 mit optionalem Foto-Attachment.
Loest anschliessend n8n-Workflow (fire-and-forget) aus.
"""
import base64
from datetime import datetime, timezone
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
from app.services.n8n_webhook import N8NWebhookClient, coerce_event_result
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


def _normalize_shadow_text(value: str) -> str:
    text = str(value or "").strip().lower()
    translation = str.maketrans(
        {
            "ä": "ae",
            "ö": "oe",
            "ü": "ue",
            "ß": "ss",
        }
    )
    return text.translate(translation)


def _infer_shadow_assessment(description: str):
    text = _normalize_shadow_text(description)
    damage_keywords = (
        "defekt",
        "kaputt",
        "beschaedigt",
        "beschadigt",
        "gebrochen",
        "bruch",
        "riss",
        "delle",
    )
    shortage_keywords = (
        "fehlt",
        "fehlmenge",
        "mindermenge",
        "zu wenig",
        "unvollstaendig",
    )
    wrong_item_keywords = (
        "falscher artikel",
        "falsches produkt",
        "falsch geliefert",
        "vertauscht",
        "wrong item",
    )

    if any(keyword in text for keyword in damage_keywords):
        return {
            "disposition": "scrap",
            "confidence": 0.83,
            "summary": "Lokale Fallback-Bewertung: Textsignal deutet auf Schaden/Defekt.",
            "recommended_action": "Artikel sperren und Ersatzpruefung starten.",
        }
    if any(keyword in text for keyword in shortage_keywords):
        return {
            "disposition": "rework",
            "confidence": 0.79,
            "summary": "Lokale Fallback-Bewertung: Textsignal deutet auf Fehlmenge.",
            "recommended_action": "Nachschubauftrag pruefen und Bestand verifizieren.",
        }
    if any(keyword in text for keyword in wrong_item_keywords):
        return {
            "disposition": "quarantine",
            "confidence": 0.76,
            "summary": "Lokale Fallback-Bewertung: Textsignal deutet auf falschen Artikel.",
            "recommended_action": "Artikel in Quarantaene und Klärung mit Wareneingang.",
        }
    return {
        "disposition": "rework",
        "confidence": 0.58,
        "summary": "Lokale Fallback-Bewertung: Keine eindeutige Kategorie erkennbar.",
        "recommended_action": "Manuelle Qualitaetspruefung durchfuehren.",
    }


async def _apply_local_quality_fallback(
    *,
    odoo: OdooClient,
    alert_id: int,
    description: str,
    failure_reason: str,
) -> None:
    assessment = _infer_shadow_assessment(description)
    analyzed_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    write_values = {
        "ai_disposition": assessment["disposition"],
        "ai_confidence": assessment["confidence"],
        "ai_summary": assessment["summary"],
        "ai_enhanced_description": description or False,
        "ai_photo_analysis": "Keine Fotoanalyse (lokaler Fallback ohne n8n).",
        "ai_recommended_action": assessment["recommended_action"],
        "ai_last_analyzed_at": analyzed_at,
        "ai_provider": "backend-local-fallback",
        "ai_model": "keyword-heuristic-v1",
        "ai_evaluation_status": "completed",
        "ai_failure_reason": False,
    }
    await odoo.write("quality.alert.custom", [alert_id], write_values)
    try:
        await odoo.execute_kw(
            "quality.alert.custom",
            "message_post",
            [[alert_id]],
            {
                "body": (
                    "Systembewertung lokal abgeschlossen (Fallback), "
                    f"weil n8n nicht erreichbar war: {failure_reason}"
                ),
            },
        )
    except Exception:
        logger.warning("Could not post fallback chatter note for alert %s", alert_id)


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

    reported_by = "mobile-picking-assistant"
    reported_by_user_id = False
    reported_by_device_id = ""
    if picker_identity and picker_identity.user_id:
        reported_by = picker_identity.picker_name or reported_by
        reported_by_user_id = picker_identity.user_id
        reported_by_device_id = picker_identity.device_id or ""

    event_result = coerce_event_result(await n8n.fire_event(
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
    ))

    if not event_result.delivered:
        failure_reason = event_result.error or "n8n konnte die Systembewertung nicht starten."
        if alert_id:
            try:
                await _apply_local_quality_fallback(
                    odoo=odoo,
                    alert_id=alert_id,
                    description=description,
                    failure_reason=failure_reason,
                )
                response = {
                    "alert_id": alert_id,
                    "name": name,
                    "photo_count": len(photo_list),
                    "ai_evaluation_status": "completed",
                    "ai_fallback": True,
                }
                await workflow.finalize_idempotent_request(reservation, response, 200)
                return response
            except Exception:
                logger.exception("Local fallback assessment failed for alert %s", alert_id)
                try:
                    await odoo.write(
                        "quality.alert.custom",
                        [alert_id],
                        {
                            "ai_evaluation_status": "failed",
                            "ai_failure_reason": failure_reason,
                        },
                    )
                except Exception:
                    logger.warning("Could not persist n8n dispatch failure for alert %s", alert_id)

        alert_label = name or f"Alert {alert_id}"
        detail = f"{alert_label} wurde erstellt, aber die Systembewertung konnte nicht gestartet werden: {failure_reason}"
        await _finalize_error(workflow, reservation, 502, detail)
        raise HTTPException(status_code=502, detail=detail)

    if alert_id:
        try:
            await odoo.write("quality.alert.custom", [alert_id], {"ai_evaluation_status": "pending"})
        except Exception:
            logger.warning("Could not set ai_evaluation_status=pending for alert %s", alert_id)

    response = {"alert_id": alert_id, "name": name, "photo_count": len(photo_list), "ai_evaluation_status": "pending"}
    await workflow.finalize_idempotent_request(reservation, response, 200)
    return response
