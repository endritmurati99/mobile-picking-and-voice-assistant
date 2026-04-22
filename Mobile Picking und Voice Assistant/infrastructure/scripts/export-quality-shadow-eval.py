#!/usr/bin/env python3
"""Export shadow evaluation logs plus ground truth into CSV/summary outputs."""
from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from pathlib import Path
from statistics import mean, median


VALID_CATEGORIES = {"damage", "shortage", "wrong_item", "unclear"}


def _load_json_line(raw_line: str) -> dict | None:
    line = raw_line.strip()
    if not line:
        return None
    candidate = line[line.find("{") :] if "{" in line else line
    try:
        payload = json.loads(candidate)
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def read_shadow_events(log_files: list[Path]) -> list[dict]:
    events_by_correlation: dict[str, dict] = {}
    for log_file in log_files:
        for raw_line in log_file.read_text(encoding="utf-8").splitlines():
            payload = _load_json_line(raw_line)
            if not payload or payload.get("event_type") != "quality_shadow_evaluation":
                continue
            correlation_id = str(payload.get("correlation_id") or "")
            if not correlation_id:
                continue
            events_by_correlation[correlation_id] = payload
    return list(events_by_correlation.values())


def read_ground_truth(path: Path) -> dict[int, str]:
    labels: dict[int, str] = {}
    if not path.exists():
        return labels
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        payload = _load_json_line(raw_line)
        if not payload:
            continue
        alert_id = payload.get("alert_id")
        true_category = payload.get("true_category")
        if not isinstance(alert_id, int) or true_category not in VALID_CATEGORIES:
            continue
        labels[alert_id] = true_category
    return labels


def join_rows(events: list[dict], truth_map: dict[int, str]) -> list[dict]:
    rows: list[dict] = []
    for event in sorted(events, key=lambda item: (item.get("timestamp") or "", item.get("alert_id") or 0)):
        alert_id = event.get("alert_id")
        true_category = truth_map.get(alert_id) if isinstance(alert_id, int) else None
        heuristic_category = event.get("heuristic_category")
        ai_category = event.get("ai_category")
        row = {
            **event,
            "true_category": true_category,
            "heuristic_correct": (heuristic_category == true_category) if true_category else None,
            "ai_correct": (ai_category == true_category) if true_category else None,
        }
        rows.append(row)
    return rows


def _safe_ratio(numerator: int, denominator: int) -> float | None:
    if denominator <= 0:
        return None
    return round(numerator / denominator, 4)


def summarize(rows: list[dict]) -> dict:
    labeled_rows = [row for row in rows if row.get("true_category")]
    heuristic_hits = sum(1 for row in labeled_rows if row.get("heuristic_correct") is True)
    ai_hits = sum(1 for row in labeled_rows if row.get("ai_correct") is True)
    matches = sum(1 for row in rows if row.get("match") is True)
    latencies = [row["ai_latency_ms"] for row in rows if isinstance(row.get("ai_latency_ms"), (int, float))]
    heuristic_errors = Counter(
        row["true_category"]
        for row in labeled_rows
        if row.get("heuristic_correct") is False
    )
    ai_errors = Counter(
        row["true_category"]
        for row in labeled_rows
        if row.get("ai_correct") is False
    )
    return {
        "total_shadow_evaluations": len(rows),
        "labeled_evaluations": len(labeled_rows),
        "heuristic_accuracy": _safe_ratio(heuristic_hits, len(labeled_rows)),
        "ai_accuracy": _safe_ratio(ai_hits, len(labeled_rows)),
        "heuristic_ai_match_rate": _safe_ratio(matches, len(rows)),
        "ai_latency_ms": {
            "count": len(latencies),
            "mean": round(mean(latencies), 2) if latencies else None,
            "median": round(median(latencies), 2) if latencies else None,
            "max": max(latencies) if latencies else None,
        },
        "heuristic_errors_by_true_category": dict(sorted(heuristic_errors.items())),
        "ai_errors_by_true_category": dict(sorted(ai_errors.items())),
    }


def write_csv(rows: list[dict], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "timestamp",
        "alert_id",
        "correlation_id",
        "true_category",
        "heuristic_category",
        "ai_category",
        "match",
        "heuristic_confidence",
        "ai_confidence",
        "confidence_delta",
        "ai_latency_ms",
        "text_length",
        "has_photo",
        "photo_count",
        "model",
        "heuristic_correct",
        "ai_correct",
        "ai_reason",
        "heuristic_reason",
        "execution_id",
    ]
    with output_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key) for key in fieldnames})


def main() -> int:
    parser = argparse.ArgumentParser(description="Export quality shadow evaluation logs.")
    parser.add_argument(
        "--log-file",
        action="append",
        required=True,
        help="Path to a backend log file containing quality_shadow_evaluation JSON lines. Can be passed multiple times.",
    )
    parser.add_argument(
        "--ground-truth",
        default="evaluation/ground_truth.jsonl",
        help="Path to the ground truth JSONL file.",
    )
    parser.add_argument(
        "--output-csv",
        default="evaluation/exports/quality-shadow-evaluation.csv",
        help="Destination CSV path.",
    )
    parser.add_argument(
        "--summary-json",
        default="evaluation/exports/quality-shadow-summary.json",
        help="Destination summary JSON path.",
    )
    args = parser.parse_args()

    log_files = [Path(path) for path in args.log_file]
    ground_truth_path = Path(args.ground_truth)
    output_csv = Path(args.output_csv)
    summary_json = Path(args.summary_json)

    rows = join_rows(read_shadow_events(log_files), read_ground_truth(ground_truth_path))
    summary = summarize(rows)

    write_csv(rows, output_csv)
    summary_json.parent.mkdir(parents=True, exist_ok=True)
    summary_json.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
