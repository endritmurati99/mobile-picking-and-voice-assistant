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
    # A well-formed event/callback node references event_id, odoo_instance,
    # and at least one delivery/lease/idempotency field.
    v2_fixture["nodes"][2]["parameters"]["deliveryGenerationProperty"] = "delivery_generation"
    v2_fixture["nodes"][2]["parameters"]["idempotencyKeyProperty"] = "idempotency_key"
    v2_fixture["nodes"][2]["parameters"]["eventIdField"] = "event_id"
    v2_fixture["nodes"][2]["parameters"]["odooInstanceField"] = "odoo_instance"
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


def test_v2_rejects_dynamic_target_expression(v2_fixture, verify):
    v2_fixture["nodes"][2]["parameters"]["target"] = "={{ $json.target }}"
    errors = verify(v2_fixture, ARTIFACT_SPEC)
    assert any("dynamic/unresolved" in error for error in errors)


def test_v2_rejects_missing_resolved_host(v2_fixture, verify):
    del v2_fixture["nodes"][2]["parameters"]["host"]
    errors = verify(v2_fixture)
    assert any("no concrete resolved host" in error for error in errors)


def test_v2_rejects_unregistered_resolved_host(v2_fixture, verify):
    v2_fixture["nodes"][2]["parameters"]["host"] = "odoo"
    errors = verify(v2_fixture)
    assert any("is not in" in error and "allowed_target_hosts" in error for error in errors)


def test_v2_rejects_business_node_between_gate_and_acceptance(v2_fixture, verify):
    # A model/carrier/business node spliced in between the Signature Gate's
    # accepted output and the PWR Signed HTTP Request acceptance call: the
    # exact failure mode this verifier exists to prevent. Even though the
    # acceptance call still eventually happens, something else ran first.
    v2_fixture["nodes"].insert(2, {
        "name": "Model Call",
        "type": "n8n-nodes-base.httpRequest",
        "parameters": {"url": "https://api.openai.example/v1/classify"},
    })
    v2_fixture["connections"]["PWR Signature Gate"] = {
        "main": [[{"node": "Model Call", "type": "main", "index": 0}], []]
    }
    v2_fixture["connections"]["Model Call"] = {
        "main": [[{"node": "Acceptance", "type": "main", "index": 0}]]
    }
    errors = verify(v2_fixture, ARTIFACT_SPEC)
    assert any("run before acceptance" in error for error in errors)


def test_v2_rejects_event_node_missing_required_fields(v2_fixture, verify):
    v2_fixture["nodes"][2]["parameters"]["target"] = "/api/internal/n8n/v2/artifacts/evt-123/status"
    # Deliberately omit event_id/odoo_instance/delivery-lease-idempotency
    # references.
    errors = verify(v2_fixture, ARTIFACT_SPEC)
    assert any("is missing required fields" in error for error in errors)
    assert any("event_id" in error for error in errors)
    assert any("odoo_instance" in error for error in errors)


def test_v2_rejects_quality_image_analysis_from_photo_count_alone(v2_fixture, verify):
    v2_fixture["name"] = "Quality Alert v2"
    quality_spec = {**SPEC, "file": "quality-alert-v2.json"}
    v2_fixture["nodes"].append({
        "name": "Assess Alert",
        "type": "n8n-nodes-base.code",
        "parameters": {
            "jsCode": "const image_analysis = photo_count > 0 ? 'damaged' : 'ok'; return image_analysis;",
        },
    })
    errors = verify(v2_fixture, quality_spec)
    assert any("image analysis" in error and "photo_count" in error for error in errors)


def test_v2_accepts_quality_image_analysis_with_real_evidence(v2_fixture, verify):
    v2_fixture["name"] = "Quality Alert v2"
    quality_spec = {**SPEC, "file": "quality-alert-v2.json"}
    v2_fixture["nodes"].append({
        "name": "Assess Alert",
        "type": "n8n-nodes-base.code",
        "parameters": {
            "jsCode": (
                "const image_analysis = classifyImage(item.binary.photo, photo_count);"
                " return image_analysis;"
            ),
        },
    })
    errors = verify(v2_fixture, quality_spec)
    assert not any("image analysis" in error for error in errors)


def test_v2_rejects_base64_content_in_code_node_item_json(v2_fixture, verify):
    v2_fixture["nodes"].append({
        "name": "Edit Fields",
        "type": "n8n-nodes-base.set",
        "parameters": {
            "fields": {
                "values": [
                    {"name": "artifact_data", "value": "aGVsbG8gd29ybGQgYmFzZTY0IGRhdGE="},
                ]
            }
        },
    })
    errors = verify(v2_fixture)
    assert any("artifact or base64" in error for error in errors)
