# Seriennummer-Bestätigung Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Beim Pick-Bestätigen kann (für serialisierte / hochwertige Güter) eine **Seriennummer** erfasst werden; das Backend schreibt sie nach Odoo, und eine **Retouren-Abgleich-Logik** prüft versendete vs. zurückgesendete Seriennummern — alles **messbar** über Telemetrie.

**Architecture:** Reine Funktionen (Serial-Abgleich, Mess-Aggregation) zuerst und voll getestet, dann der Odoo-schreibende Pfad in `PickingService.confirm_pick_line`, dann Router + PWA-Wiring, zuletzt Odoo-Konfiguration. Odoo bleibt System of Record (Seriennummer = `stock.move.line.lot_name` → Odoo erzeugt `stock.lot`). Die PWA spricht nur mit dem Backend.

**Tech Stack:** Python 3 · FastAPI · httpx (JSON-RPC) · pytest + anyio (AsyncMock) · Vanilla-JS-PWA · Odoo 18 Community (`stock.move.line`, `stock.lot`, `product.product.tracking`).

## Global Constraints

- Odoo ist **System of Record** — keine Schatten-DB; Seriennummer wird in Odoo gespeichert.
- Die PWA spricht **nur** mit FastAPI (`/api/*`), nie direkt mit Odoo.
- **Touch bleibt Fallback** — Seriennummer auch manuell eingebbar, nie einzige Bedienung.
- Odoo-18-Feldnamen: `stock.move.line.quantity` (nicht `qty_done`), `stock.picking.move_ids` (nicht `move_lines`).
- Rückwärtskompatibel: ohne `serial_number` verhält sich `confirm-line` **exakt wie heute**.
- Tests: `pytest` mit `@pytest.mark.anyio`, Odoo/n8n als `AsyncMock` gemockt (kein laufendes Odoo nötig).

---

### Task 1: Serial-Abgleich (reine Funktion) — Retouren-Prüfung

**Files:**
- Create: `backend/app/utils/serial.py`
- Test: `backend/tests/test_serial.py`

**Interfaces:**
- Produces: `reconcile_serials(shipped: list[str], returned: list[str]) -> dict` mit Keys `ok: bool`, `missing: list[str]`, `unknown: list[str]`, `duplicates: list[str]`.

- [ ] **Step 1: Failing test schreiben**

```python
# backend/tests/test_serial.py
from app.utils.serial import reconcile_serials


def test_reconcile_detects_missing_unknown_and_duplicates():
    # Versendet 1,2,3,4 — zurück kommt 1,5,5 (Prof-Beispiel CPU)
    result = reconcile_serials(["1", "2", "3", "4"], ["1", "5", "5"])
    assert result == {
        "ok": False,
        "missing": ["2", "3", "4"],
        "unknown": ["5"],
        "duplicates": ["5"],
    }


def test_reconcile_ok_when_identical():
    result = reconcile_serials(["A1", "A2"], ["A2", "A1"])
    assert result == {"ok": True, "missing": [], "unknown": [], "duplicates": []}
```

- [ ] **Step 2: Test laufen lassen, FAIL bestätigen**

Run: `make test` (oder `python -m pytest backend/tests/test_serial.py -v`)
Expected: FAIL — `ModuleNotFoundError: No module named 'app.utils.serial'`

- [ ] **Step 3: Minimale Implementierung**

```python
# backend/app/utils/serial.py
"""Soll/Ist-Abgleich von Seriennummern (Retouren-Prüfung)."""
from collections import Counter


def reconcile_serials(shipped: list[str], returned: list[str]) -> dict:
    shipped_counter = Counter(s.strip() for s in shipped if s and s.strip())
    returned_counter = Counter(s.strip() for s in returned if s and s.strip())
    missing = sorted(s for s in shipped_counter if returned_counter[s] == 0)
    unknown = sorted(s for s in returned_counter if shipped_counter[s] == 0)
    duplicates = sorted(s for s, c in returned_counter.items() if c > 1)
    ok = not missing and not unknown and not duplicates
    return {"ok": ok, "missing": missing, "unknown": unknown, "duplicates": duplicates}
```

- [ ] **Step 4: Test laufen lassen, PASS bestätigen**

Run: `python -m pytest backend/tests/test_serial.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add backend/app/utils/serial.py backend/tests/test_serial.py
git commit -m "feat(serial): Soll/Ist-Abgleich von Seriennummern (Retouren-Pruefung)"
```

---

### Task 2: Backend — Seriennummer beim Confirm nach Odoo schreiben

