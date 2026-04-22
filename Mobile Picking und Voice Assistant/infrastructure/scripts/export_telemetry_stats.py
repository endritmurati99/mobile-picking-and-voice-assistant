#!/usr/bin/env python3
"""Export structured n8n callback telemetry from backend logs."""
from __future__ import annotations

import argparse
import csv
import json
import math
import subprocess
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_COMPOSE_FILE = ROOT / "docker-compose.yml"
DEFAULT_ARTIFACT_ROOT = ROOT / "artifacts" / "telemetry"


def _coerce_number(value):
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _extract_json_object(line: str) -> dict | None:
    candidate = line.strip()
    if not candidate:
        return None

    json_start = candidate.find("{")
    if json_start < 0:
        return None

    try:
        payload = json.loads(candidate[json_start:])
    except json.JSONDecodeError:
        return None

    return payload if isinstance(payload, dict) else None


def extract_callback_events(lines: Iterable[str]) -> list[dict]:
    events: list[dict] = []
    for line in lines:
        payload = _extract_json_object(line)
        if not payload:
            continue
        if not {"workflow_name", "callback_type", "callback_status"} <= payload.keys():
            continue
        events.append(payload)
    return events


def _percentile(values: list[float], percentile: float) -> int | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return int(round(ordered[0]))

    rank = (len(ordered) - 1) * percentile
    lower = math.floor(rank)
    upper = math.ceil(rank)
    if lower == upper:
        return int(round(ordered[lower]))

    weight = rank - lower
    interpolated = ordered[lower] + (ordered[upper] - ordered[lower]) * weight
    return int(round(interpolated))


def _metric_values(events: list[dict], field_name: str) -> list[float]:
    values: list[float] = []
    for event in events:
        latency_tracking = event.get("latency_tracking") or {}
        stages = latency_tracking.get("stages") or {}
        if field_name == "total_duration_ms":
            value = latency_tracking.get("total_duration_ms")
        else:
            value = stages.get(field_name)
        numeric = _coerce_number(value)
        if numeric is not None:
            values.append(numeric)
    return values


