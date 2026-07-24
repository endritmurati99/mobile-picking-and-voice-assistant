from datetime import datetime, timezone
from uuid import UUID

import pytest
from pydantic import ValidationError

from app.models.events import EventEnvelopeV2, serialize_event_envelope


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
