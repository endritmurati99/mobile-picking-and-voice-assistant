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
  *"import:workflow"*) op="import" ;;
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
  publish|unpublish|restart|import) exit 0 ;;
  *)
    echo "unhandled fake docker invocation: $args" >&2
    exit 1
    ;;
esac
"""


def _make_secret_dir(tmp_path):
    """A synthetic stand-in for the host's /run/secrets.

    provision-n8n-credentials.sh's host-side check refuses a *missing*
    required secret file, so every harness that lets the script run has to
    provide the required files at the mode/ownership the check demands.
    """
    secret_dir = tmp_path / "secrets"
    secret_dir.mkdir(exist_ok=True)
    for name in (
        "pwr_n8n_native_header",
        "pwr_backend_to_n8n_active_hmac",
        "pwr_n8n_to_backend_active_hmac",
    ):
        secret_file = secret_dir / name
        secret_file.write_text("test-only-placeholder\n", encoding="utf-8")
        secret_file.chmod(0o600)
    return secret_dir


def _secret_env(tmp_path):
    import getpass

    return {
        "PWR_SECRET_DIR": str(_make_secret_dir(tmp_path)),
        "PWR_SECRET_OWNER": getpass.getuser(),
    }


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
    env.update(_secret_env(tmp_path))

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

    # Exact sequence with counts, not just set-membership: a set-membership
    # check ("only these kinds may appear") cannot notice a DUPLICATE of an
    # otherwise-allowed operation -- a second publish, a second
    # credential_verify, an extra healthcheck poll -- since duplicates
    # don't add anything new to the set. Every legitimate call in this
    # scenario happens exactly once, in exactly this order.
    ops = docker_harness["log_ops"]()
    assert ops == ["credential_verify", "healthcheck", "export_all", "publish"], (
        f"expected exactly one credential_verify, healthcheck, export_all, then "
        f"publish, in that order and no more; got {ops}"
    )

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
    # Exact sequence, not just membership, on the activation leg too.
    assert docker_harness["log_ops"]() == ["credential_verify", "healthcheck", "export_all", "publish"]
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
    # Exact sequence, not just membership, on the activation leg too.
    assert docker_harness["log_ops"]() == ["credential_verify", "healthcheck", "export_all", "publish"]

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


# ---------------------------------------------------------------------------
# Importer harness: drives `import-workflows.sh import` end to end against a
# synthetic registry that -- unlike every workflow in the real registry --
# actually has a credential binding. That gap is why finding #13 survived:
# the importer's `credential_index` rows were never once fed to
# stage_workflow.py with a nonempty binding list, in a test or in production.
#
# Everything below runs the REAL shell script. The only stand-ins are the
# external processes it shells out to: `docker` (the fake above) and a
# transparent `python` wrapper that tees the staging payload to a file
# before exec'ing the real interpreter. The script itself, stage_workflow.py,
# workflow_registry.py and provision-n8n-credentials.sh are all the genuine
# articles.
# ---------------------------------------------------------------------------

# Tees the JSON payload that import-workflows.sh pipes into
# `stage_workflow.py stage` and then execs the real interpreter with the
# untouched stdin. It reimplements nothing: it observes the wire, so a test
# can assert on the exact bytes crossing between the two halves.
PYTHON_TEE_SHIM = r"""#!/usr/bin/env bash
set -euo pipefail
if [[ "$*" == *"stage_workflow.py stage" ]]; then
  payload="$(mktemp "${TMPDIR:-/tmp}/stage-payload.XXXXXX")"
  cat >"$payload"
  cat "$payload" >>"$STAGE_PAYLOAD_LOG"
  printf '\n' >>"$STAGE_PAYLOAD_LOG"
  exec "$REAL_PYTHON" "$@" <"$payload"
