import json

import pytest

from infrastructure.scripts.stage_workflow import stage_workflow


def test_injects_ids_only_into_staged_copy(tmp_path):
    source = {
        "name": "PWR Smoke",
        "nodes": [
            {"name": "Webhook", "type": "n8n-nodes-base.webhook", "credentials": {}},
            {"name": "Signature Gate", "type": "n8n-nodes-pwr.pwrSignatureGate"},
        ],
        "active": True,
    }
    bindings = [
        {
            "node": "Webhook",
            "credential_type": "httpHeaderAuth",
            "logical_name": "pwr.v2.inbound-header",
        }
    ]
    staged = stage_workflow(
        source,
        bindings=bindings,
        credential_index={
            ("pwr.v2.inbound-header", "httpHeaderAuth"): {
                "id": "credential-id",
                "name": "pwr.v2.inbound-header",
                "type": "httpHeaderAuth",
            }
        },
        existing_workflow_id="workflow-id",
        error_workflow_id=None,
    )
    assert staged["active"] is False
    assert staged["id"] == "workflow-id"
    assert staged["nodes"][0]["credentials"]["httpHeaderAuth"] == {
        "id": "credential-id",
        "name": "pwr.v2.inbound-header",
    }
    assert source["active"] is True
    assert source["nodes"][0]["credentials"] == {}


def test_missing_credential_fails_closed():
    with pytest.raises(ValueError, match="exactly one credential"):
        stage_workflow(
            {"name": "x", "nodes": [{"name": "Webhook"}]},
            bindings=[{
                "node": "Webhook",
                "credential_type": "httpHeaderAuth",
                "logical_name": "pwr.v2.inbound-header",
            }],
            credential_index={},
            existing_workflow_id=None,
            error_workflow_id=None,
        )


def test_duplicate_credential_fails_closed():
    # A duplicate match is represented upstream as more than one candidate
    # for the same (logical_name, credential_type) key; the credential index
    # passed into stage_workflow is expected to already be resolved to at
    # most one entry per key, so a duplicate must fail exactly like a
    # missing credential -- fail closed, never guess which one to use.
    with pytest.raises(ValueError, match="exactly one credential"):
        stage_workflow(
            {"name": "x", "nodes": [{"name": "Webhook"}]},
            bindings=[{
                "node": "Webhook",
                "credential_type": "httpHeaderAuth",
                "logical_name": "pwr.v2.inbound-header",
            }],
            credential_index={
                ("pwr.v2.inbound-header", "httpHeaderAuth"): None,
            },
            existing_workflow_id=None,
            error_workflow_id=None,
        )


def test_missing_node_raises_clear_error():
    with pytest.raises(ValueError, match="credential node not found"):
        stage_workflow(
            {"name": "x", "nodes": [{"name": "Other"}]},
            bindings=[{
                "node": "Webhook",
                "credential_type": "httpHeaderAuth",
                "logical_name": "pwr.v2.inbound-header",
            }],
            credential_index={},
            existing_workflow_id=None,
            error_workflow_id=None,
        )


def test_error_workflow_id_is_set_when_provided():
    staged = stage_workflow(
        {"name": "x", "nodes": []},
        bindings=[],
        credential_index={},
        existing_workflow_id=None,
        error_workflow_id="error-wf-id",
    )
    assert staged["settings"]["errorWorkflow"] == "error-wf-id"


def test_generates_id_when_none_exists():
    staged = stage_workflow(
        {"name": "x", "nodes": []},
        bindings=[],
        credential_index={},
        existing_workflow_id=None,
        error_workflow_id=None,
    )
    assert staged["id"]
