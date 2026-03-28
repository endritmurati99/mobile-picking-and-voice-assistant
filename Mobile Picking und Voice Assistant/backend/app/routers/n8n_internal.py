"""Internal callback endpoints for n8n writebacks."""
from __future__ import annotations

from datetime import datetime, timezone
from html import escape
import logging

from fastapi import APIRouter, Depends, Header, HTTPException

from app.dependencies import (
    get_mobile_workflow_service,
    get_odoo_client,
    get_write_request_context,
    require_n8n_callback_secret,
)
from app.models.n8n import (
    ManualReviewActivityRequest,
    N8NCommandResponse,
    QualityAssessmentCallbackRequest,
    QualityAssessmentFailedRequest,
    ReplenishmentActionRequest,
)
from app.services.mobile_workflow import IdempotencyReservation, MobileWorkflowService, WriteRequestContext
from app.services.odoo_client import OdooAPIError, OdooClient

router = APIRouter(prefix="/internal/n8n", tags=["n8n-internal"])
logger = logging.getLogger(__name__)


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


def _analysis_timestamp(value: datetime | None) -> str:
    resolved = value or datetime.now(timezone.utc)
    return resolved.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


async def _post_chatter_note_best_effort(
    odoo: OdooClient,
    *,
    model: str,
    record_id: int,
    body_html: str,
) -> None:
    try:
        await odoo.execute_kw(
            model,
            "message_post",
            [[record_id]],
            {"body": body_html, "message_type": "comment", "subtype_xmlid": "mail.mt_note"},
        )
    except Exception as exc:
        detail = exc.message if isinstance(exc, OdooAPIError) else str(exc)
        logger.warning("Could not post chatter note for %s(%s): %s", model, record_id, detail)


async def _create_activity_best_effort(
    odoo: OdooClient,
    *,
    model: str,
    record_id: int,
    summary: str,
    note: str,
) -> None:
    try:
        model_ids = await odoo.execute_kw("ir.model", "search", [[["model", "=", model]]])
        if not model_ids:
            return
        await odoo.execute_kw(
            "mail.activity",
            "create",
            [{
                "res_model_id": model_ids[0],
                "res_id": record_id,
                "summary": summary,
                "note": note,
            }],
        )
    except Exception as exc:
        detail = exc.message if isinstance(exc, OdooAPIError) else str(exc)
        logger.warning("Could not create mail.activity for %s(%s): %s", model, record_id, detail)


def _build_quality_success_note(body: QualityAssessmentCallbackRequest) -> str:
    parts = [
        "<strong>KI-Bewertung abgeschlossen</strong>",
        f"Einstufung: {escape(body.ai_disposition)}",
        f"Konfidenz: {body.ai_confidence:.0%}",
        f"Zusammenfassung: {escape(body.ai_summary)}",
    ]
    if body.ai_recommended_action:
        parts.append(f"Empfohlene Aktion: {escape(body.ai_recommended_action)}")
    if body.ai_provider or body.ai_model:
        provider = " / ".join(filter(None, [body.ai_provider, body.ai_model]))
        parts.append(f"Quelle: {escape(provider)}")
    return "<br/>".join(parts)


def _build_quality_failure_note(reason: str) -> str:
    return "<br/>".join(
        [
            "<strong>KI-Bewertung fehlgeschlagen</strong>",
            f"Grund: {escape(reason or 'Unbekannter Fehler')}",
        ]
    )


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