fi
exec "$REAL_PYTHON" "$@"
"""

ERROR_TRIGGER_FILE = "error-trigger.json"
BOUND_WORKFLOW_FILE = "smoke-test.json"
BOUND_WORKFLOW_NAME = "Foundation Smoke Test"
BOUND_NODE_NAME = "PWR Webhook"

# The exact operation set a successful `import` legitimately performs:
# credential verification (twice: the verify gate and the metadata read),
# the healthcheck poll, the state exports, one import per managed workflow,
# and the closing "keep everything inactive" unpublish sweep.
IMPORTER_ALLOWED_OPS = "credential_verify,healthcheck,export_all,import,unpublish"


@pytest.fixture
def tmp_registry(tmp_path):
    registry_dir = tmp_path / "registry"
    workflows_dir = registry_dir / "workflows"
    workflows_dir.mkdir(parents=True)

    registry_path = registry_dir / "workflow-registry.json"
    registry_path.write_text(
        json.dumps({
            "schema_version": "v1",
            "credentials": {"pwr.v2.inbound-header": {"type": "httpHeaderAuth"}},
            "workflows": [
                {
                    "file": ERROR_TRIGGER_FILE,
                    "name": "PWR Error Trigger",
                    "generation": "v1",
                    "event_names": [],
                    "webhook_paths": [],
                    "callback_paths": [],
                    "authentication": "error_trigger_v1",
                    "managed": True,
                    "production_activation": False,
                    "test_only": False,
                    "activation_order": 1,
                    "allowed_target_hosts": [],
                    "credential_bindings": [],
                },
                {
                    "file": BOUND_WORKFLOW_FILE,
                    "name": BOUND_WORKFLOW_NAME,
                    "generation": "v2",
                    "event_names": [],
                    "webhook_paths": [],
                    "callback_paths": [],
                    "authentication": "native_header_hmac",
                    "managed": True,
                    "production_activation": False,
                    "test_only": True,
                    "activation_order": 2,
                    "allowed_target_hosts": [],
                    "credential_bindings": [
                        {
                            "node": BOUND_NODE_NAME,
                            "credential_type": "httpHeaderAuth",
                            "logical_name": "pwr.v2.inbound-header",
                        }
                    ],
                },
            ],
        }),
        encoding="utf-8",
    )
    (workflows_dir / ERROR_TRIGGER_FILE).write_text(
        json.dumps({"name": "PWR Error Trigger", "nodes": [], "connections": {}}),
        encoding="utf-8",
    )
    (workflows_dir / BOUND_WORKFLOW_FILE).write_text(
        json.dumps({
            "name": BOUND_WORKFLOW_NAME,
            "nodes": [{"name": BOUND_NODE_NAME, "type": "n8n-nodes-base.webhook"}],
            "connections": {},
        }),
        encoding="utf-8",
    )

    backup_dir = tmp_path / "import-backup"
    backup_dir.mkdir()
    (backup_dir / "original-state.json").write_text(
        json.dumps({
            "workflows": {
                ERROR_TRIGGER_FILE: {
                    "name": "PWR Error Trigger", "id": None, "active": False, "exists": False,
                },
                BOUND_WORKFLOW_FILE: {
                    "name": BOUND_WORKFLOW_NAME, "id": None, "active": False, "exists": False,
                },
            },
            "duplicates": {},
        }),
        encoding="utf-8",
    )

    return {
        "registry_path": registry_path,
        "workflows_dir": workflows_dir,
        "backup_dir": backup_dir,
    }


@pytest.fixture
def mocked_docker(tmp_path, tmp_registry):
    import os
    import stat
    import subprocess
    import sys

    state_dir = tmp_path / "importer-docker-state"
    state_dir.mkdir()
    (state_dir / "export-all.json").write_text(
        json.dumps({
            "data": [
                {"id": "wf-error-1", "name": "PWR Error Trigger", "active": False},
                {"id": "wf-smoke-1", "name": BOUND_WORKFLOW_NAME, "active": False},
            ]
        }),
        encoding="utf-8",
    )
    (state_dir / "credential-metadata.json").write_text(
        json.dumps({"credentials": []}), encoding="utf-8"
    )

    bin_dir = tmp_path / "importer-bin"
    bin_dir.mkdir()
    for name, body in (("docker", FAKE_DOCKER_SCRIPT), ("python", PYTHON_TEE_SHIM)):
        stub = bin_dir / name
        stub.write_text(body, encoding="utf-8")
        stub.chmod(stub.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)

    docker_log = tmp_path / "importer-docker.log"
    docker_log.write_text("", encoding="utf-8")
    payload_log = tmp_path / "stage-payloads.jsonl"
    payload_log.write_text("", encoding="utf-8")

    env = dict(os.environ)
    env["PATH"] = f"{bin_dir}:{env.get('PATH', '')}"
    env["REGISTRY_PATH"] = str(tmp_registry["registry_path"])
    env["WORKFLOW_DIR"] = str(tmp_registry["workflows_dir"])
    env["COMPOSE_FILE"] = str(tmp_path / "unused-compose.yml")
    env["DOCKER_MOCK_LOG"] = str(docker_log)
    env["DOCKER_MOCK_STATE_DIR"] = str(state_dir)
    env["STAGE_PAYLOAD_LOG"] = str(payload_log)
    env["REAL_PYTHON"] = sys.executable
    secret_env = _secret_env(tmp_path)
    env.update(secret_env)

    def run(*args, allowed_ops=IMPORTER_ALLOWED_OPS):
        script = ROOT / "infrastructure/scripts/import-workflows.sh"
        call_env = dict(env)
        call_env["DOCKER_MOCK_ALLOWED_OPS"] = allowed_ops
        return subprocess.run(
            ["bash", str(script), *args],
            env=call_env, cwd=str(ROOT), capture_output=True, text=True, timeout=120,
        )

    def stage_payloads():
        return [
            json.loads(line)
            for line in payload_log.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]

    return {
        "run": run,
        "state_dir": state_dir,
        "secret_dir": Path(secret_env["PWR_SECRET_DIR"]),
        "stage_payloads": stage_payloads,
        "log_ops": lambda: [
            line.split("|", 1)[0]
            for line in docker_log.read_text(encoding="utf-8").splitlines()
            if line
        ],
    }


def _run_importer(mocked_docker, tmp_registry, *, credentials, cli_stdout=""):
    """Run the real `import-workflows.sh import` with the given credential
    metadata coming back from the (faked) n8n CLI inside the container."""
    metadata = {"credentials": credentials}
    if cli_stdout:
        # Injected into the n8n CLI's *stdout*, which is where a real
        # credential export would carry secret-shaped material.
        metadata["cli_noise"] = cli_stdout
    (mocked_docker["state_dir"] / "credential-metadata.json").write_text(
        json.dumps(metadata), encoding="utf-8"
    )
    return mocked_docker["run"]("import", str(tmp_registry["backup_dir"]))


def _run_importer_and_capture_stage_payload(mocked_docker, tmp_registry, *, credentials):
    """Run the importer and return the payload it actually piped into
    `stage_workflow.py stage` for the credential-bound workflow."""
    _run_importer(mocked_docker, tmp_registry, credentials=credentials)
    payloads = [
        payload
        for payload in mocked_docker["stage_payloads"]()
        if payload["source"].get("name") == BOUND_WORKFLOW_NAME
    ]
    assert payloads, "the importer never staged the credential-bound workflow"
    return payloads[-1]


def test_importer_emits_the_wire_format_the_stager_reads(mocked_docker, tmp_registry):
    """The importer emitted "credential" (one object); the stager reads
    "credentials" (a list). Every real binding resolved to zero candidates.
    Regression cover for finding #13."""
    payload = _run_importer_and_capture_stage_payload(
        mocked_docker,
        tmp_registry,
        credentials=[{"id": "id-1", "name": "pwr.v2.inbound-header", "type": "httpHeaderAuth"}],
    )

    rows = payload["credential_index"]
    assert rows, "a workflow with a binding must produce at least one row"
    for row in rows:
        assert set(row) == {"logical_name", "credential_type", "credentials"}
        assert isinstance(row["credentials"], list)


