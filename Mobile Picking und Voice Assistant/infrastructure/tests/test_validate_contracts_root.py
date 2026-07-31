"""The v1 half of the gate must follow --registry, like the v2 half does.

Whole-branch review finding: commit 4b5a4b0 ("verify the registry the run
actually imports") closed only the v2 half. `validate_contracts()` took no
arguments and always walked the repo's n8n/workflows, so with REGISTRY_PATH
pointed elsewhere -- which import-workflows.sh supports via env -- an alternate
registry's v1 entries were contract-checked against the REPO's same-named
bytes, i.e. against files the run would never import.
"""

import json
from pathlib import Path

from infrastructure.scripts.workflow_verifier import (
    WORKFLOW_ROOT,
    extract_workflow_contracts,
    validate_contracts,
)

# validate_quality_alert_live_path() rejects exactly this node in exactly this
# file name: the production quality flow may not still contain the shadow-AI
# node. It is a v1-only check and needs no webhook wiring to fire.
SHADOW_NODE = "Execute Shadow AI Evaluation"
QUALITY_FILE = "quality-alert-created.json"


def _write_alternate_root(tmp_path: Path) -> Path:
    root = tmp_path / "n8n" / "workflows"
    root.mkdir(parents=True)
    (root / QUALITY_FILE).write_text(
        json.dumps(
            {
                "name": "Quality Alert Created (alternate registry)",
                "nodes": [{"name": SHADOW_NODE, "type": "n8n-nodes-base.noOp"}],
                "connections": {},
            }
        ),
        encoding="utf-8",
    )
    return root


def test_the_repo_root_is_still_the_default(tmp_path):
    """No caller loses its behaviour: without an argument the repo's own
    workflow root is walked, and the repo passes."""
    repo_files = {Path(item.file).name for item in extract_workflow_contracts()[0]}
    disk_files = {item.name for item in WORKFLOW_ROOT.glob("*.json")}
    assert repo_files == disk_files

    errors, _warnings, _summary = validate_contracts()
    assert errors == []


def test_v1_checks_read_the_alternate_roots_bytes(tmp_path):
    """The alternate root's quality flow is the violating one; the repo's
    same-named file is clean. Reporting the violation proves the v1 checks
    parsed the alternate registry's bytes and not the repo's."""
    alternate = _write_alternate_root(tmp_path)

    contracts, parse_errors = extract_workflow_contracts(alternate)
    assert parse_errors == []
    assert [item.path for item in contracts] == [alternate / QUALITY_FILE]
    # No repo-relative form exists for a root outside the repo, so the label
    # degrades to the bare file name instead of raising.
    assert [item.file for item in contracts] == [QUALITY_FILE]

    alternate_errors, _warnings, _summary = validate_contracts(alternate)
    assert any(SHADOW_NODE in error for error in alternate_errors), alternate_errors

    repo_errors, _warnings, _summary = validate_contracts()
    assert not any(SHADOW_NODE in error for error in repo_errors)


def test_summary_reports_the_alternate_roots_workflows(tmp_path):
    """The printed summary must describe the files that were checked; a
    summary keyed by the repo's files while another root was verified is the
    same false claim of coverage in a different place."""
    alternate = _write_alternate_root(tmp_path)
    _errors, _warnings, summary = validate_contracts(alternate)
    assert list(summary["workflow_contracts"]) == [QUALITY_FILE]
