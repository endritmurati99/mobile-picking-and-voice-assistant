import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from app.services.workflow_targets import load_event_targets

BACKEND_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_DIR.parent


def write_registry(tmp_path, workflows, schema_version="v1"):
    path = tmp_path / "workflow-registry.json"
    path.write_text(
        json.dumps({"schema_version": schema_version, "workflows": workflows}),
        encoding="utf-8",
    )
    return path


def v2_workflow(**overrides):
    workflow = {
        "file": "quality-assessment-v2.json",
        "name": "Quality Assessment v2",
        "generation": "v2",
        "event_names": ["quality.assessment.requested.v1"],
        "webhook_paths": ["quality-assessment-v2"],
    }
    workflow.update(overrides)
    return workflow


def test_frozen_quality_v2_event_maps_to_its_exact_webhook_path(tmp_path):
    path = write_registry(
        tmp_path,
        [
            v2_workflow(),
            # v1 legacy entries never contribute v2 targets
            {
                "file": "pick-confirmed.json",
                "generation": "v1",
                "event_names": ["pick-confirmed"],
                "webhook_paths": ["pick-confirmed"],
            },
        ],
    )
    assert load_event_targets(path) == {
        "quality.assessment.requested.v1": "/webhook/quality-assessment-v2"
    }


def test_registered_event_without_v2_workflow_simply_has_no_target(tmp_path):
    path = write_registry(tmp_path, [])
    assert load_event_targets(path) == {}


def test_duplicate_v2_event_names_fail_closed(tmp_path):
    path = write_registry(
        tmp_path,
        [
            v2_workflow(),
            v2_workflow(
                file="quality-assessment-v2-copy.json",
                webhook_paths=["quality-assessment-v2-copy"],
            ),
        ],
    )
    with pytest.raises(ValueError, match="duplicate"):
        load_event_targets(path)


def test_v2_workflow_must_declare_exactly_one_webhook_path(tmp_path):
    for paths in ([], ["a", "b"]):
        path = write_registry(tmp_path, [v2_workflow(webhook_paths=paths)])
        with pytest.raises(ValueError, match="one webhook path"):
            load_event_targets(path)


def test_unknown_event_name_fails_closed(tmp_path):
    path = write_registry(
        tmp_path,
        [v2_workflow(event_names=["not.a.registered.event.v1"])],
    )
    with pytest.raises(ValueError, match="unknown v2 event target"):
        load_event_targets(path)


def test_unsupported_registry_schema_fails_closed(tmp_path):
    path = write_registry(tmp_path, [v2_workflow()], schema_version="v2")
    with pytest.raises(ValueError, match="unsupported workflow registry"):
        load_event_targets(path)


def test_webhook_path_charset_is_allowlisted(tmp_path):
    for bad in ("../admin", "a/b", "x?y=1", "UPPER", "", "a b", "x#f"):
        path = write_registry(tmp_path, [v2_workflow(webhook_paths=[bad])])
        with pytest.raises(ValueError, match="webhook path"):
            load_event_targets(path)


def test_real_repository_registry_is_loadable(tmp_path):
    """The sole reviewed registry must always parse; today it contains no v2
    workflow, so the target map is empty until Task 15 lands one."""
    from pathlib import Path

    repo_registry = (
        Path(__file__).resolve().parents[2] / "n8n" / "workflow-registry.json"
    )
    targets = load_event_targets(repo_registry)
    assert isinstance(targets, dict)


def test_unknown_generation_is_rejected_rather_than_skipped(tmp_path):
    """The silent skip is finding #12 in a second reader of the same file."""
    registry = tmp_path / "workflow-registry.json"
    registry.write_text(
        json.dumps(
            {
                "schema_version": "v1",
                "workflows": [
                    {
                        "file": "x.json",
                        "generation": "v2-typo",
                        "webhook_paths": ["pwr-v2-smoke"],
                        "event_names": ["pwr.v2.smoke"],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="generation"):
        load_event_targets(registry)


def test_v1_entries_contribute_no_target_and_do_not_raise(tmp_path):
    """A `generation: "v1"` entry is a known generation with no v2 target, so
    it is skipped without error. This reader never consults
    GRANDFATHERED_V1_FILES -- only `load_registry` enforces that list -- so the
    file name below is incidental, not what is being proved."""
    registry = tmp_path / "workflow-registry.json"
    registry.write_text(
        json.dumps(
            {
                "schema_version": "v1",
                "workflows": [
                    {"file": "pick-confirmed.json", "generation": "v1", "webhook_paths": []}
                ],
            }
        ),
        encoding="utf-8",
    )
    assert load_event_targets(registry) == {}


def test_known_generations_is_imported_not_copied():
    """Step 3 of the brief: the allowlist must be one shared declaration, not
    a value independently retyped in this module. If a future edit replaces
    the import with a locally copied tuple, this identity check catches the
    drift even before the two lists' contents diverge.

    The repo root is put on sys.path HERE, by the test, and deliberately not by
    the module under test: `workflow_targets` must not reach outside `backend/`
    (see test_workflow_targets_imports_with_only_backend_importable)."""
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))

    import app.services.workflow_targets as workflow_targets
    from infrastructure.scripts.workflow_registry import (
        KNOWN_GENERATIONS as registry_known_generations,
    )

    assert workflow_targets.KNOWN_GENERATIONS is registry_known_generations


def test_workflow_targets_imports_with_only_backend_importable(tmp_path):
    """`app.dependencies` imports load_event_targets at module scope and
    `app.main` imports `app.dependencies` at module scope, so if this module
    cannot import, `uvicorn app.main:app` never serves a request.

    The backend image contains ONLY the app package (`backend/Dockerfile`:
    `COPY app/ ./app/`; compose mounts only `./backend/app:/app/app:ro`).
    This reproduces that layout -- a copy of `app/` under an otherwise empty
    root, with no `infrastructure/` anywhere and neither the repo root nor the
    real `backend/` importable -- and imports the module in a child
    interpreter. Passing inside the repo tree proves nothing: there,
    `parents[3]` of this module happens to be the repo root, so an
    `infrastructure.*` import resolves by accident of the checkout layout.
    """
    shutil.copytree(
        BACKEND_DIR / "app",
        tmp_path / "app",
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )
    assert not (tmp_path / "infrastructure").exists()

    # Keep only interpreter/third-party entries: drop the repo root, the real
    # backend dir, and anything that would make `infrastructure` importable.
    child_path = [
        entry
        for entry in sys.path
        if entry
        and Path(entry).resolve() not in {REPO_ROOT, BACKEND_DIR}
        and not (Path(entry) / "infrastructure").is_dir()
    ]
    env = {**os.environ, "PYTHONPATH": os.pathsep.join(child_path)}

    # cwd is tmp_path, so `python -c` puts exactly the staged root on sys.path[0].
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import app.services.workflow_targets as m; "
            "assert m.load_event_targets; print('imported')",
        ],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        "app.services.workflow_targets must import with only the app package "
        f"available:\n{result.stderr}"
    )
    assert "imported" in result.stdout
