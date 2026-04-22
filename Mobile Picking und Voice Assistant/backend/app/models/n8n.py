"""Pydantic models for n8n-facing routes."""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

_ALLOWED_LATENCY_STAGE_KEYS = {"ingest_ms", "heuristic_ms", "callback_ms"}


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


def _validate_latency_map(
    value: dict[str, int] | None,
    *,
    field_name: str,
    allowed_keys: set[str] | None = None,
) -> dict[str, int] | None:
    if value is None:
        return None

    invalid_values = [key for key, duration in value.items() if duration < 0]
    if invalid_values:
        invalid = ", ".join(sorted(invalid_values))
        raise ValueError(f"{field_name} darf keine negativen Werte enthalten: {invalid}")

    if allowed_keys is None:
        return value

    unknown_keys = sorted(set(value) - allowed_keys)
    if unknown_keys:
        invalid = ", ".join(unknown_keys)
        raise ValueError(f"{field_name} enthaelt ungueltige Keys: {invalid}")
    return value


class LatencyTracking(BaseModel):
    model_config = ConfigDict(extra="ignore")

    started_at: str | None = None
    total_duration_ms: int | None = Field(default=None, ge=0)
    stages: dict[str, int] | None = None
    extra_stages: dict[str, int] | None = None

    @field_validator("stages")
    @classmethod
    def validate_stages(cls, value: dict[str, int] | None) -> dict[str, int] | None:
        return _validate_latency_map(value, field_name="stages", allowed_keys=_ALLOWED_LATENCY_STAGE_KEYS)

    @field_validator("extra_stages")
    @classmethod
    def validate_extra_stages(cls, value: dict[str, int] | None) -> dict[str, int] | None:
        return _validate_latency_map(value, field_name="extra_stages")


class N8NCallbackMetadata(BaseModel):
    model_config = ConfigDict(extra="ignore")

    schema_version: str | None = None
    execution_id: str | None = None
    latency_tracking: LatencyTracking | None = None


class QualityAssessmentCallbackRequest(N8NCallbackMetadata):
    correlation_id: str | None = None
    alert_id: int
    ai_disposition: str
    ai_confidence: float = Field(ge=0.0, le=1.0)
    ai_summary: str
    ai_enhanced_description: str | None = None
    ai_photo_analysis: str | None = None
    ai_recommended_action: str | None = None
    ai_last_analyzed_at: datetime | None = None
    ai_provider: str | None = None
    ai_model: str | None = None


class QualityAssessmentAIRequest(N8NCallbackMetadata):
    schema_version: Literal["v1"] = "v1"
    execution_id: str = Field(min_length=1)
    latency_tracking: LatencyTracking
    correlation_id: str = Field(min_length=1)
    alert_id: int
    category: Literal["damage", "shortage", "wrong_item", "unclear"]
    confidence: float = Field(ge=0.0, le=1.0)
    reason: str
    model: str = Field(min_length=1)

    @field_validator("reason")
    @classmethod
    def validate_reason(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("reason darf nicht leer sein")
        return value.strip()


class ReplenishmentActionRequest(N8NCallbackMetadata):
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


class QualityAssessmentFailedRequest(N8NCallbackMetadata):
    correlation_id: str | None = None
    alert_id: int
    failure_reason: str


class ManualReviewActivityRequest(N8NCallbackMetadata):
    correlation_id: str | None = None
    picking_id: int
    reason: str
    execution_url: str | None = None


class N8NCommandResponse(BaseModel):
    status: str
    correlation_id: str
    detail: str
