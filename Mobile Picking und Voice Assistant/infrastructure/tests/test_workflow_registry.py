import json
from pathlib import Path

import pytest

from infrastructure.scripts.workflow_registry import load_registry

ROOT = Path(__file__).resolve().parents[2]


def test_repository_registry_has_every_workflow_once():
    registry = load_registry(ROOT / "n8n/workflow-registry.json")
    disk = {path.name for path in (ROOT / "n8n/workflows").glob("*.json")}
    assert {item.file for item in registry.workflows} == disk
    assert registry.managed_files() == (
        "error-trigger.json",
        "voice-exception-query.json",
        "quality-alert-created.json",
        "shortage-reported.json",
    )


def test_duplicate_path_and_unknown_credential_fail(tmp_path):
    source = json.loads((ROOT / "n8n/workflow-registry.json").read_text())
    source["workflows"][1]["webhook_paths"] = source["workflows"][0]["webhook_paths"]
    source["workflows"][1]["credential_bindings"] = [
        {
            "node": "Gate",
            "credential_type": "pwrInboundHmac",
            "logical_name": "missing.logical.name",
        }
    ]
    path = tmp_path / "registry.json"
    path.write_text(json.dumps(source), encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate webhook path|unknown logical credential"):
        load_registry(path, workflow_root=ROOT / "n8n/workflows")


def test_v2_requires_native_header_and_hmac_gate(tmp_path):
    source = json.loads((ROOT / "n8n/workflow-registry.json").read_text())
    source["workflows"][0]["generation"] = "v2"
    source["workflows"][0]["authentication"] = "legacy_v1"
    path = tmp_path / "registry.json"
    path.write_text(json.dumps(source), encoding="utf-8")
    with pytest.raises(ValueError, match="native_header_hmac"):
        load_registry(path, workflow_root=ROOT / "n8n/workflows")