**Files:**
- Modify: `backend/app/services/picking_service.py` (Methode `confirm_pick_line`, ab Zeile 570)
- Modify: `backend/app/routers/pickings.py` (`ConfirmLineRequest` + Endpoint `confirm_line`)
- Test: `backend/tests/test_picking_service.py`

**Interfaces:**
- Consumes: `OdooClient.write(model, ids, vals)`, `OdooClient.search_read(model, domain, fields, limit)`.
- Produces: `confirm_pick_line(..., serial_number: str = "")` — schreibt bei serialisierten Produkten `{"lot_name": serial_number}` auf die Move-Line; Response enthält `recorded_serial: str`.

- [ ] **Step 1: Failing test schreiben** (ans bestehende Mock-Muster angelehnt: `odoo = AsyncMock()`)

```python
# backend/tests/test_picking_service.py  (neue Testklasse anhängen)
class TestConfirmPickLineSerial:
    @pytest.mark.anyio
    async def test_writes_lot_name_for_serial_tracked_product(self, service, odoo, n8n):
        async def fake_execute_kw(model, method, args, kwargs=None):
            if model == "stock.move.line" and method == "read":
                return [{"id": 50, "product_id": [5, "[CPU] Xeon"], "quantity": 1,
                         "move_id": [10, "MOVE/10"], "location_id": [1, "WH/Stock/A-1"]}]
            if model == "stock.move" and method == "search_read":
                return [{"id": 10, "picked": True}]
            raise AssertionError(f"unexpected execute_kw {model}.{method}")

        async def fake_search_read(model, domain, fields, limit=100):
            if model == "product.product" and "barcode" in fields:
                return [{"barcode": "CPU-XEON-1"}]
            if model == "product.product" and "tracking" in fields:
                return [{"tracking": "serial"}]
            if model == "stock.quant":
                return [{"quantity": 10, "reserved_quantity": 0, "location_id": [1, "WH/Stock/A-1"]}]
            raise AssertionError(f"unexpected search_read {model} {fields}")

        odoo.execute_kw.side_effect = fake_execute_kw
        odoo.search_read.side_effect = fake_search_read
        odoo.write.return_value = True
        odoo.call_method.return_value = True
        n8n.fire_event.return_value = N8NEventResult(delivered=True, correlation_id="c1", error=None)

        result = await service.confirm_pick_line(
            picking_id=1, move_line_id=50, scanned_barcode="CPU-XEON-1",
            quantity=1, serial_number="SN-0001",
        )

        assert result["success"] is True
        assert result["recorded_serial"] == "SN-0001"
        odoo.write.assert_any_call("stock.move.line", [50], {"lot_name": "SN-0001"})
```

- [ ] **Step 2: Test laufen lassen, FAIL bestätigen**

Run: `python -m pytest backend/tests/test_picking_service.py::TestConfirmPickLineSerial -v`
Expected: FAIL — `TypeError: confirm_pick_line() got an unexpected keyword argument 'serial_number'`

- [ ] **Step 3: `confirm_pick_line` erweitern**

In `backend/app/services/picking_service.py` die Signatur (Zeile 570–577) ergänzen:

```python
    async def confirm_pick_line(
        self,
        picking_id: int,
        move_line_id: int,
        scanned_barcode: str,
        quantity: float,
        picker_identity: PickerIdentity | None = None,
        serial_number: str = "",
    ) -> dict:
```

Direkt **nach** dem Schreiben der Menge (heute Zeile 631 `await self._odoo.write("stock.move.line", [move_line_id], {"quantity": qty})`) einfügen:

```python
        recorded_serial = ""
        serial_clean = (serial_number or "").strip()
        if serial_clean and product_id:
            tracked = await self._odoo.search_read(
                "product.product", [("id", "=", product_id)], ["tracking"]
            )
            tracking = tracked[0].get("tracking") if tracked else None
            if tracking in ("serial", "lot"):
                await self._odoo.write(
                    "stock.move.line", [move_line_id], {"lot_name": serial_clean}
                )
                recorded_serial = serial_clean
```

Im **erfolgreichen Return** (heute Zeile 702–706) `recorded_serial` ergänzen:

```python
        return {
            "success": True,
            "message": "Auftrag abgeschlossen." if picking_complete else "Bestätigt.",
            "picking_complete": picking_complete,
            "recorded_serial": recorded_serial,
        }
```

- [ ] **Step 4: Router erweitern**

In `backend/app/routers/pickings.py` `ConfirmLineRequest` (Zeile 39–42) ergänzen:

