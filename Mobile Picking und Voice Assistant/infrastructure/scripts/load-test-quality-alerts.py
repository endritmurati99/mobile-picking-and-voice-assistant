#!/usr/bin/env python3
"""
Load-Test: 100 Quality-Alert-Requests gegen den laufenden Stack.

Feuert N POST-Requests an /api/quality-alerts (multipart form-data),
wartet auf n8n-Callback-Verarbeitung und prueft den ai_evaluation_status
jedes erstellten Alerts in der Odoo-DB.

Aufruf:
    python infrastructure/scripts/load-test-quality-alerts.py
    python infrastructure/scripts/load-test-quality-alerts.py --count 50 --concurrency 5
    python infrastructure/scripts/load-test-quality-alerts.py --base-url https://localhost --verify-ssl
"""
from __future__ import annotations

import argparse
import asyncio
import json
import random
import statistics
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

try:
    import httpx
except ImportError:
    sys.exit("httpx fehlt. Installiere mit: pip install httpx")

# ── Test descriptions (mix of severity levels) ──────────────────

DESCRIPTIONS = [
    # Scrap-level
    "Totalschaden am Gehaeuse, komplett zerstoert",
    "Artikel gebrochen, Bruch nicht reparierbar",
    # Quarantine-level
    "Artikel defekt, Funktion eingeschraenkt",
    "Verpackung feucht, Inhalt moeglicherweise betroffen",
    "Rost an der Unterseite sichtbar",
    "Fremdkoerper in der Verpackung gefunden",
    # Rework-level
    "Kleiner Kratzer auf der Verpackung",
    "Etikett schief aufgeklebt, Nacharbeit noetig",
    "Leichte Delle am Deckel",
    # Sellable-level
    "Ware sieht gut aus, alles in Ordnung",
]

PRIORITIES = ["0", "0", "0", "1"]  # 75% normal, 25% urgent


@dataclass
class RequestResult:
    index: int
    idempotency_key: str
    description: str
    priority: str
    http_status: int = 0
    alert_id: int | None = None
    alert_name: str | None = None
    ai_status: str | None = None
    ai_disposition: str | None = None
    ai_confidence: float | None = None
    latency_ms: int = 0
    error: str | None = None


@dataclass
class LoadTestReport:
    timestamp: str = ""
    count: int = 0
    concurrency: int = 0
    base_url: str = ""
    total_duration_s: float = 0
    results: list[dict] = field(default_factory=list)
    summary: dict = field(default_factory=dict)


async def send_alert(
    client: httpx.AsyncClient,
    semaphore: asyncio.Semaphore,
    index: int,
    base_url: str,
    picker_user_id: int,
    picking_id: int,
    product_id: int,
    location_id: int,
) -> RequestResult:
    desc = random.choice(DESCRIPTIONS)
    prio = random.choice(PRIORITIES)
    key = f"loadtest-{uuid4().hex[:12]}"

    result = RequestResult(
        index=index,
        idempotency_key=key,
        description=desc,
        priority=prio,
    )

    async with semaphore:
        t0 = time.monotonic()
        try:
            resp = await client.post(
                f"{base_url}/api/quality-alerts",
                headers={
                    "X-Picker-User-Id": str(picker_user_id),
                    "X-Device-Id": f"loadtest-{index}",
                    "Idempotency-Key": key,
                },
                data={
                    "description": desc,
                    "picking_id": str(picking_id),
                    "product_id": str(product_id),
                    "location_id": str(location_id),
                    "priority": prio,
                },
                timeout=30.0,
            )
            result.http_status = resp.status_code
            result.latency_ms = int((time.monotonic() - t0) * 1000)

            if resp.status_code == 200:
                body = resp.json()
                result.alert_id = body.get("alert_id")
                result.alert_name = body.get("name")
            else:
                result.error = resp.text[:200]
        except Exception as exc:
            result.latency_ms = int((time.monotonic() - t0) * 1000)
            result.error = str(exc)[:200]

    return result


