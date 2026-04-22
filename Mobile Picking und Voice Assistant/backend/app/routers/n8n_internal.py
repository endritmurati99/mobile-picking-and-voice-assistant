"""Internal callback endpoints for n8n writebacks."""
from __future__ import annotations

from datetime import datetime, timezone
from html import escape, unescape
import json
import logging
import re

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
    QualityAssessmentAIRequest,
    QualityAssessmentCallbackRequest,
    QualityAssessmentFailedRequest,
    ReplenishmentActionRequest,
)
from app.services.mobile_workflow import IdempotencyReservation, MobileWorkflowService, WriteRequestContext
from app.services.odoo_client import OdooAPIError, OdooClient
from app.services.quality_shadow_evaluation import ShadowHeuristicResult, classify_quality_alert_shadow

router = APIRouter(prefix="/internal/n8n", tags=["n8n-internal"])
logger = logging.getLogger(__name__)
_HTML_TAG_RE = re.compile(r"<[^>]+>")


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


def _received_at_backend() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _resolve_correlation_id(body, idempotency_key: str | None) -> str:
    return getattr(body, "correlation_id", None) or idempotency_key or ""


def _dump_latency_tracking(body) -> dict | None:
    latency_tracking = getattr(body, "latency_tracking", None)
    if latency_tracking is None:
        return None
    return latency_tracking.model_dump(mode="json")


def _log_callback_event(
    *,
    workflow_name: str,
    callback_type: str,
    callback_status: str,
    correlation_id: str,
    idempotency_key: str | None,
    target_object_type: str,
    target_object_id: int | None,
    execution_id: str | None,
    schema_version: str | None,
    legacy_payload: bool,
    latency_tracking: dict | None,
    detail: str | None = None,
) -> None:
    event = {
        "workflow_name": workflow_name,
        "callback_type": callback_type,
        "callback_status": callback_status,
        "correlation_id": correlation_id,
        "idempotency_key": idempotency_key,
        "target_object_type": target_object_type,
        "target_object_id": target_object_id,
        "execution_id": execution_id,
        "schema_version": schema_version,
        "received_at_backend": _received_at_backend(),
        "legacy_payload": legacy_payload,
        "latency_tracking": latency_tracking,
    }
    if detail:
        event["detail"] = detail
    logger.info(json.dumps(event, ensure_ascii=False, sort_keys=True))


def _require_idempotency_key(
    body,
    *,
    idempotency_key: str | None,
    workflow_name: str,
    callback_type: str,
    target_object_type: str,
    target_object_id: int | None,
) -> None:
    correlation_id = _resolve_correlation_id(body, idempotency_key)
    schema_version = getattr(body, "schema_version", None)
    execution_id = getattr(body, "execution_id", None)
    legacy_payload = not bool(schema_version)
    latency_tracking = _dump_latency_tracking(body)

    if not idempotency_key:
        _log_callback_event(
            workflow_name=workflow_name,
            callback_type=callback_type,
            callback_status="rejected",
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
            target_object_type=target_object_type,
            target_object_id=target_object_id,
            execution_id=execution_id,
            schema_version=schema_version,
            legacy_payload=legacy_payload,
            latency_tracking=latency_tracking,
            detail="missing_idempotency_key",
        )
        raise HTTPException(status_code=400, detail="Idempotency-Key ist erforderlich.")

    if body.correlation_id and body.correlation_id != idempotency_key:
        _log_callback_event(
            workflow_name=workflow_name,
            callback_type=callback_type,
            callback_status="rejected",
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
            target_object_type=target_object_type,
            target_object_id=target_object_id,
            execution_id=execution_id,
            schema_version=schema_version,
            legacy_payload=legacy_payload,
            latency_tracking=latency_tracking,
            detail="correlation_id_mismatch",
        )
        raise HTTPException(status_code=409, detail="correlation_id und Idempotency-Key muessen identisch sein.")