def test_exactly_one_matching_credential_imports_successfully(mocked_docker, tmp_registry):
    result = _run_importer(
        mocked_docker,
        tmp_registry,
        credentials=[{"id": "id-1", "name": "pwr.v2.inbound-header", "type": "httpHeaderAuth"}],
    )
    assert result.returncode == 0, result.stderr

    # The exact operation sequence a real `import` performs. It is asserted
    # here mainly as proof that these tests drive the ACTUAL shell script:
    # this order is a property of import_workflows() in the .sh (verify
    # credentials, wait for health, re-read the credential metadata, import
    # the error workflow, re-export, import the rest, re-export, then the
    # closing "stay inactive" sweep), and no Python stand-in produces it.
    assert mocked_docker["log_ops"]() == [
        "credential_verify", "healthcheck", "credential_verify",
        "import", "export_all", "import", "export_all",
        "unpublish", "unpublish",
    ]


def test_zero_matching_credentials_fails_closed(mocked_docker, tmp_registry):
    result = _run_importer(mocked_docker, tmp_registry, credentials=[])
    assert result.returncode != 0
    assert "credential" in result.stderr.lower()


def test_two_matching_credentials_fail_closed(mocked_docker, tmp_registry):
    result = _run_importer(
        mocked_docker,
        tmp_registry,
        credentials=[
            {"id": "id-1", "name": "pwr.v2.inbound-header", "type": "httpHeaderAuth"},
            {"id": "id-2", "name": "pwr.v2.inbound-header", "type": "httpHeaderAuth"},
        ],
    )
    assert result.returncode != 0
    assert "duplicate" in result.stderr.lower() or "exactly one" in result.stderr.lower()


