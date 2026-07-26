from copy import deepcopy

import pytest

from infrastructure.scripts.workflow_verifier import verify_v2_workflow

SPEC = {
    "file": "fixture.json",
    "generation": "v2",
    "webhook_paths": ["fixture-v2"],
    "callback_paths": ["/api/internal/n8n/v2/callbacks/status"],
    "allowed_target_hosts": ["backend"],
    "authentication": "native_header_hmac",
}

ARTIFACT_SPEC = {
    **SPEC,
    "artifact_path_templates": ["/api/internal/n8n/v2/artifacts/{event_id}/status"],
}

TEST_ONLY_SPEC = {**SPEC, "test_only": True}


@pytest.fixture
def v2_fixture():
    return {
        "name": "Fixture v2",
        "active": False,
        "nodes": [
            {
                "name": "Webhook",
                "type": "n8n-nodes-base.webhook",
                "parameters": {
                    "path": "fixture-v2",
                    "authentication": "headerAuth",
                    "options": {"rawBody": True},
                },
            },
            {
                "name": "PWR Signature Gate",
                "type": "CUSTOM.pwrSignatureGate",
                "parameters": {},
            },
            {
                "name": "Acceptance",
                "type": "CUSTOM.pwrSignedHttpRequest",
                "parameters": {
                    "target": "/api/internal/n8n/v2/events/accept",
                    "host": "backend",
                },
            },
        ],
        "connections": {
            "Webhook": {
                "main": [[{
                    "node": "PWR Signature Gate", "type": "main", "index": 0
                }]]
            },
            "PWR Signature Gate": {
                "main": [[{"node": "Acceptance", "type": "main", "index": 0}], []]
            },
        },
    }


@pytest.fixture
def verify():
    return lambda workflow, spec=SPEC: verify_v2_workflow(deepcopy(workflow), spec)


def test_v2_rejects_unauthenticated_webhook(v2_fixture, verify):
    v2_fixture["nodes"][0]["parameters"]["authentication"] = "none"
    errors = verify(v2_fixture)
    assert any("headerAuth" in error for error in errors)


def test_v2_rejects_business_node_before_gate(v2_fixture, verify):
    v2_fixture["connections"] = {
        "Webhook": {"main": [[{"node": "Model Call", "type": "main", "index": 0}]]},
    }
    errors = verify(v2_fixture)
    assert any("Signature Gate must be first" in error for error in errors)


def test_v2_rejects_normal_http_node_for_internal_callback(v2_fixture, verify):
    v2_fixture["nodes"].append({
        "name": "Unsafe Callback",
        "type": "n8n-nodes-base.httpRequest",
        "parameters": {
            "url": "http://backend:8000/api/internal/n8n/v2/callbacks/status"
        },
    })
    errors = verify(v2_fixture)
    assert any("PWR Signed HTTP Request" in error for error in errors)


def test_v2_accepts_registered_artifact_path_template(v2_fixture, verify):
    v2_fixture["nodes"][2]["parameters"]["target"] = "/api/internal/n8n/v2/artifacts/evt-123/status"
    errors = verify(v2_fixture, ARTIFACT_SPEC)
    assert errors == []


def test_v2_rejects_mismatching_resolved_segment(v2_fixture, verify):
    v2_fixture["nodes"][2]["parameters"]["target"] = "/api/internal/n8n/v2/artifacts/evt-123/wrong-suffix"
    errors = verify(v2_fixture, ARTIFACT_SPEC)
    assert any("not a registered target" in error for error in errors)


def test_v2_rejects_direct_odoo_target(v2_fixture, verify):
    v2_fixture["nodes"][2]["parameters"]["target"] = "http://odoo:8069/write"
    errors = verify(v2_fixture, ARTIFACT_SPEC)
    assert any("relative path" in error or "Odoo" in error for error in errors)


def test_v2_rejects_literal_body_mode_under_production_spec(v2_fixture, verify):
    v2_fixture["nodes"][2]["parameters"]["bodyMode"] = "literalUtf8"
    errors = verify(v2_fixture, SPEC)
    assert any("literalUtf8" in error for error in errors)


def test_v2_accepts_literal_body_mode_under_test_only_spec(v2_fixture, verify):
    v2_fixture["nodes"][2]["parameters"]["bodyMode"] = "literalUtf8"
    errors = verify(v2_fixture, TEST_ONLY_SPEC)
    assert not any("literalUtf8" in error for error in errors)