```python
class ConfirmLineRequest(BaseModel):
    move_line_id: int
    scanned_barcode: str = ""
    quantity: float = 0
    serial_number: str = ""
```

Im Endpoint `confirm_line` den Aufruf von `service.confirm_pick_line(...)` (im `try`-Block) um `serial_number=body.serial_number` ergänzen.

- [ ] **Step 5: Tests laufen lassen, PASS bestätigen**

Run: `python -m pytest backend/tests/test_picking_service.py -v`
Expected: PASS (alle bestehenden + neuer Test)

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/picking_service.py backend/app/routers/pickings.py backend/tests/test_picking_service.py
git commit -m "feat(serial): Seriennummer beim confirm-line nach Odoo (lot_name) schreiben"
```

---

### Task 3: Messung — Telemetrie-Event + Auswertungs-Funktion

**Files:**
- Create: `backend/app/utils/telemetry.py`
- Modify: `backend/app/services/picking_service.py` (Event in `confirm_pick_line` emittieren)
- Test: `backend/tests/test_telemetry.py`

**Interfaces:**
- Produces: `summarize_serial_events(events: list[dict]) -> dict` mit Keys `count`, `success_rate`, `serial_capture_rate`, `latency_p50_ms`, `latency_p95_ms`.

- [ ] **Step 1: Failing test schreiben**

```python
# backend/tests/test_telemetry.py
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
```

- [ ] **Step 2: Test laufen lassen, FAIL bestätigen**

Run: `python -m pytest backend/tests/test_telemetry.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.utils.telemetry'`

- [ ] **Step 3: Implementierung**

```python
# backend/app/utils/telemetry.py
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
```

- [ ] **Step 4: Event in `confirm_pick_line` emittieren**

Oben in `picking_service.py` ergänzen (falls noch nicht vorhanden): `import json`, `import logging`, `import time`, `logger = logging.getLogger(__name__)`.
Zu Beginn von `confirm_pick_line` `_t0 = time.monotonic()` setzen; direkt **vor** dem erfolgreichen Return:

```python
        logger.info(json.dumps({
            "event_type": "serial_confirm",
            "picking_id": picking_id,
            "move_line_id": move_line_id,
            "product_id": product_id,
            "success": True,
            "serial_recorded": bool(recorded_serial),
            "latency_ms": int((time.monotonic() - _t0) * 1000),
        }, ensure_ascii=False))
```

- [ ] **Step 5: Tests laufen lassen, PASS bestätigen**

Run: `python -m pytest backend/tests/test_telemetry.py backend/tests/test_picking_service.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add backend/app/utils/telemetry.py backend/app/services/picking_service.py backend/tests/test_telemetry.py
git commit -m "feat(measure): serial_confirm-Telemetrie + Auswertungsfunktion"
```

---

### Task 4: Odoo-Konfiguration — Serial-Tracking für hochwertige Güter

**Files:** (keine Code-Datei — Odoo-Konfiguration über `odoocli`, anschließend lesend verifiziert)

