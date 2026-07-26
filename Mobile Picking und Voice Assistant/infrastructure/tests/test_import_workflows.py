"""Tests for the activation guards import-workflows.sh relies on.

These exercise the pure, Docker-free guard functions in
infrastructure.scripts.stage_workflow that back the shell script's
`activate`, `activate-test`, and `deactivate-test` modes. The shell script
itself is only checked for syntax here (`bash -n`) -- it drives a live n8n
container via docker compose, which this test suite must not touch.
"""
from pathlib import Path

import pytest

from infrastructure.scripts.stage_workflow import (
    ActivationError,
    assert_activatable,
    assert_test_activatable,
    build_restoration_manifest,
    restore_from_manifest,
)
from infrastructure.scripts.workflow_registry import load_registry

ROOT = Path(__file__).resolve().parents[2]

# A synthetic stand-in for the Task 15 "Foundation smoke" workflow: a
# managed, non-production, test_only v2 workflow. It does not exist in the
# registry yet (Task 15 lands it), but the guard must already refuse it via
# the ordinary `activate` mode regardless of which workflow it is applied to.
FOUNDATION_SMOKE_SPEC = {
    "file": "foundation-smoke.json",
    "managed": True,
    "production_activation": False,
    "test_only": True,
    "generation": "v2",
}


def test_activate_rejects_the_foundation_smoke_workflow():
    with pytest.raises(ActivationError, match="production_activation is false"):
        assert_activatable(
            FOUNDATION_SMOKE_SPEC,
            credentials_verified=True,
            duplicate=False,
        )


def test_activate_rejects_unverified_credentials():
    spec = {"file": "shortage-reported.json", "production_activation": True}
    with pytest.raises(ActivationError, match="credentials are not verified"):
        assert_activatable(spec, credentials_verified=False, duplicate=False)


def test_activate_rejects_duplicate_workflow_name():
    spec = {"file": "shortage-reported.json", "production_activation": True}
    with pytest.raises(ActivationError, match="duplicate workflow name"):
        assert_activatable(spec, credentials_verified=True, duplicate=True)


def test_activate_test_rejects_every_registered_non_test_only_workflow():
    registry = load_registry(ROOT / "n8n/workflow-registry.json")
    for workflow in registry.workflows:
        spec = {
            "file": workflow.file,
            "production_activation": workflow.production_activation,
            "test_only": workflow.test_only,
        }
        with pytest.raises(ActivationError):
            assert_test_activatable(spec, run_id="run-1234", dependency_files=set())


def test_activate_test_requires_nonempty_run_id():
    with pytest.raises(ActivationError, match="RUN_ID"):
        assert_test_activatable(
            FOUNDATION_SMOKE_SPEC, run_id="", dependency_files=set()
        )


def test_activate_test_refuses_a_dependency_workflow():
    with pytest.raises(ActivationError, match="dependency workflow"):
        assert_test_activatable(
            FOUNDATION_SMOKE_SPEC,
            run_id="run-1234",
            dependency_files={"foundation-smoke.json"},
        )


def test_activate_test_accepts_a_valid_test_only_workflow():
    # Should not raise.
    assert_test_activatable(
        FOUNDATION_SMOKE_SPEC, run_id="run-1234", dependency_files=set()
    )


def test_activate_deactivate_test_pair_restores_exact_previous_state():
    manifest = build_restoration_manifest(
        file_name="foundation-smoke.json",
        run_id="run-5678",
        workflow_id="wf-1",
        previous_active=False,
    )
    restored_active = restore_from_manifest(manifest, run_id="run-5678")
    assert restored_active is False

    manifest_active = build_restoration_manifest(
        file_name="foundation-smoke.json",
        run_id="run-9999",
        workflow_id="wf-1",
        previous_active=True,
    )
    restored_active_true = restore_from_manifest(manifest_active, run_id="run-9999")
    assert restored_active_true is True


def test_deactivate_test_refuses_mismatched_run_id():
    manifest = build_restoration_manifest(
        file_name="foundation-smoke.json",
        run_id="run-original",
        workflow_id="wf-1",
        previous_active=False,
    )
    with pytest.raises(ActivationError, match="run_id"):
        restore_from_manifest(manifest, run_id="run-different")


def test_deactivate_test_refuses_empty_run_id():
    manifest = build_restoration_manifest(
        file_name="foundation-smoke.json",
        run_id="run-original",
        workflow_id="wf-1",
        previous_active=False,
    )
    with pytest.raises(ActivationError, match="run_id"):
        restore_from_manifest(manifest, run_id="")


def test_import_workflows_script_has_valid_syntax():
    import subprocess

    script = ROOT / "infrastructure/scripts/import-workflows.sh"
    result = subprocess.run(["bash", "-n", str(script)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
