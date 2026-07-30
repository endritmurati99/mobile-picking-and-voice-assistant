import json

import pytest

from app.services.workflow_targets import load_event_targets


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


def test_grandfathered_v1_entries_are_still_skipped_without_error(tmp_path):
    """v1 entries legitimately have no v2 target; they must not raise."""
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
    drift even before the two lists' contents diverge."""
    import app.services.workflow_targets as workflow_targets
    from infrastructure.scripts.workflow_registry import (
        KNOWN_GENERATIONS as registry_known_generations,
    )

    assert workflow_targets.KNOWN_GENERATIONS is registry_known_generations