- [ ] **Step 1: Kandidaten lesen** (welche Produkte sind „hochwertig"?)

```powershell
odoocli --json model search-read product.product --domain '[["tracking","=","none"]]' --fields id,name,default_code,tracking --limit 20
```

- [ ] **Step 2: Tracking auf `serial` setzen** (Beispiel-IDs ersetzen) — Schreibbefehl, nach Freigabe

```powershell
odoocli model write product.template --ids <TMPL_ID> --values '{"tracking":"serial"}'
```

- [ ] **Step 3: Verifizieren**

```powershell
odoocli --json model search-read product.product --domain '[["tracking","=","serial"]]' --fields id,name,tracking
```
Expected: die gewählten Produkte erscheinen mit `tracking = serial`.

- [ ] **Step 4: Commit** (Doku-Notiz, kein Code)

```bash
git commit --allow-empty -m "chore(odoo): Serial-Tracking fuer hochwertige Gueter aktiviert (Konfig)"
```

---

### Task 5: PWA — optionalen Seriennummer-Scan im Confirm-Flow

**Files:**
- Modify: `backend/.. ` (keine) · `pwa/js/app.js` (Funktion `handleScan`, ab Zeile ~2161; Aufruf von `confirmLine` ~2190)
- (api.js bleibt unverändert: `confirmLine(pickingId, data, ...)` reicht `data` 1:1 durch.)

**Interfaces:**
- Consumes: `confirmLine(pickingId, { move_line_id, scanned_barcode, quantity, serial_number }, opts)`.

- [ ] **Step 1: Serial-Eingabe ergänzen**

In `handleScan(barcode)` nach erfolgreicher Produkt-Validierung: wenn die Zeile ein serialisiertes Produkt betrifft (Flag vom Backend, z. B. `line.tracking === 'serial'`), per `showManualInput(...)` / Scanner eine Seriennummer abfragen und in einer Variable `serialNumber` halten (Touch-Fallback bleibt: leer lassen erlaubt, wenn nicht serialisiert).

- [ ] **Step 2: `serial_number` an `confirmLine` übergeben**

Den bestehenden `confirmLine`-Aufruf (heute mit `{ move_line_id, scanned_barcode, quantity }`) erweitern zu:

```javascript
const result = await withManagedRequest((signal) => confirmLine(
    activePickingId,
    {
        move_line_id: line.id,
        scanned_barcode: barcode || line.product_barcode || '',
        quantity: line.quantity_demand || 1,
        serial_number: serialNumber || '',
    },
    { idempotencyKey: buildOperationKey('confirm-line', [/* ...bestehende parts... */]), signal },
));
```

- [ ] **Step 3: Backend liefert `tracking` an die PWA**
In `PickingService.get_picking_detail` pro Move-Line das Produktfeld `tracking` mitliefern (analog zu `barcode`/`default_code` in `product_meta_map`, Zeile ~474), als `line["tracking"]`.

- [ ] **Step 4: UI-Test laufen lassen**

Run: `make verify-ui`
Expected: PASS (PWA-Browser-Tests grün; bestehender Confirm-Flow unverändert wenn kein Serial).

- [ ] **Step 5: Commit**

```bash
git add pwa/js/app.js backend/app/services/picking_service.py
git commit -m "feat(pwa): optionaler Seriennummer-Scan im Confirm-Flow"
```

---

## Validierung & Messung (Antwort auf „wie validiere/messe ich das richtig")

**Validierung (Korrektheit):**
- **Unit/TDD:** Tasks 1–3 sind testgetrieben (`reconcile_serials`, `confirm_pick_line` mit Serial, `summarize_serial_events`). `make verify-code` muss grün sein.
- **Integration/UI:** `make verify-ui` für den PWA-Flow; `make verify-stack` wenn der Stack läuft (echter Confirm gegen `masterfischer`).
- **Manuell (Beispiel Prof):** versendet `1,2,3,4`, zurück `1,5,5` → `reconcile_serials` liefert `missing=[2,3,4]`, `unknown=[5]`, `duplicates=[5]`.

**Messung (Design-Science-Evaluation):** jedes Confirm emittiert ein `serial_confirm`-JSON-Event. Über `summarize_serial_events` (bzw. später `export_telemetry_stats.py`) entstehen die Kennzahlen für das Evaluationskapitel:
- **Scan-/Erfassungsrate** (`serial_capture_rate`), **Erfolgsrate** (`success_rate`)
- **Bestätigungs-Latenz** `p50`/`p95` (ms)
- (für Retouren später: Mismatch-/Duplikat-Quote aus `reconcile_serials`)

---

## Self-Review

- **Spec-Abdeckung:** Seriennummer erfassen (Task 2/5) ✓ · in Odoo speichern (Task 2, `lot_name`) ✓ · hochwertige Güter (Task 4, `tracking=serial`) ✓ · Retouren-Abgleich (Task 1) ✓ · Messung/Validierung (Task 3 + Abschnitt) ✓ · optionales Foto → **bewusst NICHT in v1** (eigener kleiner Folge-Task, siehe Roadmap).
- **Platzhalter:** keine — jeder Code-Step enthält vollständigen Code; Odoo-/PWA-Steps nennen exakte Dateien/Funktionen/Zeilen.
- **Typ-Konsistenz:** `serial_number`/`serial_clean`/`recorded_serial` (Backend), `serial_number` (Router/PWA-Body), Event-Keys (`success`,`serial_recorded`,`latency_ms`) konsistent zwischen Emitter (Task 3 Step 4) und Auswertung (Task 3 Step 3).
- **Rückwärtskompatibilität:** ohne `serial_number` unverändertes Verhalten (Default `""`, kein `write`).

## Roadmap (Folge-Pläne, je eigener Spec→Plan)
1. **Foto-Nachweis** zum Serial (kleiner Zusatz-Task, FormData wie `createQualityAlert`).
2. **Karton-/Behälter-Tracking** (`stock.quant.package`, `result_package_id`).
3. **Cluster-/Batch-Picking** (`stock.picking.batch`).
4. **Odoo-Instanz-Switching** (Backend-Config-Register).
