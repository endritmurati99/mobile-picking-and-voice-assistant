"""Pydantic models for n8n-facing routes."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class VoiceAssistRequest(BaseModel):
    text: str
    intent: str
    surface: str = "detail"
    picking_id: int | None = None
    move_line_id: int | None = None
    product_id: int | None = None
    location_id: int | None = None
    remaining_line_count: int = 0


class VoiceAssistResponse(BaseModel):
    status: str
    tts_text: str
    source: str
    correlation_id: str
    latency_ms: int
    fallback_reason: str | None = None
    recommendation: dict | None = None


class QualityAssessmentCallbackRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    correlation_id: str | None = None
    alert_id: int
    ai_disposition: str
    ai_confidence: float = Field(ge=0.0, le=1.0)
    ai_summary: str
    ai_recommended_action: str | None = None
    ai_last_analyzed_at: datetime | None = None
    ai_provider: str | None = None
    ai_model: str | None = None


class ReplenishmentActionRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    correlation_id: str | None = None
    picking_id: int
    product_id: int | None = None
    location_id: int | None = None
    recommended_location_id: int | None = None
    recommended_location: str | None = None
    quantity: float | None = None
    reason: str
    ticket_text: str | None = None
    requested_by_user_id: int | None = None
    requested_by_name: str | None = None


class QualityAssessmentFailedRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    correlation_id: str | None = None
    alert_id: int
    failure_reason: str


class ManualReviewActivityRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    correlation_id: str | None = None
    picking_id: int
    reason: str
    execution_url: str | None = None


class N8NCommandResponse(BaseModel):
    status: str
    correlation_id: str
    detail: str
