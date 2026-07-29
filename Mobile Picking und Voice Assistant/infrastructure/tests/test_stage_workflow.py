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
            ("pwr.v2.inbound-header", "httpHeaderAuth"): [{
                "id": "credential-id",
                "name": "pwr.v2.inbound-header",
                "type": "httpHeaderAuth",
            }]
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
    # A real duplicate: two distinct candidates were found upstream for the
    # exact same (logical_name, credential_type) key. stage_workflow must
    # refuse this exactly like a missing credential -- fail closed, never
    # guess which one to use. This drives the actual "more than one
    # candidate" branch, not a stand-in sentinel value.
    with pytest.raises(ValueError, match="exactly one credential"):
        stage_workflow(
            {"name": "x", "nodes": [{"name": "Webhook"}]},
            bindings=[{
                "node": "Webhook",
                "credential_type": "httpHeaderAuth",
                "logical_name": "pwr.v2.inbound-header",
            }],
            credential_index={
                ("pwr.v2.inbound-header", "httpHeaderAuth"): [
                    {"id": "candidate-a", "name": "pwr.v2.inbound-header"},
                    {"id": "candidate-b", "name": "pwr.v2.inbound-header"},
                ],
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


# ---------------------------------------------------------------------------
# CLI-level wire-format cover. The tests above exercise the pure function,
# which never sees the JSON rows; these pin the *contract* the stage
# subcommand parses -- the half of the seam that import-workflows.sh writes.
# ---------------------------------------------------------------------------

import subprocess
import sys
from pathlib import Path

STAGE_PY = Path(__file__).resolve().parents[1] / "scripts" / "stage_workflow.py"

BINDING = {
    "node": "Webhook",
    "credential_type": "httpHeaderAuth",
    "logical_name": "pwr.v2.inbound-header",
}
SOURCE = {"name": "PWR Smoke", "nodes": [{"name": "Webhook"}]}


def _stage_cli(credential_index):
    payload = {
        "source": SOURCE,
        "bindings": [BINDING],
        "credential_index": credential_index,
        "existing_workflow_id": None,
        "error_workflow_id": None,
    }
    return subprocess.run(
        [sys.executable, str(STAGE_PY), "stage"],
        input=json.dumps(payload), capture_output=True, text=True,
    )


def test_stage_cli_accepts_the_row_shape_the_importer_emits():
    result = _stage_cli([
        {
            "logical_name": "pwr.v2.inbound-header",
            "credential_type": "httpHeaderAuth",
            "credentials": [
                {"id": "id-1", "name": "pwr.v2.inbound-header", "type": "httpHeaderAuth"},
            ],
        }
    ])
    assert result.returncode == 0, result.stderr
    staged = json.loads(result.stdout)
    assert staged["nodes"][0]["credentials"]["httpHeaderAuth"] == {
        "id": "id-1",
        "name": "pwr.v2.inbound-header",
    }


def test_stage_cli_rejects_a_row_carrying_two_candidates():
    # A list is the only shape that can even express a duplicate; this is
    # what the "exactly one" check exists to reject.
    result = _stage_cli([
        {
            "logical_name": "pwr.v2.inbound-header",
            "credential_type": "httpHeaderAuth",
            "credentials": [
                {"id": "id-1", "name": "pwr.v2.inbound-header", "type": "httpHeaderAuth"},
                {"id": "id-2", "name": "pwr.v2.inbound-header", "type": "httpHeaderAuth"},
            ],
        }
    ])
    assert result.returncode != 0
    assert "exactly one credential" in result.stderr
    assert result.stdout == ""


def test_stage_cli_rejects_the_old_singular_credential_key():
    # The exact defect: the importer used to emit "credential" holding one
    # object. The stager reads "credentials" (a list), so such a row
    # resolves to ZERO candidates and must fail closed rather than be
    # quietly tolerated by a lenient parser.
    result = _stage_cli([
        {
            "logical_name": "pwr.v2.inbound-header",
            "credential_type": "httpHeaderAuth",
            "credential": {
                "id": "id-1", "name": "pwr.v2.inbound-header", "type": "httpHeaderAuth",
            },
        }
    ])
    assert result.returncode != 0
    assert "found 0" in result.stderr