def test_no_cli_output_is_embedded_in_the_error(mocked_docker, tmp_registry):
    """n8n CLI stdout can carry secrets. It must never reach a raised error."""
    result = _run_importer(
        mocked_docker, tmp_registry, credentials=[], cli_stdout="SECRET-VALUE-abc123"
    )
    assert "SECRET-VALUE-abc123" not in result.stderr
    assert "SECRET-VALUE-abc123" not in result.stdout


# ---------------------------------------------------------------------------
# Host-side secret check (provision-n8n-credentials.sh). It runs on paths in
# the HOST namespace, while the files are actually read at identically named
# paths INSIDE the container -- so it is an early convenience check, not the
# security boundary (that one lives in provision-credentials.mjs, immediately
# before the read). What it must not do is stay silent: a missing required
# secret used to return 0, which is how a misconfigured host reached docker
# at all.
# ---------------------------------------------------------------------------


def test_missing_required_secret_stops_before_any_docker_call(mocked_docker, tmp_registry):
    (mocked_docker["secret_dir"] / "pwr_n8n_native_header").unlink()
    result = _run_importer(
        mocked_docker,
        tmp_registry,
        credentials=[{"id": "id-1", "name": "pwr.v2.inbound-header", "type": "httpHeaderAuth"}],
    )
    assert result.returncode != 0
    assert "pwr_n8n_native_header" in result.stderr
    assert mocked_docker["log_ops"]() == [], (
        "a missing required secret must be refused before anything reaches docker"
    )


def test_group_readable_secret_stops_before_any_docker_call(mocked_docker, tmp_registry):
    (mocked_docker["secret_dir"] / "pwr_backend_to_n8n_active_hmac").chmod(0o640)
    result = _run_importer(
        mocked_docker,
        tmp_registry,
        credentials=[{"id": "id-1", "name": "pwr.v2.inbound-header", "type": "httpHeaderAuth"}],
    )
    assert result.returncode != 0
    assert "pwr_backend_to_n8n_active_hmac" in result.stderr
    assert mocked_docker["log_ops"]() == []


def test_optional_previous_hmac_secret_may_be_absent(mocked_docker, tmp_registry):
    # The previous-HMAC secret only exists during a rotation. Requiring it
    # unconditionally would break every ordinary run, so its absence must
    # stay legal -- the mode/owner rules still apply once it does exist.
    assert not (mocked_docker["secret_dir"] / "pwr_backend_to_n8n_previous_hmac").exists()
    result = _run_importer(
        mocked_docker,
        tmp_registry,
        credentials=[{"id": "id-1", "name": "pwr.v2.inbound-header", "type": "httpHeaderAuth"}],
    )
    assert result.returncode == 0, result.stderr