@router.post("/quality-assessment", response_model=N8NCommandResponse, dependencies=[Depends(require_n8n_callback_secret)])
async def quality_assessment_callback(
    body: QualityAssessmentCallbackRequest,
    workflow: MobileWorkflowService = Depends(get_mobile_workflow_service),
    odoo: OdooClient = Depends(get_odoo_client),
    context: WriteRequestContext = Depends(get_write_request_context),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    if not idempotency_key:
        raise HTTPException(status_code=400, detail="Idempotency-Key ist erforderlich.")
    if body.correlation_id and body.correlation_id != idempotency_key:
        raise HTTPException(status_code=409, detail="correlation_id und Idempotency-Key muessen identisch sein.")

    callback_context = WriteRequestContext(idempotency_key=idempotency_key, identity=context.identity)
    fingerprint = workflow.build_request_fingerprint(body.model_dump(mode="json"))
    reservation = await workflow.begin_idempotent_request(
        "n8n.quality-assessment",
        callback_context,
        fingerprint,
    )
    replay = _return_or_raise_replay(reservation)
    if replay is not None:
        return N8NCommandResponse(**replay)

    try:
        updated = await odoo.write(
            "quality.alert.custom",
            [body.alert_id],
            {
                "ai_disposition": body.ai_disposition,
                "ai_confidence": body.ai_confidence,
                "ai_summary": body.ai_summary,
                "ai_recommended_action": body.ai_recommended_action or False,
                "ai_last_analyzed_at": _analysis_timestamp(body.ai_last_analyzed_at),
                "ai_provider": body.ai_provider or False,
                "ai_model": body.ai_model or False,
                "ai_evaluation_status": "completed",
                "ai_failure_reason": False,
            },
        )
        if not updated:
            detail = "Quality Alert konnte nicht aktualisiert werden."
            await _finalize_error(workflow, reservation, 404, detail)
            raise HTTPException(status_code=404, detail=detail)
    except OdooAPIError as exc:
        detail = f"Odoo-Fehler: {exc.message}"
        await _finalize_error(workflow, reservation, 502, detail)
        raise HTTPException(status_code=502, detail=detail) from exc
    except Exception:
        await workflow.abort_idempotent_request(reservation)
        raise

    response = {
        "status": "applied",
        "correlation_id": body.correlation_id or idempotency_key or "",
        "detail": f"AI-Bewertung fuer Alert {body.alert_id} gespeichert.",
    }
    await _post_chatter_note_best_effort(
        odoo,
        model="quality.alert.custom",
        record_id=body.alert_id,
        body_html=_build_quality_success_note(body),
    )
    await workflow.finalize_idempotent_request(reservation, response, 200)
    return N8NCommandResponse(**response)


@router.post("/replenishment-action", response_model=N8NCommandResponse, dependencies=[Depends(require_n8n_callback_secret)])
async def replenishment_action_callback(
    body: ReplenishmentActionRequest,
    workflow: MobileWorkflowService = Depends(get_mobile_workflow_service),
    odoo: OdooClient = Depends(get_odoo_client),
    context: WriteRequestContext = Depends(get_write_request_context),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    if not idempotency_key:
        raise HTTPException(status_code=400, detail="Idempotency-Key ist erforderlich.")
    if body.correlation_id and body.correlation_id != idempotency_key:
        raise HTTPException(status_code=409, detail="correlation_id und Idempotency-Key muessen identisch sein.")

    callback_context = WriteRequestContext(idempotency_key=idempotency_key, identity=context.identity)
    fingerprint = workflow.build_request_fingerprint(body.model_dump(mode="json"))
    reservation = await workflow.begin_idempotent_request(
        "n8n.replenishment-action",
        callback_context,
        fingerprint,
        body.picking_id,
    )
    replay = _return_or_raise_replay(reservation)
    if replay is not None:
        return N8NCommandResponse(**replay)

    if body.product_id is None or body.location_id is None or body.recommended_location_id is None:
        detail = "product_id, location_id und recommended_location_id sind fuer Nachschub erforderlich."
        await _finalize_error(workflow, reservation, 400, detail)
        raise HTTPException(status_code=400, detail=detail)

    try:
        result = await odoo.execute_kw(
            "stock.picking",
            "api_create_replenishment_transfer",
            [
                body.picking_id,
                body.product_id,
                body.recommended_location_id,
                body.location_id,
                body.quantity or 1.0,
                body.ticket_text or body.reason,
                body.correlation_id or idempotency_key,
                body.requested_by_user_id or False,
                body.requested_by_name or False,
            ],
        )
        if not isinstance(result, dict) or not result.get("success"):
            detail = result.get("message") if isinstance(result, dict) else "Nachschub konnte nicht erzeugt werden."
            await _finalize_error(workflow, reservation, 422, detail)
            raise HTTPException(status_code=422, detail=detail)
    except OdooAPIError as exc:
        detail = f"Odoo-Fehler: {exc.message}"
        await _finalize_error(workflow, reservation, 502, detail)
        raise HTTPException(status_code=502, detail=detail) from exc
    except Exception:
        await workflow.abort_idempotent_request(reservation)
        raise

    replenishment_name = result.get("replenishment_name") if isinstance(result, dict) else None
    detail = (
        f"Nachschubauftrag {replenishment_name} fuer Picking {body.picking_id} angelegt."
        if replenishment_name
        else f"Nachschubauftrag fuer Picking {body.picking_id} angelegt."
    )
    response = {
        "status": "applied",
        "correlation_id": body.correlation_id or idempotency_key or "",
        "detail": detail,
    }
    await workflow.finalize_idempotent_request(reservation, response, 200)
    return N8NCommandResponse(**response)


@router.post("/quality-assessment-failed", response_model=N8NCommandResponse, dependencies=[Depends(require_n8n_callback_secret)])
async def quality_assessment_failed_callback(
    body: QualityAssessmentFailedRequest,
    odoo: OdooClient = Depends(get_odoo_client),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    corr = body.correlation_id or idempotency_key or ""
    try:
        updated = await odoo.write(
            "quality.alert.custom",
            [body.alert_id],
            {
                "ai_evaluation_status": "failed",
                "ai_failure_reason": body.failure_reason or "Unbekannter Fehler",
            },
        )
        if not updated:
            raise HTTPException(status_code=404, detail=f"Quality Alert {body.alert_id} nicht gefunden.")
    except OdooAPIError as exc:
        raise HTTPException(status_code=502, detail=f"Odoo-Fehler: {exc.message}") from exc

    failure_reason = body.failure_reason or "Unbekannter Fehler"
    await _post_chatter_note_best_effort(
        odoo,
        model="quality.alert.custom",
        record_id=body.alert_id,
        body_html=_build_quality_failure_note(failure_reason),
    )
    await _create_activity_best_effort(
        odoo,
        model="quality.alert.custom",
        record_id=body.alert_id,
        summary="KI-Bewertung fehlgeschlagen",
        note=failure_reason,
    )

    return N8NCommandResponse(
        status="applied",
        correlation_id=corr,
        detail=f"AI-Status fuer Alert {body.alert_id} auf 'failed' gesetzt.",
    )


@router.post("/manual-review-activity", response_model=N8NCommandResponse, dependencies=[Depends(require_n8n_callback_secret)])
async def manual_review_activity_callback(
    body: ManualReviewActivityRequest,
    odoo: OdooClient = Depends(get_odoo_client),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    corr = body.correlation_id or idempotency_key or ""
    note_parts = [f"<strong>Manual Review Required</strong><br/>{body.reason}"]
    if body.execution_url:
        note_parts.append(f"<br/>n8n Execution: <a href='{body.execution_url}'>{body.execution_url}</a>")
    note_html = "".join(note_parts)

    try:
        await odoo.execute_kw(
            "stock.picking",
            "message_post",
            [[body.picking_id]],
            {"body": note_html, "message_type": "comment", "subtype_xmlid": "mail.mt_note"},
        )
    except OdooAPIError as exc:
        raise HTTPException(status_code=502, detail=f"Odoo-Fehler beim Chatter-Post: {exc.message}") from exc

    try:
        model_ids = await odoo.execute_kw("ir.model", "search", [[["model", "=", "stock.picking"]]])
        if model_ids:
            await odoo.execute_kw(
                "mail.activity",
                "create",
                [{
                    "res_model_id": model_ids[0],
                    "res_id": body.picking_id,
                    "summary": "Manual Review Required",
                    "note": body.reason,
                }],
            )
    except OdooAPIError:
        pass  # Activity creation is best-effort

    return N8NCommandResponse(
        status="applied",
        correlation_id=corr,
        detail=f"Review-Notiz und Aktivitaet fuer Picking {body.picking_id} erstellt.",
    )
