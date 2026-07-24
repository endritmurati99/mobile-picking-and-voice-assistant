from datetime import datetime, timezone
from uuid import UUID

import pytest
from pydantic import ValidationError

from app.models.events import (
    CallbackApplyResponse,
    CallbackEnvelopeV2,
    EventAcceptanceRequest,
    EventAcceptanceResponse,
    EventEnvelopeV2,
    serialize_event_envelope,
)


def valid_event() -> dict:
    return {
        "schema_version": "v2",
        "event_name": "quality.assessment.requested.v1",
        "event_id": "a4ff5ca2-4546-4ea4-8e6c-b75bc003ca32",
        "correlation_id": "0b2f7909-4ad9-44c1-8527-e775fe6d4bec",
        "causation_id": None,
        "occurred_at": datetime(2026, 7, 23, 12, 0, tzinfo=timezone.utc),
        "source": {"service": "picking-assistant-api", "odoo_instance": "o19"},
        "actor": {
            "type": "picker",
            "user_id": 7,
            "name": "Mina Muster",
            "device_id": "device-42",
        },
        "aggregate": {"model": "quality.alert.custom", "id": 42, "revision": 1},
        "payload": {"job_id": "4ddb2442-e58a-47fe-9a6f-1ec1d779ef88", "media": []},
    }


def test_event_serialization_is_deterministic_and_contains_no_base64_field():
    event = EventEnvelopeV2.model_validate(valid_event())
    first = serialize_event_envelope(event)
    second = serialize_event_envelope(event)
    assert first == second
    assert b'"schema_version":"v2"' in first
    assert b'"event_id":"a4ff5ca2-4546-4ea4-8e6c-b75bc003ca32"' in first
    assert b"base64" not in first.lower()


def test_event_rejects_unknown_fields_and_naive_time():
    data = valid_event()
    data["source"]["database"] = "must-not-leak"
    data["occurred_at"] = datetime(2026, 7, 23, 12, 0)
    with pytest.raises(ValidationError):
        EventEnvelopeV2.model_validate(data)


def test_event_rejects_unregistered_name():
    data = valid_event()
    data["event_name"] = "pick-confirmed"
    with pytest.raises(ValidationError):
        EventEnvelopeV2.model_validate(data)


def valid_callback() -> dict:
    return {
        "schema_version": "v2",
        "callback_name": "quality.assessment.status.v1",
        "callback_id": "b1c2d3e4-1111-4222-8333-444455556666",
        "source_event_id": "a4ff5ca2-4546-4ea4-8e6c-b75bc003ca32",
        "correlation_id": "0b2f7909-4ad9-44c1-8527-e775fe6d4bec",
        "odoo_instance": "o19",
        "job_id": "4ddb2442-e58a-47fe-9a6f-1ec1d779ef88",
        "sequence": 1,
        "attempt": 1,
        "delivery_generation": 1,
        "processing_lease_token": "l" * 32,
        "status": "succeeded",
        "execution_id": "exec-1",
        "occurred_at": datetime(2026, 7, 23, 12, 0, tzinfo=timezone.utc),
        "next_retry_at": None,
        "result": {},
        "error": None,
        "metrics": {},
    }


def test_callback_envelope_v2_constructs_valid():
    callback = CallbackEnvelopeV2.model_validate(valid_callback())
    assert callback.status == "succeeded"
    assert callback.job_id == UUID("4ddb2442-e58a-47fe-9a6f-1ec1d779ef88")


def test_callback_envelope_v2_rejects_unknown_fields():
    data = valid_callback()
    data["unexpected"] = "nope"
    with pytest.raises(ValidationError):
        CallbackEnvelopeV2.model_validate(data)


def test_callback_envelope_v2_accepts_valid_terminal_status():
    data = valid_callback()
    data["status"] = "running"
    callback = CallbackEnvelopeV2.model_validate(data)
    assert callback.status == "running"


def test_callback_envelope_v2_rejects_queued_status():
    data = valid_callback()
    data["status"] = "queued"
    with pytest.raises(ValidationError):
        CallbackEnvelopeV2.model_validate(data)


def valid_acceptance_request() -> dict:
    return {
        "schema_version": "v2",
        "event_id": "a4ff5ca2-4546-4ea4-8e6c-b75bc003ca32",
        "job_id": "4ddb2442-e58a-47fe-9a6f-1ec1d779ef88",
        "odoo_instance": "o19",
        "payload_fingerprint": "a" * 64,
        "ingress_key_id": "active",
        "ingress_nonce": "123e4567-e89b-42d3-a456-426614174000",
        "delivery_generation": 1,
    }


def test_event_acceptance_request_constructs_valid():
    request = EventAcceptanceRequest.model_validate(valid_acceptance_request())
    assert request.delivery_generation == 1


def test_event_acceptance_request_rejects_unknown_fields():
    data = valid_acceptance_request()
    data["extra"] = "nope"
    with pytest.raises(ValidationError):
        EventAcceptanceRequest.model_validate(data)


def valid_acceptance_response() -> dict:
    return {
        "accepted": True,
        "event_id": "a4ff5ca2-4546-4ea4-8e6c-b75bc003ca32",
        "process": True,
        "processing_lease_token": "l" * 32,
    }


def test_event_acceptance_response_constructs_valid():
    response = EventAcceptanceResponse.model_validate(valid_acceptance_response())
    assert response.processing_lease_token == "l" * 32


def test_event_acceptance_response_rejects_unknown_fields():
    data = valid_acceptance_response()
    data["extra"] = "nope"
    with pytest.raises(ValidationError):
        EventAcceptanceResponse.model_validate(data)


def valid_callback_apply_response() -> dict:
    return {
        "status": "applied",
        "job_id": "4ddb2442-e58a-47fe-9a6f-1ec1d779ef88",
        "sequence": 0,
    }


def test_callback_apply_response_constructs_valid():
    response = CallbackApplyResponse.model_validate(valid_callback_apply_response())
    assert response.sequence == 0


def test_callback_apply_response_rejects_unknown_fields():
    data = valid_callback_apply_response()
    data["extra"] = "nope"
    with pytest.raises(ValidationError):
        CallbackApplyResponse.model_validate(data)