def _log_replay_or_raise(
    reservation: IdempotencyReservation,
    *,
    workflow_name: str,
    callback_type: str,
    correlation_id: str,
    idempotency_key: str | None,
    target_object_type: str,
    target_object_id: int | None,
    execution_id: str | None,
    schema_version: str | None,
    legacy_payload: bool,
    latency_tracking: dict | None,
) -> dict | None:
    try:
        replay = _return_or_raise_replay(reservation)
    except HTTPException as exc:
        _log_callback_event(
            workflow_name=workflow_name,
            callback_type=callback_type,
            callback_status="replay",
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
            target_object_type=target_object_type,
            target_object_id=target_object_id,
            execution_id=execution_id,
            schema_version=schema_version,
            legacy_payload=legacy_payload,
            latency_tracking=latency_tracking,
            detail=str(exc.detail),
        )
        raise

    if replay is not None:
        _log_callback_event(
            workflow_name=workflow_name,
            callback_type=callback_type,
            callback_status="replay",
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
            target_object_type=target_object_type,
            target_object_id=target_object_id,
            execution_id=execution_id,
            schema_version=schema_version,
            legacy_payload=legacy_payload,
            latency_tracking=latency_tracking,
            detail=replay.get("detail") if isinstance(replay, dict) else None,
        )
    return replay


