"""Tests for the activation guards import-workflows.sh relies on.

These exercise the pure, Docker-free guard functions in
infrastructure.scripts.stage_workflow that back the shell script's
`activate`, `activate-test`, and `deactivate-test` modes. The shell script
itself is only checked for syntax here (`bash -n`) -- it drives a live n8n
container via docker compose, which this test suite must not touch.
"""
import json
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


# ---------------------------------------------------------------------------
# Mocked-command harness: runs the real import-workflows.sh end to end for
# activate-test / deactivate-test, with a fake `docker` on PATH that records
# every invocation instead of touching anything real. This is the only way
# to prove the *wiring* is correct (that verification really happens before
# a publish call reaches "docker", that a file/RUN_ID mismatch really stops
# before any unpublish call) -- the pure guard-function tests above prove
# the guards behave correctly in isolation, but not that the shell script
# actually calls them in the right order before touching docker.
# ---------------------------------------------------------------------------

FAKE_DOCKER_SCRIPT = r"""#!/usr/bin/env bash
# Every invocation is classified into an operation kind, logged as
# "kind|full argv" (so tests can assert on the *kind*, not fragile
# substring matching on the whole command line), and then checked against
# DOCKER_MOCK_ALLOWED_OPS -- a comma-separated allowlist the test sets for
# the exact scenario under test. Any operation kind not on that allowlist
# is a hard failure (not merely unlogged), so an unauthorized or duplicate
# operation on a success path aborts the run instead of silently passing.
set -euo pipefail
args="$*"
case "$args" in
  *"unpublish:workflow"*) op="unpublish" ;;
  *"publish:workflow"*) op="publish" ;;
  *"sh -lc"*"wget -qO-"*) op="healthcheck" ;;
  *"sh -lc"*"export:workflow --all"*) op="export_all" ;;
  *"node "*"verify"*) op="credential_verify" ;;
  *"restart n8n"*) op="restart" ;;
  *) op="unknown" ;;
esac
echo "$op|$args" >> "$DOCKER_MOCK_LOG"

allowed=",${DOCKER_MOCK_ALLOWED_OPS:-},"
if [[ "$allowed" != *",$op,"* ]]; then
  echo "FORBIDDEN fake docker op '$op' (allowed: ${DOCKER_MOCK_ALLOWED_OPS:-<none>}): $args" >&2
  exit 1
fi

case "$op" in
  healthcheck) exit 0 ;;
  export_all) cat "$DOCKER_MOCK_STATE_DIR/export-all.json" ;;
  credential_verify) cat "$DOCKER_MOCK_STATE_DIR/credential-metadata.json" ;;
  publish|unpublish|restart) exit 0 ;;
  *)
    echo "unhandled fake docker invocation: $args" >&2
    exit 1
    ;;
esac
"""


@pytest.fixture
def docker_harness(tmp_path):
    """Builds a temp registry with one test_only workflow, a fake `docker`
    on PATH, and the environment import-workflows.sh needs to run against
    them instead of the real repo/registry/live stack.
    """
    import os
    import stat
    import subprocess

    registry_dir = tmp_path / "registry"
    workflows_dir = registry_dir / "workflows"
    workflows_dir.mkdir(parents=True)
    registry_path = registry_dir / "workflow-registry.json"
    registry_path.write_text(
        json.dumps({
            "schema_version": "v1",
            "credentials": {},
            "workflows": [
                {
                    "file": "smoke-test.json",
                    "name": "Foundation Smoke Test",
                    "generation": "v2",
                    "event_names": [],
                    "webhook_paths": [],
                    "callback_paths": [],
                    "authentication": "native_header_hmac",
                    "managed": True,
                    "production_activation": False,
                    "test_only": True,
                    "activation_order": None,
                    "allowed_target_hosts": [],
                    "credential_bindings": [],
                }
            ],
        }),
        encoding="utf-8",
    )
    (workflows_dir / "smoke-test.json").write_text(
        json.dumps({"name": "Foundation Smoke Test", "nodes": [], "connections": {}}),
        encoding="utf-8",
    )

    state_dir = tmp_path / "docker-state"
    state_dir.mkdir()
    (state_dir / "export-all.json").write_text(
        json.dumps({
            "data": [
                {"id": "wf-smoke-1", "name": "Foundation Smoke Test", "active": False},
            ]
        }),
        encoding="utf-8",
    )
    (state_dir / "credential-metadata.json").write_text(
        json.dumps({"credentials": []}), encoding="utf-8"
    )

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    docker_stub = bin_dir / "docker"
    docker_stub.write_text(FAKE_DOCKER_SCRIPT, encoding="utf-8")
    docker_stub.chmod(docker_stub.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)

    docker_log = tmp_path / "docker-invocations.log"
    docker_log.write_text("", encoding="utf-8")

    backup_dir = tmp_path / "backup"
    backup_dir.mkdir()

    env = dict(os.environ)
    env["PATH"] = f"{bin_dir}:{env.get('PATH', '')}"
    env["REGISTRY_PATH"] = str(registry_path)
    env["WORKFLOW_DIR"] = str(workflows_dir)
    env["COMPOSE_FILE"] = str(tmp_path / "unused-compose.yml")
    env["DOCKER_MOCK_LOG"] = str(docker_log)
    env["DOCKER_MOCK_STATE_DIR"] = str(state_dir)

    def run(*args, allowed_ops=""):
        # allowed_ops is the exact, explicit set of docker operation kinds
        # legitimate for THIS call in THIS scenario (e.g.
        # "credential_verify,healthcheck,export_all,publish"). Anything
        # else the script tries to do through "docker" is a hard failure,
        # not silently accepted -- this is what lets the assertions below
        # check the forbidden set, not only the expected one.
        script = ROOT / "infrastructure/scripts/import-workflows.sh"
        call_env = dict(env)
        call_env["DOCKER_MOCK_ALLOWED_OPS"] = allowed_ops
        return subprocess.run(
            ["bash", str(script), *args],
            env=call_env, cwd=str(ROOT), capture_output=True, text=True, timeout=30,
        )

    def log_lines():
        return [
            line for line in docker_log.read_text(encoding="utf-8").splitlines() if line
        ]

    def log_ops():
        return [line.split("|", 1)[0] for line in log_lines()]

    return {
        "run": run,
        "log_lines": log_lines,
        "log_ops": log_ops,
        "backup_dir": backup_dir,
    }


