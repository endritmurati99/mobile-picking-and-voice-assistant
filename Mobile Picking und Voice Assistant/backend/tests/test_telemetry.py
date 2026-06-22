from app.utils.telemetry import summarize_serial_events


def test_summarize_serial_events_computes_rates_and_latency():
    events = [
        {"success": True, "serial_recorded": True, "latency_ms": 100},
        {"success": True, "serial_recorded": False, "latency_ms": 200},
        {"success": False, "serial_recorded": False, "latency_ms": 300},
    ]
    s = summarize_serial_events(events)
    assert s["count"] == 3
    assert round(s["success_rate"], 2) == 0.67
    assert round(s["serial_capture_rate"], 2) == 0.33
    assert s["latency_p50_ms"] == 200
    assert s["latency_p95_ms"] == 300