async def _post_chatter_note_best_effort(
    odoo: OdooClient,
    *,
    model: str,
    record_id: int,
    body: str,
) -> None:
    try:
        await odoo.execute_kw(
            model,
            "message_post",
            [[record_id]],
            {"body": body, "message_type": "comment", "subtype_xmlid": "mail.mt_note"},
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
    disposition = _sanitize_required_text(body.ai_disposition)
    summary = _sanitize_optional_text(body.ai_summary)
    enhanced_description = _sanitize_optional_text(body.ai_enhanced_description)
    photo_analysis = _sanitize_optional_text(body.ai_photo_analysis)
    recommended_action = _sanitize_optional_text(body.ai_recommended_action)
    provider = " / ".join(
        filter(
            None,
            [
                _sanitize_optional_text(body.ai_provider) or None,
                _sanitize_optional_text(body.ai_model) or None,
            ],
        )
    )
    parts = [
        "KI-Bewertung abgeschlossen",
        f"Einstufung: {disposition}",
        f"Konfidenz: {body.ai_confidence:.0%}",
    ]
    if summary:
        parts.append(f"Zusammenfassung: {summary}")
    if enhanced_description:
        parts.append(f"KI-verbesserte Beschreibung: {enhanced_description}")
    if photo_analysis:
        parts.append(f"Fotoanalyse: {photo_analysis}")
    if recommended_action:
        parts.append(f"Empfohlene Aktion: {recommended_action}")
    if provider:
        parts.append(f"Quelle: {provider}")
    return "\n".join(parts)


def _build_quality_failure_note(reason: str) -> str:
    failure_reason = _sanitize_optional_text(reason) or "Unbekannter Fehler"
    return "\n".join(
        [
            "KI-Bewertung fehlgeschlagen",
            f"Grund: {failure_reason}",
        ]
    )


def _sanitize_text(value: str | None) -> str:
    if value is None:
        return ""
    cleaned = unescape(str(value))
    cleaned = _HTML_TAG_RE.sub("", cleaned)
    cleaned = cleaned.replace("\r\n", "\n").replace("\r", "\n")
    lines = [line.strip() for line in cleaned.split("\n")]
    return "\n".join(line for line in lines if line).strip()


def _sanitize_optional_text(value: str | None) -> str | bool:
    cleaned = _sanitize_text(value)
    return cleaned or False


def _sanitize_required_text(value: str) -> str:
    cleaned = _sanitize_text(value)
    return cleaned or str(value).strip()


def _build_quality_write_values(body: QualityAssessmentCallbackRequest) -> dict:
    return {
        "ai_disposition": _sanitize_required_text(body.ai_disposition),
        "ai_confidence": body.ai_confidence,
        "ai_summary": _sanitize_optional_text(body.ai_summary),
        "ai_enhanced_description": _sanitize_optional_text(body.ai_enhanced_description),
        "ai_photo_analysis": _sanitize_optional_text(body.ai_photo_analysis),
        "ai_recommended_action": _sanitize_optional_text(body.ai_recommended_action),
        "ai_last_analyzed_at": _analysis_timestamp(body.ai_last_analyzed_at),
        "ai_provider": _sanitize_optional_text(body.ai_provider),
        "ai_model": _sanitize_optional_text(body.ai_model),
        "ai_evaluation_status": "completed",
        "ai_failure_reason": False,
    }


def _extract_ai_latency_ms(latency_tracking: dict | None) -> int | None:
    if not latency_tracking:
        return None
    extra_stages = latency_tracking.get("extra_stages") or {}
    for key in ("ai_shadow_ms", "shadow_ai_ms", "model_ms"):
        value = extra_stages.get(key)
        if isinstance(value, (int, float)) and value >= 0:
            return int(value)
    total_duration = latency_tracking.get("total_duration_ms")
    if isinstance(total_duration, (int, float)) and total_duration >= 0:
        return int(total_duration)
    return None


async def _load_quality_alert_shadow_context(odoo: OdooClient, alert_id: int) -> dict | None:
    alerts = await odoo.search_read(
        "quality.alert.custom",
        [("id", "=", alert_id)],
        ["id", "name", "description", "priority", "photo_count", "product_id", "location_id"],
        limit=1,
    )
    return alerts[0] if alerts else None


def _log_shadow_evaluation_event(
    *,
    alert: dict,
    body: QualityAssessmentAIRequest,
    heuristic: ShadowHeuristicResult,
    ai_latency_ms: int | None,
) -> None:
    description = _sanitize_text(alert.get("description"))
    photo_count = alert.get("photo_count") or 0
    try:
        normalized_photo_count = max(0, int(photo_count))
    except (TypeError, ValueError):
        normalized_photo_count = 0

    event = {
        "event_type": "quality_shadow_evaluation",
        "workflow_name": "quality-alert-ai-evaluation",
        "timestamp": _received_at_backend(),
        "alert_id": body.alert_id,
        "correlation_id": body.correlation_id,
        "heuristic_category": heuristic.category,
        "ai_category": body.category,
        "match": heuristic.category == body.category,
        "heuristic_confidence": heuristic.confidence,
        "ai_confidence": body.confidence,
        "confidence_delta": round(abs(body.confidence - heuristic.confidence), 4),
        "ai_latency_ms": ai_latency_ms,
        "text_length": len(description),
        "has_photo": normalized_photo_count > 0,
        "photo_count": normalized_photo_count,
        "model": _sanitize_required_text(body.model),
        "ai_reason": _sanitize_required_text(body.reason),
        "heuristic_reason": heuristic.reason,
        "schema_version": body.schema_version,
        "execution_id": body.execution_id,
    }
    logger.info(json.dumps(event, ensure_ascii=False, sort_keys=True))


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


@router.post(
    "/quality-assessment-ai",
    response_model=N8NCommandResponse,
    dependencies=[Depends(require_n8n_callback_secret)],
)
async def quality_assessment_ai_callback(
    body: QualityAssessmentAIRequest,
    workflow: MobileWorkflowService = Depends(get_mobile_workflow_service),
    odoo: OdooClient = Depends(get_odoo_client),
    context: WriteRequestContext = Depends(get_write_request_context),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    workflow_name = "quality-alert-ai-evaluation"
    callback_type = "quality_assessment_ai"
    target_object_type = "quality_alert_shadow"
    target_object_id = body.alert_id
    _require_idempotency_key(
        body,
        idempotency_key=idempotency_key,
        workflow_name=workflow_name,
        callback_type=callback_type,
        target_object_type=target_object_type,
        target_object_id=target_object_id,
    )

    callback_context = WriteRequestContext(idempotency_key=idempotency_key, identity=context.identity)
    fingerprint = workflow.build_request_fingerprint(body.model_dump(mode="json"))
    reservation = await workflow.begin_idempotent_request(
        "n8n.quality-assessment-ai",
        callback_context,
        fingerprint,
    )
    correlation_id = _resolve_correlation_id(body, idempotency_key)
    legacy_payload = not bool(body.schema_version)
    latency_tracking = _dump_latency_tracking(body)
    replay = _log_replay_or_raise(
        reservation,
        workflow_name=workflow_name,
        callback_type=callback_type,
        correlation_id=correlation_id,
        idempotency_key=idempotency_key,
        target_object_type=target_object_type,
        target_object_id=target_object_id,
        execution_id=body.execution_id,
        schema_version=body.schema_version,
        legacy_payload=legacy_payload,
        latency_tracking=latency_tracking,
    )
    if replay is not None:
        return N8NCommandResponse(**replay)

    try:
        alert = await _load_quality_alert_shadow_context(odoo, body.alert_id)
        if not alert:
            detail = "Quality Alert fuer Shadow-Evaluation nicht gefunden."
            await _finalize_error(workflow, reservation, 404, detail)
            _log_callback_event(
                workflow_name=workflow_name,
                callback_type=callback_type,
                callback_status="failed",
                correlation_id=correlation_id,
                idempotency_key=idempotency_key,
                target_object_type=target_object_type,
                target_object_id=target_object_id,
                execution_id=body.execution_id,
                schema_version=body.schema_version,
                legacy_payload=legacy_payload,
                latency_tracking=latency_tracking,
                detail=detail,
            )
            raise HTTPException(status_code=404, detail=detail)

        heuristic = classify_quality_alert_shadow(alert)
    except OdooAPIError as exc:
        detail = f"Odoo-Fehler: {exc.message}"
        await _finalize_error(workflow, reservation, 502, detail)
        _log_callback_event(
            workflow_name=workflow_name,
            callback_type=callback_type,
            callback_status="failed",
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
            target_object_type=target_object_type,
            target_object_id=target_object_id,
            execution_id=body.execution_id,
            schema_version=body.schema_version,
            legacy_payload=legacy_payload,
            latency_tracking=latency_tracking,
            detail=detail,
        )
        raise HTTPException(status_code=502, detail=detail) from exc
    except HTTPException:
        raise
    except Exception as exc:
        _log_callback_event(
            workflow_name=workflow_name,
            callback_type=callback_type,
            callback_status="aborted",
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
            target_object_type=target_object_type,
            target_object_id=target_object_id,
            execution_id=body.execution_id,
            schema_version=body.schema_version,
            legacy_payload=legacy_payload,
            latency_tracking=latency_tracking,
            detail=str(exc),
        )
        await workflow.abort_idempotent_request(reservation)
        raise

    response = {
        "status": "applied",
        "correlation_id": body.correlation_id,
        "detail": f"Shadow-AI-Bewertung fuer Alert {body.alert_id} protokolliert.",
    }
    await workflow.finalize_idempotent_request(reservation, response, 200)
    _log_callback_event(
        workflow_name=workflow_name,
        callback_type=callback_type,
        callback_status="applied",
        correlation_id=correlation_id,
        idempotency_key=idempotency_key,
        target_object_type=target_object_type,
        target_object_id=target_object_id,
        execution_id=body.execution_id,
        schema_version=body.schema_version,
        legacy_payload=legacy_payload,
        latency_tracking=latency_tracking,
        detail=response["detail"],
    )
    _log_shadow_evaluation_event(
        alert=alert,
        body=body,
        heuristic=heuristic,
        ai_latency_ms=_extract_ai_latency_ms(latency_tracking),
    )
    return N8NCommandResponse(**response)


@router.post("/quality-assessment", response_model=N8NCommandResponse, dependencies=[Depends(require_n8n_callback_secret)])
async def quality_assessment_callback(
    body: QualityAssessmentCallbackRequest,
    workflow: MobileWorkflowService = Depends(get_mobile_workflow_service),
    odoo: OdooClient = Depends(get_odoo_client),
    context: WriteRequestContext = Depends(get_write_request_context),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    workflow_name = "quality-alert-created"
    callback_type = "quality_assessment"
    target_object_type = "quality_alert"
    target_object_id = body.alert_id
    _require_idempotency_key(
        body,
        idempotency_key=idempotency_key,
        workflow_name=workflow_name,
        callback_type=callback_type,
        target_object_type=target_object_type,
        target_object_id=target_object_id,
    )

    callback_context = WriteRequestContext(idempotency_key=idempotency_key, identity=context.identity)
    fingerprint = workflow.build_request_fingerprint(body.model_dump(mode="json"))
    reservation = await workflow.begin_idempotent_request(
        "n8n.quality-assessment",
        callback_context,
        fingerprint,
    )
    correlation_id = _resolve_correlation_id(body, idempotency_key)
    legacy_payload = not bool(body.schema_version)
    latency_tracking = _dump_latency_tracking(body)
    replay = _log_replay_or_raise(
        reservation,
        workflow_name=workflow_name,
        callback_type=callback_type,
        correlation_id=correlation_id,
        idempotency_key=idempotency_key,
        target_object_type=target_object_type,
        target_object_id=target_object_id,
        execution_id=body.execution_id,
        schema_version=body.schema_version,
        legacy_payload=legacy_payload,
        latency_tracking=latency_tracking,
    )
    if replay is not None:
        return N8NCommandResponse(**replay)

    write_values = _build_quality_write_values(body)
    try:
        updated = await odoo.write(
            "quality.alert.custom",
            [body.alert_id],
            write_values,
        )
        if not updated:
            detail = "Quality Alert konnte nicht aktualisiert werden."
            await _finalize_error(workflow, reservation, 404, detail)
            _log_callback_event(
                workflow_name=workflow_name,
                callback_type=callback_type,
                callback_status="failed",
                correlation_id=correlation_id,
                idempotency_key=idempotency_key,
                target_object_type=target_object_type,
                target_object_id=target_object_id,
                execution_id=body.execution_id,
                schema_version=body.schema_version,
                legacy_payload=legacy_payload,
                latency_tracking=latency_tracking,
                detail=detail,
            )
            raise HTTPException(status_code=404, detail=detail)
    except OdooAPIError as exc:
        detail = f"Odoo-Fehler: {exc.message}"
        await _finalize_error(workflow, reservation, 502, detail)
        _log_callback_event(
            workflow_name=workflow_name,
            callback_type=callback_type,
            callback_status="failed",
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
            target_object_type=target_object_type,
            target_object_id=target_object_id,
            execution_id=body.execution_id,
            schema_version=body.schema_version,
            legacy_payload=legacy_payload,
            latency_tracking=latency_tracking,
            detail=detail,
        )
        raise HTTPException(status_code=502, detail=detail) from exc
    except Exception as exc:
        _log_callback_event(
            workflow_name=workflow_name,
            callback_type=callback_type,
            callback_status="aborted",
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
            target_object_type=target_object_type,
            target_object_id=target_object_id,
            execution_id=body.execution_id,
            schema_version=body.schema_version,
            legacy_payload=legacy_payload,
            latency_tracking=latency_tracking,
            detail=str(exc),
        )
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
        body=_build_quality_success_note(body),
    )
    await workflow.finalize_idempotent_request(reservation, response, 200)
    _log_callback_event(
        workflow_name=workflow_name,
        callback_type=callback_type,
        callback_status="applied",
        correlation_id=correlation_id,
        idempotency_key=idempotency_key,
        target_object_type=target_object_type,
        target_object_id=target_object_id,
        execution_id=body.execution_id,
        schema_version=body.schema_version,
        legacy_payload=legacy_payload,
        latency_tracking=latency_tracking,
        detail=response["detail"],
    )
    return N8NCommandResponse(**response)


@router.post("/replenishment-action", response_model=N8NCommandResponse, dependencies=[Depends(require_n8n_callback_secret)])
async def replenishment_action_callback(
    body: ReplenishmentActionRequest,
    workflow: MobileWorkflowService = Depends(get_mobile_workflow_service),
    odoo: OdooClient = Depends(get_odoo_client),
    context: WriteRequestContext = Depends(get_write_request_context),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    workflow_name = "shortage-reported"
    callback_type = "replenishment_action"
    target_object_type = "stock_picking"
    target_object_id = body.picking_id
    _require_idempotency_key(
        body,
        idempotency_key=idempotency_key,
        workflow_name=workflow_name,
        callback_type=callback_type,
        target_object_type=target_object_type,
        target_object_id=target_object_id,
    )

    callback_context = WriteRequestContext(idempotency_key=idempotency_key, identity=context.identity)
    fingerprint = workflow.build_request_fingerprint(body.model_dump(mode="json"))
    reservation = await workflow.begin_idempotent_request(
        "n8n.replenishment-action",
        callback_context,
        fingerprint,
        body.picking_id,
    )
    correlation_id = _resolve_correlation_id(body, idempotency_key)
    legacy_payload = not bool(body.schema_version)
    latency_tracking = _dump_latency_tracking(body)
    replay = _log_replay_or_raise(
        reservation,
        workflow_name=workflow_name,
        callback_type=callback_type,
        correlation_id=correlation_id,
        idempotency_key=idempotency_key,
        target_object_type=target_object_type,
        target_object_id=target_object_id,
        execution_id=body.execution_id,
        schema_version=body.schema_version,
        legacy_payload=legacy_payload,
        latency_tracking=latency_tracking,
    )
    if replay is not None:
        return N8NCommandResponse(**replay)

    if body.product_id is None or body.location_id is None or body.recommended_location_id is None:
        detail = "product_id, location_id und recommended_location_id sind fuer Nachschub erforderlich."
        await _finalize_error(workflow, reservation, 400, detail)
        _log_callback_event(
            workflow_name=workflow_name,
            callback_type=callback_type,
            callback_status="failed",
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
            target_object_type=target_object_type,
            target_object_id=target_object_id,
            execution_id=body.execution_id,
            schema_version=body.schema_version,
            legacy_payload=legacy_payload,
            latency_tracking=latency_tracking,
            detail=detail,
        )
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
            _log_callback_event(
                workflow_name=workflow_name,
                callback_type=callback_type,
                callback_status="failed",
                correlation_id=correlation_id,
                idempotency_key=idempotency_key,
                target_object_type=target_object_type,
                target_object_id=target_object_id,
                execution_id=body.execution_id,
                schema_version=body.schema_version,
                legacy_payload=legacy_payload,
                latency_tracking=latency_tracking,
                detail=detail,
            )
            raise HTTPException(status_code=422, detail=detail)
    except OdooAPIError as exc:
        detail = f"Odoo-Fehler: {exc.message}"
        await _finalize_error(workflow, reservation, 502, detail)
        _log_callback_event(
            workflow_name=workflow_name,
            callback_type=callback_type,
            callback_status="failed",
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
            target_object_type=target_object_type,
            target_object_id=target_object_id,
            execution_id=body.execution_id,
            schema_version=body.schema_version,
            legacy_payload=legacy_payload,
            latency_tracking=latency_tracking,
            detail=detail,
        )
        raise HTTPException(status_code=502, detail=detail) from exc
    except Exception as exc:
        _log_callback_event(
            workflow_name=workflow_name,
            callback_type=callback_type,
            callback_status="aborted",
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
            target_object_type=target_object_type,
            target_object_id=target_object_id,
            execution_id=body.execution_id,
            schema_version=body.schema_version,
            legacy_payload=legacy_payload,
            latency_tracking=latency_tracking,
            detail=str(exc),
        )
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
    _log_callback_event(
        workflow_name=workflow_name,
        callback_type=callback_type,
        callback_status="applied",
        correlation_id=correlation_id,
        idempotency_key=idempotency_key,
        target_object_type=target_object_type,
        target_object_id=target_object_id,
        execution_id=body.execution_id,
        schema_version=body.schema_version,
        legacy_payload=legacy_payload,
        latency_tracking=latency_tracking,
        detail=response["detail"],
    )
    return N8NCommandResponse(**response)


@router.post("/quality-assessment-failed", response_model=N8NCommandResponse, dependencies=[Depends(require_n8n_callback_secret)])
async def quality_assessment_failed_callback(
    body: QualityAssessmentFailedRequest,
    workflow: MobileWorkflowService = Depends(get_mobile_workflow_service),
    odoo: OdooClient = Depends(get_odoo_client),
    context: WriteRequestContext = Depends(get_write_request_context),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    workflow_name = "error-trigger"
    callback_type = "quality_assessment_failed"
    target_object_type = "quality_alert"
    target_object_id = body.alert_id
    _require_idempotency_key(
        body,
        idempotency_key=idempotency_key,
        workflow_name=workflow_name,
        callback_type=callback_type,
        target_object_type=target_object_type,
        target_object_id=target_object_id,
    )
    corr = _resolve_correlation_id(body, idempotency_key)
    legacy_payload = not bool(body.schema_version)
    latency_tracking = _dump_latency_tracking(body)
    callback_context = WriteRequestContext(idempotency_key=idempotency_key, identity=context.identity)
    fingerprint = workflow.build_request_fingerprint(body.model_dump(mode="json"))
    reservation = await workflow.begin_idempotent_request(
        "n8n.quality-assessment-failed",
        callback_context,
        fingerprint,
    )
    replay = _log_replay_or_raise(
        reservation,
        workflow_name=workflow_name,
        callback_type=callback_type,
        correlation_id=corr,
        idempotency_key=idempotency_key,
        target_object_type=target_object_type,
        target_object_id=target_object_id,
        execution_id=body.execution_id,
        schema_version=body.schema_version,
        legacy_payload=legacy_payload,
        latency_tracking=latency_tracking,
    )
    if replay is not None:
        return N8NCommandResponse(**replay)

    failure_reason = _sanitize_optional_text(body.failure_reason) or "Unbekannter Fehler"
    try:
        updated = await odoo.write(
            "quality.alert.custom",
            [body.alert_id],
            {
                "ai_evaluation_status": "failed",
                "ai_failure_reason": failure_reason,
            },
        )
        if not updated:
            detail = f"Quality Alert {body.alert_id} nicht gefunden."
            await _finalize_error(workflow, reservation, 404, detail)
            _log_callback_event(
                workflow_name=workflow_name,
                callback_type=callback_type,
                callback_status="failed",
                correlation_id=corr,
                idempotency_key=idempotency_key,
                target_object_type=target_object_type,
                target_object_id=target_object_id,
                execution_id=body.execution_id,
                schema_version=body.schema_version,
                legacy_payload=legacy_payload,
                latency_tracking=latency_tracking,
                detail=detail,
            )
            raise HTTPException(status_code=404, detail=f"Quality Alert {body.alert_id} nicht gefunden.")
    except OdooAPIError as exc:
        detail = f"Odoo-Fehler: {exc.message}"
        await _finalize_error(workflow, reservation, 502, detail)
        _log_callback_event(
            workflow_name=workflow_name,
            callback_type=callback_type,
            callback_status="failed",
            correlation_id=corr,
            idempotency_key=idempotency_key,
            target_object_type=target_object_type,
            target_object_id=target_object_id,
            execution_id=body.execution_id,
            schema_version=body.schema_version,
            legacy_payload=legacy_payload,
            latency_tracking=latency_tracking,
            detail=detail,
        )
        raise HTTPException(status_code=502, detail=detail) from exc
    except Exception as exc:
        _log_callback_event(
            workflow_name=workflow_name,
            callback_type=callback_type,
            callback_status="aborted",
            correlation_id=corr,
            idempotency_key=idempotency_key,
            target_object_type=target_object_type,
            target_object_id=target_object_id,
            execution_id=body.execution_id,
            schema_version=body.schema_version,
            legacy_payload=legacy_payload,
            latency_tracking=latency_tracking,
            detail=str(exc),
        )
        await workflow.abort_idempotent_request(reservation)
        raise

    await _post_chatter_note_best_effort(
        odoo,
        model="quality.alert.custom",
        record_id=body.alert_id,
        body=_build_quality_failure_note(failure_reason),
    )
    await _create_activity_best_effort(
        odoo,
        model="quality.alert.custom",
        record_id=body.alert_id,
        summary="KI-Bewertung fehlgeschlagen",
        note=failure_reason,
    )

    response = {
        "status": "applied",
        "correlation_id": corr,
        "detail": f"AI-Status fuer Alert {body.alert_id} auf 'failed' gesetzt.",
    }
    await workflow.finalize_idempotent_request(reservation, response, 200)
    _log_callback_event(
        workflow_name=workflow_name,
        callback_type=callback_type,
        callback_status="applied",
        correlation_id=corr,
        idempotency_key=idempotency_key,
        target_object_type=target_object_type,
        target_object_id=target_object_id,
        execution_id=body.execution_id,
        schema_version=body.schema_version,
        legacy_payload=legacy_payload,
        latency_tracking=latency_tracking,
        detail=response["detail"],
    )
    return N8NCommandResponse(
        status="applied",
        correlation_id=response["correlation_id"],
        detail=response["detail"],
    )


@router.post("/manual-review-activity", response_model=N8NCommandResponse, dependencies=[Depends(require_n8n_callback_secret)])
async def manual_review_activity_callback(
    body: ManualReviewActivityRequest,
    workflow: MobileWorkflowService = Depends(get_mobile_workflow_service),
    odoo: OdooClient = Depends(get_odoo_client),
    context: WriteRequestContext = Depends(get_write_request_context),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    workflow_name = "error-trigger"
    callback_type = "manual_review_activity"
    target_object_type = "stock_picking"
    target_object_id = body.picking_id
    _require_idempotency_key(
        body,
        idempotency_key=idempotency_key,
        workflow_name=workflow_name,
        callback_type=callback_type,
        target_object_type=target_object_type,
        target_object_id=target_object_id,
    )
    corr = _resolve_correlation_id(body, idempotency_key)
    legacy_payload = not bool(body.schema_version)
    latency_tracking = _dump_latency_tracking(body)
    callback_context = WriteRequestContext(idempotency_key=idempotency_key, identity=context.identity)
    fingerprint = workflow.build_request_fingerprint(body.model_dump(mode="json"))
    reservation = await workflow.begin_idempotent_request(
        "n8n.manual-review-activity",
        callback_context,
        fingerprint,
        body.picking_id,
    )
    replay = _log_replay_or_raise(
        reservation,
        workflow_name=workflow_name,
        callback_type=callback_type,
        correlation_id=corr,
        idempotency_key=idempotency_key,
        target_object_type=target_object_type,
        target_object_id=target_object_id,
        execution_id=body.execution_id,
        schema_version=body.schema_version,
        legacy_payload=legacy_payload,
        latency_tracking=latency_tracking,
    )
    if replay is not None:
        return N8NCommandResponse(**replay)

    note_parts = [f"<strong>Manual Review Required</strong><br/>{escape(body.reason)}"]
    if body.execution_url:
        safe_execution_url = escape(body.execution_url, quote=True)
        note_parts.append(f"<br/>n8n Execution: <a href='{safe_execution_url}'>{safe_execution_url}</a>")
    note_html = "".join(note_parts)

    try:
        await odoo.execute_kw(
            "stock.picking",
            "message_post",
            [[body.picking_id]],
            {"body": note_html, "message_type": "comment", "subtype_xmlid": "mail.mt_note"},
        )
    except OdooAPIError as exc:
        detail = f"Odoo-Fehler beim Chatter-Post: {exc.message}"
        await _finalize_error(workflow, reservation, 502, detail)
        _log_callback_event(
            workflow_name=workflow_name,
            callback_type=callback_type,
            callback_status="failed",
            correlation_id=corr,
            idempotency_key=idempotency_key,
            target_object_type=target_object_type,
            target_object_id=target_object_id,
            execution_id=body.execution_id,
            schema_version=body.schema_version,
            legacy_payload=legacy_payload,
            latency_tracking=latency_tracking,
            detail=detail,
        )
        raise HTTPException(status_code=502, detail=detail) from exc
    except Exception as exc:
        _log_callback_event(
            workflow_name=workflow_name,
            callback_type=callback_type,
            callback_status="aborted",
            correlation_id=corr,
            idempotency_key=idempotency_key,
            target_object_type=target_object_type,
            target_object_id=target_object_id,
            execution_id=body.execution_id,
            schema_version=body.schema_version,
            legacy_payload=legacy_payload,
            latency_tracking=latency_tracking,
            detail=str(exc),
        )
        await workflow.abort_idempotent_request(reservation)
        raise

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

    response = {
        "status": "applied",
        "correlation_id": corr,
        "detail": f"Review-Notiz und Aktivitaet fuer Picking {body.picking_id} erstellt.",
    }
    await workflow.finalize_idempotent_request(reservation, response, 200)
    _log_callback_event(
        workflow_name=workflow_name,
        callback_type=callback_type,
        callback_status="applied",
        correlation_id=corr,
        idempotency_key=idempotency_key,
        target_object_type=target_object_type,
        target_object_id=target_object_id,
        execution_id=body.execution_id,
        schema_version=body.schema_version,
        legacy_payload=legacy_payload,
        latency_tracking=latency_tracking,
        detail=response["detail"],
    )
    return N8NCommandResponse(
        status="applied",
        correlation_id=response["correlation_id"],
        detail=response["detail"],
    )