# The exact, explicit operation set legitimate for a successful
# activate-test call: credential verification, the healthcheck poll, one
# state export, and exactly one publish. Nothing else -- in particular
# neither "unpublish" nor "restart" -- may ever appear on this path.
ACTIVATE_TEST_ALLOWED_OPS = "credential_verify,healthcheck,export_all,publish"


def test_activate_test_verifies_before_publishing(docker_harness):
    result = docker_harness["run"](
        "activate-test", str(docker_harness["backup_dir"]), "smoke-test.json", "run-harness-1",
        allowed_ops=ACTIVATE_TEST_ALLOWED_OPS,
    )
    assert result.returncode == 0, result.stderr

    ops = docker_harness["log_ops"]()
    assert ops.index("credential_verify") < ops.index("publish"), (
        "credential verification must be logged before any publish call"
    )
    # The forbidden set for this scenario: only the four allowed kinds may
    # ever appear, never unpublish/restart/unknown.
    assert set(ops) <= {"credential_verify", "healthcheck", "export_all", "publish"}
    assert "unpublish" not in ops and "restart" not in ops

    manifest_file = docker_harness["backup_dir"] / "activate-test-run-harness-1.json"
    assert manifest_file.exists()
    manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    assert manifest["file"] == "smoke-test.json"
    assert manifest["run_id"] == "run-harness-1"
    assert manifest["workflow_id"] == "wf-smoke-1"


def test_activate_test_refuses_unregistered_file_without_touching_docker(docker_harness):
    # allowed_ops="" (nothing at all): if the script tried any docker
    # operation here, the fake docker itself would hard-fail it, backstopping
    # the assertion that the log stays completely empty.
    result = docker_harness["run"](
        "activate-test", str(docker_harness["backup_dir"]), "not-a-real-workflow.json", "run-harness-2",
        allowed_ops="",
    )
    assert result.returncode != 0
    assert docker_harness["log_lines"]() == []


def test_deactivate_test_restores_and_removes_manifest(docker_harness):
    activate_result = docker_harness["run"](
        "activate-test", str(docker_harness["backup_dir"]), "smoke-test.json", "run-harness-3",
        allowed_ops=ACTIVATE_TEST_ALLOWED_OPS,
    )
    assert activate_result.returncode == 0, activate_result.stderr
    ops_after_activate = len(docker_harness["log_ops"]())

    # previous_active was False, so exactly one "unpublish" is legitimate
    # here -- nothing else. In particular no re-verification and no
    # "publish" (that would mean it restored to the wrong state).
    deactivate_result = docker_harness["run"](
        "deactivate-test", str(docker_harness["backup_dir"]), "smoke-test.json", "run-harness-3",
        allowed_ops="unpublish",
    )
    assert deactivate_result.returncode == 0, deactivate_result.stderr

    manifest_file = docker_harness["backup_dir"] / "activate-test-run-harness-3.json"
    assert not manifest_file.exists(), "manifest must be removed after a successful deactivate-test"

    new_ops = docker_harness["log_ops"]()[ops_after_activate:]
    assert new_ops == ["unpublish"], (
        f"deactivate-test must do exactly one unpublish and nothing else, got {new_ops}"
    )


def test_deactivate_test_refuses_mismatched_file_without_touching_docker(docker_harness):
    activate_result = docker_harness["run"](
        "activate-test", str(docker_harness["backup_dir"]), "smoke-test.json", "run-harness-4",
        allowed_ops=ACTIVATE_TEST_ALLOWED_OPS,
    )
    assert activate_result.returncode == 0, activate_result.stderr

    before_lines = len(docker_harness["log_lines"]())

    # allowed_ops="": a file/RUN_ID mismatch must be refused before ANY
    # docker call -- publish, unpublish, or otherwise. If the script tried
    # one anyway, the fake docker would hard-fail it.
    deactivate_result = docker_harness["run"](
        "deactivate-test", str(docker_harness["backup_dir"]), "a-different-file.json", "run-harness-4",
        allowed_ops="",
    )
    assert deactivate_result.returncode != 0

    manifest_file = docker_harness["backup_dir"] / "activate-test-run-harness-4.json"
    assert manifest_file.exists(), "a refused deactivate-test must not consume the manifest"

    after_lines = docker_harness["log_lines"]()
    assert len(after_lines) == before_lines, (
        "a file-name mismatch must be refused before any further docker call "
        "(no extra publish/unpublish invocation)"
    )
