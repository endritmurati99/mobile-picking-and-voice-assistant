from __future__ import annotations

import importlib.util
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[2] / "infrastructure" / "scripts" / "export_telemetry_stats.py"
SPEC = importlib.util.spec_from_file_location("export_telemetry_stats", SCRIPT_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


def test_extract_callback_events_filters_non_callback_json():
    lines = [
        'backend-1  | {"workflow_name":"quality-alert-created","callback_type":"quality_assessment","callback_status":"applied"}',
        'backend-1  | {"message":"plain app log"}',
        "not json at all",
    ]

    events = MODULE.extract_callback_events(lines)

    assert len(events) == 1
    assert events[0]["workflow_name"] == "quality-alert-created"


def test_build_summary_counts_duplicates_and_latency_percentiles():
    events = [
        {
            "workflow_name": "quality-alert-created",
            "callback_type": "quality_assessment",
            "callback_status": "applied",
            "idempotency_key": "corr-1",
            "execution_id": "exec-1",
            "legacy_payload": False,
            "latency_tracking": {
                "total_duration_ms": 100,
                "stages": {"heuristic_ms": 20, "callback_ms": 5},
            },
        },
        {
            "workflow_name": "quality-alert-created",
            "callback_type": "quality_assessment",
            "callback_status": "replay",
            "idempotency_key": "corr-1",
            "execution_id": "exec-2",
            "legacy_payload": False,
            "latency_tracking": {
                "total_duration_ms": 220,
                "stages": {"heuristic_ms": 40, "callback_ms": 8},
            },
        },
        {
            "workflow_name": "shortage-reported",
            "callback_type": "replenishment_action",
            "callback_status": "failed",
            "idempotency_key": "corr-2",
            "execution_id": None,
            "legacy_payload": True,
            "latency_tracking": {
                "total_duration_ms": 300,
                "stages": {"heuristic_ms": 15, "callback_ms": 12},
            },
        },
    ]

    summary = MODULE.build_summary(events)

    assert summary["event_count"] == 3
    assert summary["duplicate_replay_count"] == 1
    assert summary["missing_execution_id_count"] == 1
    assert summary["legacy_payload_count"] == 1
    assert summary["workflow_counts"]["quality-alert-created"]["success"] == 1
    assert summary["workflow_counts"]["quality-alert-created"]["replay"] == 1
    assert summary["workflow_counts"]["shortage-reported"]["error"] == 1
    assert summary["latency_ms"]["total_duration_ms"]["p50"] == 220
    assert summary["latency_ms"]["callback_ms"]["p95"] == 12


def test_build_summary_quality_incident_completeness_uses_status_rows():
    events = [
        {
            "workflow_name": "quality-alert-created",
            "callback_type": "quality_assessment",
            "callback_status": "applied",
            "idempotency_key": "corr-1",
            "execution_id": "exec-1",
            "legacy_payload": False,
            "latency_tracking": {"total_duration_ms": 100, "stages": {"heuristic_ms": 20, "callback_ms": 5}},
        }
    ]
    quality_rows = [
        {"alert_id": 1, "ai_evaluation_status": "completed", "ai_disposition": "scrap", "ai_confidence": 0.92},
        {"alert_id": 2, "ai_evaluation_status": "pending", "ai_disposition": None, "ai_confidence": None},
    ]

    summary = MODULE.build_summary(events, quality_rows)

    completeness = summary["quality_incident_completeness"]
    assert completeness["evaluated_alerts"] == 2
    assert completeness["complete_alerts"] == 1
    assert completeness["ratio"] == 0.5
