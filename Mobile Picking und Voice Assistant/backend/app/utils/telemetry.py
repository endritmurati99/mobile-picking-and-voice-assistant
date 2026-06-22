"""Mess-Auswertung für die Design-Science-Evaluation (Serial-Confirm)."""


def _percentile(sorted_values: list[float], p: float) -> float:
    if not sorted_values:
        return 0.0
    k = max(0, min(len(sorted_values) - 1, round((p / 100) * (len(sorted_values) - 1))))
    return sorted_values[k]


def summarize_serial_events(events: list[dict]) -> dict:
    count = len(events)
    if count == 0:
        return {"count": 0, "success_rate": 0.0, "serial_capture_rate": 0.0,
                "latency_p50_ms": 0, "latency_p95_ms": 0}
    successes = sum(1 for e in events if e.get("success"))
    captures = sum(1 for e in events if e.get("serial_recorded"))
    latencies = sorted(int(e.get("latency_ms", 0)) for e in events)
    return {
        "count": count,
        "success_rate": successes / count,
        "serial_capture_rate": captures / count,
        "latency_p50_ms": int(_percentile(latencies, 50)),
        "latency_p95_ms": int(_percentile(latencies, 95)),
    }
