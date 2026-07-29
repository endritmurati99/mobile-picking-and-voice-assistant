import json
from pathlib import Path

import pytest

from infrastructure.scripts.workflow_registry import load_registry

ROOT = Path(__file__).resolve().parents[2]
REAL_REGISTRY_PATH = ROOT / "n8n" / "workflow-registry.json"


def _registry_document(*, generation="v2", file=None):
    """Build a registry document from the real registry, with the first
    workflow entry's generation (and optionally file) overridden.

    Reusing the real document -- rather than a hand-rolled minimal one --
    keeps every other field (credentials, other workflows) realistic, so
    these tests exercise the same shape load_registry sees in production.
    """
    source = json.loads(REAL_REGISTRY_PATH.read_text(encoding="utf-8"))
    target = source["workflows"][0]
    target["generation"] = generation
    if file is not None:
        target["file"] = file
    return source


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


def test_duplicate_webhook_path_fails(tmp_path):
    source = json.loads((ROOT / "n8n/workflow-registry.json").read_text())
    source["workflows"][1]["webhook_paths"] = source["workflows"][0]["webhook_paths"]
    path = tmp_path / "registry.json"
    path.write_text(json.dumps(source), encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate webhook path"):
        load_registry(path, workflow_root=ROOT / "n8n/workflows")


def test_unknown_logical_credential_fails(tmp_path):
    source = json.loads((ROOT / "n8n/workflow-registry.json").read_text())
    source["workflows"][1]["credential_bindings"] = [
        {
            "node": "Gate",
            "credential_type": "pwrInboundHmac",
            "logical_name": "missing.logical.name",
        }
    ]
    path = tmp_path / "registry.json"
    path.write_text(json.dumps(source), encoding="utf-8")
    with pytest.raises(ValueError, match="unknown logical credential"):
        load_registry(path, workflow_root=ROOT / "n8n/workflows")


def test_test_only_invariant_enforced(tmp_path):
    source = json.loads((ROOT / "n8n/workflow-registry.json").read_text())
    source["workflows"][0]["generation"] = "v2"
    source["workflows"][0]["authentication"] = "native_header_hmac"
    source["workflows"][0]["managed"] = True
    source["workflows"][0]["production_activation"] = True
    source["workflows"][0]["test_only"] = True
    path = tmp_path / "registry.json"
    path.write_text(json.dumps(source), encoding="utf-8")
    with pytest.raises(ValueError, match="test_only requires managed non-production v2"):
        load_registry(path, workflow_root=ROOT / "n8n/workflows")


def test_v2_requires_native_header_and_hmac_gate(tmp_path):
    source = json.loads((ROOT / "n8n/workflow-registry.json").read_text())
    source["workflows"][0]["generation"] = "v2"
    source["workflows"][0]["authentication"] = "legacy_v1"
    path = tmp_path / "registry.json"
    path.write_text(json.dumps(source), encoding="utf-8")
    with pytest.raises(ValueError, match="native_header_hmac"):
        load_registry(path, workflow_root=ROOT / "n8n/workflows")


@pytest.mark.parametrize("generation", ["v2-typo", "V2", "v3", "", "v2 ", " v2"])
def test_unknown_generation_is_rejected(tmp_path, generation):
    """An unknown generation silently skipped every v2 check.
    Regression cover for finding #12."""
    registry = tmp_path / "workflow-registry.json"
    registry.write_text(
        json.dumps(_registry_document(generation=generation)), encoding="utf-8"
    )
    with pytest.raises(ValueError, match="generation"):
        load_registry(registry)


def test_a_new_v1_entry_is_rejected(tmp_path):
    """v1 is frozen: the listed legacy files may stay, nothing may join them."""
    registry = tmp_path / "workflow-registry.json"
    registry.write_text(
        json.dumps(_registry_document(generation="v1", file="brand-new.json")),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="grandfather"):
        load_registry(registry)


def test_the_grandfathered_v1_files_still_load(tmp_path):
    from workflow_registry import GRANDFATHERED_V1_FILES

    assert GRANDFATHERED_V1_FILES, "the existing v1 workflows must be listed explicitly"
    registry = tmp_path / "workflow-registry.json"
    registry.write_text(
        json.dumps(
            _registry_document(generation="v1", file=sorted(GRANDFATHERED_V1_FILES)[0])
        ),
        encoding="utf-8",
    )
    assert load_registry(registry).workflows


def test_the_real_registry_still_loads():
    """The grandfather list must actually match what is on disk."""
    load_registry(REAL_REGISTRY_PATH)
