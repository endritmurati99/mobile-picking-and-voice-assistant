"""Interner Endpoint: lokale LLM-Qualitaetsbewertung fuer den n8n-Workflow.

n8n darf per SSRF-Policy nur das Backend erreichen. Der Workflow ruft daher diesen
Endpoint auf; das Backend spricht mit dem lokalen Ollama-Container. Bei llm_ok=False
faellt der Workflow auf die eingebaute Heuristik zurueck.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends

from app.config import settings
from app.dependencies import get_llm_client, require_n8n_callback_secret
from app.models.n8n import QualityDispositionRequest, QualityDispositionResponse
from app.services.llm_client import LlmClient

router = APIRouter(prefix="/internal/llm", tags=["llm-internal"])
logger = logging.getLogger(__name__)


@router.post(
    "/quality-disposition",
    response_model=QualityDispositionResponse,
    dependencies=[Depends(require_n8n_callback_secret)],
)
async def quality_disposition(
    body: QualityDispositionRequest,
    llm: LlmClient = Depends(get_llm_client),
) -> QualityDispositionResponse:
    if settings.llm_provider != "ollama":
        return QualityDispositionResponse(
            llm_ok=False,
            llm_model=settings.llm_model,
            llm_provider=settings.llm_provider,
        )

    result = await llm.classify_disposition(
        description=body.description,
        priority=body.priority,
        photo_count=body.photo_count,
        product_id=body.product_id,
        location_id=body.location_id,
    )
    if not result.ok:
        return QualityDispositionResponse(
            llm_ok=False,
            llm_model=result.model,
            llm_provider=LlmClient.PROVIDER,
        )
    return QualityDispositionResponse(
        llm_ok=True,
        llm_disposition=result.disposition,
        llm_confidence=result.confidence,
        llm_summary=result.summary,
        llm_recommended_action=result.recommended_action,
        llm_model=result.model,
        llm_provider=LlmClient.PROVIDER,
    )
