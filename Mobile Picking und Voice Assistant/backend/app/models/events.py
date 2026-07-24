import json
from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

EVENT_NAMES = frozenset(
    {"quality.assessment.requested.v1", "shipment.parcel.ready.v1"}
)
CALLBACK_NAMES = frozenset(
    {"quality.assessment.status.v1", "shipping.label.status.v1"}
)
JOB_STATUSES = frozenset(
    {"queued", "running", "succeeded", "review_required", "retry_scheduled", "failed"}
)


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must include a timezone")
    return value


class EventSource(StrictModel):
    service: Literal["picking-assistant-api"]
    odoo_instance: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,63}$")


class EventActor(StrictModel):
    type: Literal["picker", "supervisor", "system"]
    user_id: int | None = Field(default=None, ge=1)
    name: str | None = Field(default=None, max_length=256)
    device_id: str | None = Field(default=None, max_length=128)


class EventAggregate(StrictModel):
    model: str = Field(min_length=1, max_length=128)
    id: int = Field(ge=1)
    revision: int = Field(ge=1)


class EventEnvelopeV2(StrictModel):
    schema_version: Literal["v2"]
    event_name: str
    event_id: UUID
    correlation_id: UUID
    causation_id: UUID | None
    occurred_at: datetime
    source: EventSource
    actor: EventActor
    aggregate: EventAggregate
    payload: dict[str, Any]

    _validate_time = field_validator("occurred_at")(_aware)

    @field_validator("event_name")
    @classmethod
    def known_event(cls, value: str) -> str:
        if value not in EVENT_NAMES:
            raise ValueError("unregistered event name")
        return value


class CallbackEnvelopeV2(StrictModel):
    schema_version: Literal["v2"]
    callback_name: str
    callback_id: UUID
    source_event_id: UUID
    correlation_id: UUID
    odoo_instance: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,63}$")
    job_id: UUID
    sequence: int = Field(ge=1)
    attempt: int = Field(ge=1)
    delivery_generation: int = Field(ge=1)
    processing_lease_token: str = Field(min_length=32, max_length=256)
    status: str
    execution_id: str = Field(min_length=1, max_length=256)
    occurred_at: datetime
    next_retry_at: datetime | None
    result: dict[str, Any]
    error: dict[str, Any] | None
    metrics: dict[str, Any]

    _validate_time = field_validator("occurred_at")(_aware)

    @field_validator("callback_name")
    @classmethod
    def known_callback(cls, value: str) -> str:
        if value not in CALLBACK_NAMES:
            raise ValueError("unregistered callback name")
        return value

    @field_validator("status")
    @classmethod
    def known_status(cls, value: str) -> str:
        if value not in JOB_STATUSES - {"queued"}:
            raise ValueError("invalid callback status")
        return value


class EventAcceptanceRequest(StrictModel):
    schema_version: Literal["v2"]
    event_id: UUID
    job_id: UUID
    odoo_instance: str
    payload_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    ingress_key_id: str
    ingress_nonce: UUID
    delivery_generation: int = Field(ge=1)


class EventAcceptanceResponse(StrictModel):
    accepted: Literal[True]
    event_id: UUID
    process: bool
    processing_lease_token: str | None = None


class CallbackApplyResponse(StrictModel):
    status: Literal["applied", "replayed", "ignored_stale"]
    job_id: UUID
    sequence: int = Field(ge=0)


def serialize_event_envelope(envelope: EventEnvelopeV2) -> bytes:
    return json.dumps(
        envelope.model_dump(mode="json"),
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