def query_alert_statuses(alert_ids: list[int], db_container: str, db_name: str) -> dict[int, dict]:
    """Query ai_evaluation_status for each alert via psql in the DB container."""
    if not alert_ids:
        return {}

    ids_csv = ",".join(str(i) for i in alert_ids)
    sql = (
        f"SELECT id, ai_evaluation_status, ai_disposition, ai_confidence "
        f"FROM quality_alert_custom WHERE id IN ({ids_csv});"
    )

    try:
        out = subprocess.check_output(
            [
                "docker", "exec", db_container,
                "psql", "-U", "odoo", "-d", db_name, "-t", "-A", "-F", "|", "-c", sql,
            ],
            text=True,
            timeout=15,
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        print(f"  [WARN] DB-Abfrage fehlgeschlagen: {exc}")
        return {}

    statuses = {}
    for line in out.strip().splitlines():
        parts = line.split("|")
        if len(parts) >= 2:
            aid = int(parts[0])
            statuses[aid] = {
                "ai_evaluation_status": parts[1] if len(parts) > 1 else None,
                "ai_disposition": parts[2] if len(parts) > 2 else None,
                "ai_confidence": float(parts[3]) if len(parts) > 3 and parts[3] else None,
            }
    return statuses


async def run_load_test(args: argparse.Namespace) -> LoadTestReport:
    report = LoadTestReport(
        timestamp=datetime.now(timezone.utc).isoformat(),
        count=args.count,
        concurrency=args.concurrency,
        base_url=args.base_url,
    )

    semaphore = asyncio.Semaphore(args.concurrency)
    verify = args.verify_ssl

    print(f"\n{'='*60}")
    print(f"  Load-Test: {args.count} Quality-Alert-Requests")
    print(f"  Concurrency: {args.concurrency}")
    print(f"  Target: {args.base_url}")
    print(f"{'='*60}\n")

    t_start = time.monotonic()

    async with httpx.AsyncClient(verify=verify) as client:
        tasks = [
            send_alert(
                client, semaphore, i,
                args.base_url,
                args.picker_user_id,
                args.picking_id,
                args.product_id,
                args.location_id,
            )
            for i in range(args.count)
        ]
        results: list[RequestResult] = await asyncio.gather(*tasks)

    fire_duration = time.monotonic() - t_start
    print(f"  Alle {args.count} Requests gesendet in {fire_duration:.1f}s")

    # Wait for n8n callbacks
    wait_s = args.wait_seconds
    print(f"  Warte {wait_s}s auf n8n-Callback-Verarbeitung ...")
    await asyncio.sleep(wait_s)

    # Query Odoo for final status
    alert_ids = [r.alert_id for r in results if r.alert_id]
    print(f"  Pruefe {len(alert_ids)} Alert-Statuses in Odoo ...")
    statuses = query_alert_statuses(alert_ids, args.db_container, args.db_name)

    for r in results:
        if r.alert_id and r.alert_id in statuses:
            s = statuses[r.alert_id]
            r.ai_status = s.get("ai_evaluation_status")
            r.ai_disposition = s.get("ai_disposition")
            r.ai_confidence = s.get("ai_confidence")

    report.total_duration_s = round(time.monotonic() - t_start, 1)

    # Build summary
    http_ok = [r for r in results if r.http_status == 200]
    http_err = [r for r in results if r.http_status != 200]
    completed = [r for r in results if r.ai_status == "completed"]
    pending = [r for r in results if r.ai_status == "pending"]
    failed = [r for r in results if r.ai_status == "failed"]
    no_status = [r for r in results if r.ai_status is None and r.alert_id]

    latencies = [r.latency_ms for r in results if r.latency_ms > 0]

    report.summary = {
        "http_200": len(http_ok),
        "http_error": len(http_err),
        "ai_completed": len(completed),
        "ai_pending": len(pending),
        "ai_failed": len(failed),
        "ai_unknown": len(no_status),
        "latency_avg_ms": round(statistics.mean(latencies)) if latencies else 0,
        "latency_p50_ms": round(statistics.median(latencies)) if latencies else 0,
        "latency_p95_ms": round(sorted(latencies)[int(len(latencies) * 0.95)] if latencies else 0),
        "latency_p99_ms": round(sorted(latencies)[int(len(latencies) * 0.99)] if latencies else 0),
        "latency_max_ms": max(latencies) if latencies else 0,
    }
    report.results = [asdict(r) for r in results]

    # Print report
    print(f"\n{'='*60}")
    print(f"  ERGEBNIS")
    print(f"{'='*60}")
    print(f"  Gesamt-Dauer:       {report.total_duration_s}s")
    print(f"  HTTP 200:           {report.summary['http_200']}/{args.count}")
    print(f"  HTTP Fehler:        {report.summary['http_error']}")
    print(f"  AI completed:       {report.summary['ai_completed']}")
    print(f"  AI pending:         {report.summary['ai_pending']}")
    print(f"  AI failed:          {report.summary['ai_failed']}")
    print(f"  AI unbekannt:       {report.summary['ai_unknown']}")
    print(f"  Latenz Avg:         {report.summary['latency_avg_ms']}ms")
    print(f"  Latenz P50:         {report.summary['latency_p50_ms']}ms")
    print(f"  Latenz P95:         {report.summary['latency_p95_ms']}ms")
    print(f"  Latenz P99:         {report.summary['latency_p99_ms']}ms")
    print(f"  Latenz Max:         {report.summary['latency_max_ms']}ms")
    print(f"{'='*60}")

    if http_err:
        print(f"\n  Erste HTTP-Fehler:")
        for r in http_err[:5]:
            print(f"    [{r.index}] HTTP {r.http_status}: {r.error}")

    # Disposition breakdown
    dispositions: dict[str, int] = {}
    for r in results:
        if r.ai_disposition:
            dispositions[r.ai_disposition] = dispositions.get(r.ai_disposition, 0) + 1
    if dispositions:
        print(f"\n  Disposition-Verteilung:")
        for disp, count in sorted(dispositions.items()):
            print(f"    {disp}: {count}")

    return report


def main():
    parser = argparse.ArgumentParser(description="Load-Test fuer Quality Alerts")
    parser.add_argument("--count", type=int, default=100, help="Anzahl Requests (default: 100)")
    parser.add_argument("--concurrency", type=int, default=10, help="Max parallele Requests (default: 10)")
    parser.add_argument("--base-url", default="https://localhost", help="Backend-URL (default: https://localhost)")
    parser.add_argument("--verify-ssl", action="store_true", help="SSL-Zertifikat pruefen")
    parser.add_argument("--wait-seconds", type=int, default=20, help="Wartezeit fuer n8n-Callbacks (default: 20)")
    parser.add_argument("--picker-user-id", type=int, default=7, help="Picker User ID (default: 7)")
    parser.add_argument("--picking-id", type=int, default=337, help="Picking ID (default: 337)")
    parser.add_argument("--product-id", type=int, default=144, help="Product ID (default: 144)")
    parser.add_argument("--location-id", type=int, default=301, help="Location ID (default: 301)")
    parser.add_argument("--db-container", default="mobilepickingundvoiceassistant-db-1", help="DB-Container")
    parser.add_argument("--db-name", default="masterfischer", help="Odoo DB-Name")
    parser.add_argument("--output", default=None, help="JSON-Output-Datei")
    args = parser.parse_args()

    report = asyncio.run(run_load_test(args))

    # Save JSON report
    output_path = args.output or str(
        Path(__file__).parent / "load-test-results.json"
    )
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(asdict(report), f, indent=2, ensure_ascii=False, default=str)
    print(f"\n  Report gespeichert: {output_path}\n")


if __name__ == "__main__":
    main()
