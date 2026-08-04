"""Die v2-signierte Bewertungsroute.

Sie existiert, weil der signierte n8n-Knoten keinen frei gesetzten Header
tragen kann (`PwrSignedHttpRequest` kennt nur `pwrOutboundHmac`), die alte
Route `/api/internal/llm/quality-disposition` aber genau auf
`X-N8N-Callback-Secret` besteht. Eine Auth-Art fuer die ganze v2-Kette statt
zwei nebeneinander.
"""
import json

import pytest
from fastapi.testclient import TestClient

from app import dependencies
from app.main import app
from app.services.llm_client import LlmDispositionResult

# `signed_env` bringt fixierte Uhr, fixierten Keyring und Fake-Odoo je Instanz.
from tests.test_n8n_v2_routes import signed_env, signed_headers  # noqa: F401

ASSESS_TARGET = "/api/internal/n8n/v2/assessments/quality"

ASSESS = {
    "schema_version": "v2",
    "event_id": "a4ff5ca2-4546-4ea4-8e6c-b75bc003ca32",
    "job_id": "4ddb2442-e58a-47fe-9a6f-1ec1d779ef88",
    "odoo_instance": "o19-a",
    "delivery_generation": 1,
    "processing_lease_token": "lease-" + ("x" * 40),
    "description": "Karton zerdrueckt, Ware nass",
    "priority": "1",
    "photo_count": 2,
    "product_id": 42,
    "location_id": 8,
}


def assess_body(overrides=None):
    payload = dict(ASSESS)
    payload.update(overrides or {})
    return json.dumps(payload, separators=(",", ":")).encode()


class FakeLlm:
    def __init__(self, result):
        self.result = result
        self.calls = []

    async def classify_disposition(self, **kwargs):
        self.calls.append(kwargs)
        return self.result


def install_llm(result):
    fake = FakeLlm(result)
    app.dependency_overrides[dependencies.get_llm_client] = lambda: fake
    return fake


@pytest.fixture
def llm_ok(signed_env):
    fake = install_llm(
        LlmDispositionResult(
            ok=True,
            model="qwen2.5:7b",
            disposition="scrap",
            confidence=0.95,
            summary="Ware unbrauchbar.",
            recommended_action="Artikel sperren.",
        )
    )
    yield fake
    app.dependency_overrides.pop(dependencies.get_llm_client, None)


@pytest.fixture
def llm_down(signed_env):
    fake = install_llm(LlmDispositionResult(ok=False, model="qwen2.5:7b"))
    yield fake
    app.dependency_overrides.pop(dependencies.get_llm_client, None)


def post(body, **header_kwargs):
    headers = signed_headers(
        body,
        ASSESS_TARGET,
        idempotency_key=header_kwargs.pop("idempotency_key", ASSESS["event_id"]),
        **header_kwargs,
    )
    with TestClient(app) as client:
        return client.post(ASSESS_TARGET, content=body, headers=headers)


def test_signed_assessment_returns_the_verdict(llm_ok):
    response = post(assess_body())
    assert response.status_code == 200
    data = response.json()
    assert data["llm_ok"] is True
    assert data["disposition"] == "scrap"
    assert data["confidence"] == 0.95
    assert data["provider"] == "ollama-local"
    assert data["model"] == "qwen2.5:7b"
    assert llm_ok.calls[0]["description"] == ASSESS["description"]
    assert llm_ok.calls[0]["photo_count"] == 2


def test_unsigned_request_is_rejected(llm_ok):
    body = assess_body()
    with TestClient(app) as client:
        response = client.post(
            ASSESS_TARGET,
            content=body,
            headers={
                "Content-Type": "application/json",
                "Idempotency-Key": ASSESS["event_id"],
            },
        )
    assert response.status_code in (401, 403)
    assert llm_ok.calls == []


def test_idempotency_key_must_equal_event_id(llm_ok):
    response = post(assess_body(), idempotency_key="etwas-anderes")
    assert response.status_code == 409
    assert llm_ok.calls == []


def test_signed_generation_must_match_the_body(llm_ok):
    body = assess_body()
    with TestClient(app) as client:
        response = client.post(
            ASSESS_TARGET,
            content=body,
            headers=signed_headers(
                body,
                ASSESS_TARGET,
                generation=2,
                idempotency_key=ASSESS["event_id"],
            ),
        )
    assert response.status_code == 409
    assert llm_ok.calls == []


def test_unknown_field_is_refused(llm_ok):
    response = post(assess_body({"schmuggel": "x"}))
    assert response.status_code == 422
    assert llm_ok.calls == []


def test_llm_failure_reports_not_ok_without_verdict(llm_down):
    response = post(assess_body())
    assert response.status_code == 200
    data = response.json()
    assert data["llm_ok"] is False
    assert data["disposition"] is None
    assert data["confidence"] is None
    assert data["summary"] is None


def test_route_never_writes_to_odoo(llm_ok, signed_env):
    post(assess_body())
    assert all(client.calls == [] for client in signed_env.values())