def query_quality_alert_statuses(alert_ids: list[int], db_container: str, db_name: str) -> list[dict]:
    if not alert_ids:
        return []

    ids_csv = ",".join(str(alert_id) for alert_id in sorted(set(alert_ids)))
    sql = (
        "SELECT id, ai_evaluation_status, ai_disposition, ai_confidence "
        f"FROM quality_alert_custom WHERE id IN ({ids_csv});"
    )

    try:
        output = subprocess.check_output(
            [
                "docker",
                "exec",
                db_container,
                "psql",
                "-U",
                "odoo",
                "-d",
                db_name,
                "-t",
                "-A",
                "-F",
                "|",
                "-c",
                sql,
            ],
            text=True,
            timeout=20,
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError(f"DB-Abfrage fuer Quality Alerts fehlgeschlagen: {exc}") from exc

    rows: list[dict] = []
    for line in output.strip().splitlines():
        parts = line.split("|")
        if not parts or not parts[0]:
            continue
        rows.append(
            {
                "alert_id": int(parts[0]),
                "ai_evaluation_status": parts[1] if len(parts) > 1 else None,
                "ai_disposition": parts[2] if len(parts) > 2 else None,
                "ai_confidence": float(parts[3]) if len(parts) > 3 and parts[3] else None,
            }
        )
    return rows


def build_summary(
    events: list[dict],
    quality_status_rows: list[dict] | None = None,
    quality_alert_ids: list[int] | None = None,
) -> dict:
    by_workflow: dict[str, dict] = defaultdict(lambda: {"success": 0, "error": 0, "replay": 0, "total": 0})
    idempotency_counts: Counter[tuple[str, str]] = Counter()

    for event in events:
        workflow_name = str(event.get("workflow_name") or "unknown")
        callback_status = str(event.get("callback_status") or "unknown")
        by_workflow[workflow_name]["total"] += 1
        if callback_status == "applied":
            by_workflow[workflow_name]["success"] += 1
        elif callback_status == "replay":
            by_workflow[workflow_name]["replay"] += 1
        else:
            by_workflow[workflow_name]["error"] += 1

        idempotency_key = event.get("idempotency_key")
        if isinstance(idempotency_key, str) and idempotency_key:
            idempotency_counts[(workflow_name, idempotency_key)] += 1

    duplicates = sum(count - 1 for count in idempotency_counts.values() if count > 1)
    total_values = _metric_values(events, "total_duration_ms")
    heuristic_values = _metric_values(events, "heuristic_ms")
    callback_values = _metric_values(events, "callback_ms")

    quality_completeness = None
    if quality_status_rows is not None:
        rows_by_id = {int(row["alert_id"]): row for row in quality_status_rows if row.get("alert_id") is not None}
        evaluated_ids = sorted(set(quality_alert_ids or rows_by_id.keys()))
        complete = 0
        for alert_id in evaluated_ids:
            row = rows_by_id.get(alert_id)
            if not row:
                continue
            if (
                row.get("ai_evaluation_status") == "completed"
                and row.get("ai_disposition")
                and row.get("ai_confidence") is not None
            ):
                complete += 1
        quality_completeness = {
            "evaluated_alerts": len(evaluated_ids),
            "complete_alerts": complete,
            "ratio": round((complete / len(evaluated_ids)), 4) if evaluated_ids else None,
        }

    return {
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "event_count": len(events),
        "workflow_counts": dict(sorted(by_workflow.items())),
        "duplicate_replay_count": duplicates,
        "missing_execution_id_count": sum(1 for event in events if not event.get("execution_id")),
        "legacy_payload_count": sum(1 for event in events if bool(event.get("legacy_payload"))),
        "latency_ms": {
            "total_duration_ms": {"p50": _percentile(total_values, 0.50), "p95": _percentile(total_values, 0.95)},
            "heuristic_ms": {"p50": _percentile(heuristic_values, 0.50), "p95": _percentile(heuristic_values, 0.95)},
            "callback_ms": {"p50": _percentile(callback_values, 0.50), "p95": _percentile(callback_values, 0.95)},
        },
        "quality_incident_completeness": quality_completeness,
    }


def _write_csv(path: Path, fieldnames: list[str], rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def _event_rows(events: list[dict]) -> list[dict]:
    rows: list[dict] = []
    for event in events:
        rows.append(
            {
                "workflow_name": event.get("workflow_name"),
                "callback_type": event.get("callback_type"),
                "callback_status": event.get("callback_status"),
                "correlation_id": event.get("correlation_id"),
                "idempotency_key": event.get("idempotency_key"),
                "execution_id": event.get("execution_id"),
                "schema_version": event.get("schema_version"),
                "legacy_payload": event.get("legacy_payload"),
                "target_object_type": event.get("target_object_type"),
                "target_object_id": event.get("target_object_id"),
                "received_at_backend": event.get("received_at_backend"),
                "latency_tracking": json.dumps(event.get("latency_tracking"), ensure_ascii=False, sort_keys=True),
            }
        )
    return rows


def _read_log_lines(args: argparse.Namespace) -> list[str]:
    if args.log_file:
        return args.log_file.read_text(encoding="utf-8").splitlines()

    cmd = [
        "docker",
        "compose",
        "-f",
        str(args.compose_file),
        "logs",
        "--no-color",
        "--no-log-prefix",
        args.service,
    ]
    if args.since:
        cmd.extend(["--since", args.since])
    if args.until:
        cmd.extend(["--until", args.until])

    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "docker compose logs fehlgeschlagen")
    return result.stdout.splitlines()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Export backend callback telemetry from structured logs.")
    parser.add_argument("--since", help="Zeitfenster fuer docker compose logs, z. B. 30m oder 2026-03-31T10:00:00")
    parser.add_argument("--until", help="Optionales Ende fuer docker compose logs")
    parser.add_argument("--log-file", type=Path, help="Alternativer Log-Dateipfad statt docker compose logs")
    parser.add_argument("--compose-file", type=Path, default=DEFAULT_COMPOSE_FILE)
    parser.add_argument("--service", default="backend")
    parser.add_argument("--db-container", help="Optionaler Docker-Containername fuer Odoo-DB-Abfragen")
    parser.add_argument("--db-name", help="Optionaler Odoo-Datenbankname fuer Quality-Completeness")
    parser.add_argument("--output-dir", type=Path, help="Optionales Zielverzeichnis fuer Artefakte")
    args = parser.parse_args()

    if not args.log_file and not args.since:
        parser.error("Entweder --log-file oder --since muss gesetzt sein.")
    if bool(args.db_container) ^ bool(args.db_name):
        parser.error("--db-container und --db-name muessen zusammen gesetzt werden.")
    return args


def main() -> int:
    args = parse_args()
    lines = _read_log_lines(args)
    events = extract_callback_events(lines)

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    output_dir = args.output_dir or (DEFAULT_ARTIFACT_ROOT / timestamp)
    output_dir.mkdir(parents=True, exist_ok=True)

    quality_status_rows = None
    if args.db_container and args.db_name:
        quality_alert_ids = [
            int(event["target_object_id"])
            for event in events
            if event.get("callback_type") == "quality_assessment" and event.get("target_object_id") is not None
        ]
        quality_status_rows = query_quality_alert_statuses(quality_alert_ids, args.db_container, args.db_name)

    _write_csv(
        output_dir / "callback-events.csv",
        [
            "workflow_name",
            "callback_type",
            "callback_status",
            "correlation_id",
            "idempotency_key",
            "execution_id",
            "schema_version",
            "legacy_payload",
            "target_object_type",
            "target_object_id",
            "received_at_backend",
            "latency_tracking",
        ],
        _event_rows(events),
    )

    if quality_status_rows is not None:
        _write_csv(
            output_dir / "quality-alert-status.csv",
            ["alert_id", "ai_evaluation_status", "ai_disposition", "ai_confidence"],
            quality_status_rows,
        )

    summary = build_summary(events, quality_status_rows, quality_alert_ids if quality_status_rows is not None else None)
    with (output_dir / "summary.json").open("w", encoding="utf-8") as handle:
        json.dump(summary, handle, indent=2, ensure_ascii=False)

    print(f"Telemetry export written to: {output_dir}")
    print(f"  callback-events.csv: {len(events)} event(s)")
    if quality_status_rows is not None:
        print(f"  quality-alert-status.csv: {len(quality_status_rows)} row(s)")
    print("  summary.json: ready")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
