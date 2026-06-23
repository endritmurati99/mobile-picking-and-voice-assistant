# Cluster-/Batch-Picking Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Mehrere offene Pickaufträge als echter Odoo `stock.picking.batch` gebündelt in einem Rundgang abarbeiten — Backend (FastAPI/JSON-RPC) + PWA-View mit Box-Zuordnung, Serial und Voice.

**Architecture:** Neuer `ClusterService` + Router `/api/cluster/*` legen einen echten `stock.picking.batch` an, liefern eine route-sortierte Sammelliste über alle Batch-Pickings, bestätigen Positionen **ohne** Einzel-Validierung und schließen am Ende den ganzen Batch via `action_done` ab. Die PWA bekommt additive Views (Auswahl + Rundgang). `picking_service.py` bleibt unberührt; Wiederverwendung von `route_optimizer.build_route_plan` und den Enrichment-Helfern.

**Tech Stack:** Python 3 / FastAPI / `unittest.mock.AsyncMock` + `pytest` (anyio); Odoo 18 JSON-RPC; Vanilla-JS-PWA; Playwright (e2e/visual/a11y).

## Global Constraints

- Odoo ist System of Record — kein Schatten-State; der Batch ist ein echter Odoo-Datensatz. (Inv. 1)
- PWA spricht nur mit FastAPI über `pwa/js/api.js`. (Inv. 2)
- Odoo-18-Felder: Move-Line-Menge = `quantity` (NICHT `qty_done`); `stock.move.picked` (bool); Bedarf = `stock.move.product_uom_qty`. Serial via `lot_name` (string) nur bei `product.tracking in ('serial','lot')`.
- Endpoint-Prefix `/api`; Picker-Identity über Header `X-Picker-User-Id` / `X-Device-Id`; Idempotenz über `Idempotency-Key` analog `pickings.py`.
- `picking_service.py` NICHT ändern. Backend-Touch außerhalb neuer Dateien nur: eine `include_router`-Zeile in `main.py` + ein `get_cluster_service`-Provider in `dependencies.py` (beide additiv).
- Box-Zuordnung ist rein logisch (Box N ↔ Picking N) — KEINE echten Odoo-Packages (`result_package_id`).
- Branch `feat/cluster-picking`; pro Task committen + pushen; **nicht** mergen.
- Demo-DB `masterfischer`, Picker „Max Picker" (uid 7).

> **Verifizierter Odoo-18-Stand (Fact-Sheet 2026-06-23, quellenverifiziert gegen `odoo/odoo@18.0`):**
> - `create`: `company_id` mitgeben (von den Pickings übernehmen, sonst `_check_company`-Fehler bei confirm/done); **`name` weglassen** (Sequenz `picking.batch` füllt; NIE `name='New'`); `user_id`, `picking_ids=[(6,0,ids)]`.
> - `action_confirm([id])`: draft→in_progress (bestätigt Member-Pickings, setzt `state`). NICHT `action_done`.
> - `action_done([id])`: validiert alle Member-Pickings via `button_validate`. **Gibt oft ein Wizard-Action-Dict zurück, NICHT `True`** — Rückgabewert prüfen. Backorder-Wizard bei Teilmengen unterdrücken via Kontext `{'skip_backorder': True, 'picking_ids_not_to_backorder': <member_ids>}` (Policy „No Backorder").
> - `state` ist computed — NIE direkt schreiben; nur über action_confirm/done/cancel.
> - Serial: `lot_name` (Char) auf Move-Line → Odoo legt `stock.lot` **bei Validierung** an (gated auf `picking_type.use_create_lots`); Serial braucht **1 Zeile/Stück, qty=1**; `lot_name` auf untracked Produkt wird ignoriert.
> - `picked=True` blockiert Re-Reservierung (für unseren Flow ok).
> - **Vor erstem echten Lauf gegen `masterfischer` verifizieren:** Modul `stock_picking_batch` installiert? `picking_type.use_create_lots`/`create_backorder`-Flags? RPC-User in `stock.group_production_lot`? Backorder-Verhalten end-to-end non-interaktiv?

---

### Task 1: Cluster-Planungs-Helfer (Box-Zuordnung + Merge/Route-Sort)

Reine, seiteneffektfreie Funktionen im Modulkopf von `cluster_service.py`. Kein Odoo nötig.

**Files:**
- Create: `backend/app/services/cluster_service.py`
- Test: `backend/tests/test_cluster_service.py`

**Interfaces:**
- Produces:
  - `BOX_PALETTE: list[str]` — feste Hex-Farbtokens (zyklisch).
  - `assign_boxes(picking_ids: list[int]) -> dict[int, dict]` — `{picking_id: {"box_index": int (1-based), "box_color": str}}`, deterministisch nach aufsteigender `picking_id`.
  - `build_cluster_lines(lines_by_picking: dict[int, list[dict]], box_map: dict[int, dict]) -> list[dict]` — alle Move-Lines mergen, je Zeile `box_index`/`box_color`/`picking_id` taggen, dann via `build_route_plan` route-sortieren; Rückgabe = sortierte Zeilenliste (`ordered_move_lines`) mit Box-Tags.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_cluster_service.py
from app.services.cluster_service import assign_boxes, build_cluster_lines, BOX_PALETTE


class TestAssignBoxes:
    def test_assigns_one_based_index_by_sorted_picking_id(self):
        result = assign_boxes([30, 10, 20])
        assert result[10]["box_index"] == 1
        assert result[20]["box_index"] == 2
        assert result[30]["box_index"] == 3

    def test_color_is_deterministic_and_from_palette(self):
        a = assign_boxes([10, 20])
        b = assign_boxes([20, 10])
        assert a == b
        assert a[10]["box_color"] in BOX_PALETTE
        assert a[20]["box_color"] in BOX_PALETTE

    def test_more_pickings_than_palette_cycles(self):
        ids = list(range(1, len(BOX_PALETTE) + 2))
        result = assign_boxes(ids)
        first = result[1]["box_color"]
        wrapped = result[len(BOX_PALETTE) + 1]["box_color"]
        assert first == wrapped  # palette cycles


class TestBuildClusterLines:
    def test_merges_tags_and_route_sorts(self):
        lines_by_picking = {
            10: [{"id": 100, "product_name": "A", "location_src": "WH/Stock/Mitte/E2-P5", "picked": False}],
            20: [{"id": 200, "product_name": "B", "location_src": "WH/Stock/Links/E1-P1", "picked": False}],
        }
        box_map = assign_boxes([10, 20])
        result = build_cluster_lines(lines_by_picking, box_map)
        # Links-Zone wird vor Mitte einsortiert (route_optimizer)
        assert [l["id"] for l in result] == [200, 100]
        tagged = {l["id"]: l for l in result}
        assert tagged[200]["box_index"] == box_map[20]["box_index"]
        assert tagged[200]["picking_id"] == 20
        assert tagged[100]["box_color"] == box_map[10]["box_color"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_cluster_service.py -v`
Expected: FAIL — `ModuleNotFoundError`/`ImportError: cannot import name 'assign_boxes'`.

- [ ] **Step 3: Write minimal implementation**

```python
# backend/app/services/cluster_service.py
"""
Cluster-/Batch-Picking — mehrere stock.picking gebündelt in einem Rundgang.

Odoo 18: echter stock.picking.batch (action_confirm / action_done).
Box-Zuordnung ist rein logisch (Box N <-> Picking N), keine Odoo-Packages.
picking_service.py bleibt unberührt; Route-Sort + Enrichment werden wiederverwendet.
"""
from __future__ import annotations

from typing import Any

from app.services.route_optimizer import build_route_plan

# Farbtokens passend zum PWA-Designsystem (Akzent-Palette, zyklisch).
BOX_PALETTE: list[str] = ["#A299FF", "#FF8A7E", "#6FD3C7", "#F4C77B", "#7EA8FF", "#C58BFF"]


def assign_boxes(picking_ids: list[int]) -> dict[int, dict[str, Any]]:
    """Deterministische Box-Nummer + Farbe je Picking (1-based, nach picking_id sortiert)."""
    box_map: dict[int, dict[str, Any]] = {}
    for index, picking_id in enumerate(sorted(set(picking_ids))):
        box_map[picking_id] = {
            "box_index": index + 1,
            "box_color": BOX_PALETTE[index % len(BOX_PALETTE)],
        }
    return box_map


def build_cluster_lines(
    lines_by_picking: dict[int, list[dict[str, Any]]],
    box_map: dict[int, dict[str, Any]],
) -> list[dict[str, Any]]:
    """Alle Move-Lines mergen, mit Box/Picking taggen und route-sortieren."""
    merged: list[dict[str, Any]] = []
    for picking_id, lines in lines_by_picking.items():
        box = box_map.get(picking_id, {})
        for line in lines:
            tagged = dict(line)
            tagged["picking_id"] = picking_id
            tagged["box_index"] = box.get("box_index")
            tagged["box_color"] = box.get("box_color")
            merged.append(tagged)
    plan = build_route_plan(merged)
    # build_route_plan liefert nur offene Zeilen in ordered_move_lines; für die
    # Sammelliste wollen wir ALLE Zeilen sortiert -> erneut nach gleicher Logik
    # sortieren ist nicht nötig: build_route_plan sortiert intern alle, gibt aber
    # nur offene zurück. Wir sortieren daher selbst stabil über den Plan hinweg.
    ordered_open = plan["ordered_move_lines"]
    open_ids = {l["id"] for l in ordered_open}
    done = [l for l in merged if l["id"] not in open_ids]
    return ordered_open + done
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_cluster_service.py -v`
Expected: PASS (3 + 1 Tests grün).

- [ ] **Step 5: Commit + push**

```bash
git add backend/app/services/cluster_service.py backend/tests/test_cluster_service.py
git commit -m "feat(cluster): box assignment + merged route-sort helpers (TDD)"
git push
```

---

### Task 2: `ClusterService.suggest_batches`

**Files:**
- Modify: `backend/app/services/cluster_service.py` (Service-Klasse hinzufügen)
- Test: `backend/tests/test_cluster_service.py`

**Interfaces:**
- Consumes: `OdooClient.search_read`, `route_optimizer` Zonen-Logik (`_location_zone` aus `picking_service` wird NICHT importiert — eigene schlanke Zonen-Ableitung über `build_route_plan`/`location_src`).
- Produces: `class ClusterService.__init__(self, odoo, n8n)`; `async suggest_batches(self) -> list[dict]` → `[{"zone": str, "picking_ids": [int], "order_count": int, "line_count": int, "picking_names": [str]}]`.

- [ ] **Step 1: Write the failing test**

```python
# append to backend/tests/test_cluster_service.py
from unittest.mock import AsyncMock
import pytest
from app.services.cluster_service import ClusterService


@pytest.fixture
def odoo():
    return AsyncMock()


@pytest.fixture
def n8n():
    return AsyncMock()


@pytest.fixture
def service(odoo, n8n):
    return ClusterService(odoo, n8n)


class TestSuggestBatches:
    @pytest.mark.anyio
    async def test_groups_assigned_pickings_without_batch_by_zone(self, service, odoo):
        async def fake_search_read(model, domain, fields, limit=100):
            if model == "stock.picking":
                # Nur assigned + batch_id == False werden geladen (domain enthält das)
                return [
                    {"id": 1, "name": "WH/OUT/001", "batch_id": False},
                    {"id": 2, "name": "WH/OUT/002", "batch_id": False},
                ]
            if model == "stock.move.line":
                return [
                    {"id": 10, "picking_id": [1, "WH/OUT/001"], "location_id": [5, "WH/Stock/Links/E1-P1"]},
                    {"id": 11, "picking_id": [2, "WH/OUT/002"], "location_id": [6, "WH/Stock/Links/E1-P2"]},
                ]
            raise AssertionError(model)

        odoo.search_read.side_effect = fake_search_read
        result = await service.suggest_batches()
        assert len(result) == 1
        group = result[0]
        assert group["zone"] == "Links"
        assert sorted(group["picking_ids"]) == [1, 2]
        assert group["order_count"] == 2
        assert group["line_count"] == 2

    @pytest.mark.anyio
    async def test_returns_empty_when_no_open_pickings(self, service, odoo):
        odoo.search_read.return_value = []
        assert await service.suggest_batches() == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_cluster_service.py::TestSuggestBatches -v`
Expected: FAIL — `cannot import name 'ClusterService'`.

- [ ] **Step 3: Write minimal implementation**

```python
# add to backend/app/services/cluster_service.py
import re
from collections import defaultdict


def _zone_of(location: str) -> str:
    parts = [p.strip() for p in (location or "").split("/") if p.strip()]
    return parts[-2] if len(parts) >= 2 else (parts[-1] if parts else "Unbekannt")


class ClusterService:
    def __init__(self, odoo, n8n):
        self._odoo = odoo
        self._n8n = n8n

    async def suggest_batches(self) -> list[dict[str, Any]]:
        pickings = await self._odoo.search_read(
            "stock.picking",
            [("state", "=", "assigned"), ("batch_id", "=", False)],
            ["name", "batch_id"],
            limit=100,
        )
        if not pickings:
            return []
        picking_ids = [p["id"] for p in pickings]
        name_by_id = {p["id"]: p["name"] for p in pickings}
        lines = await self._odoo.search_read(
            "stock.move.line",
            [("picking_id", "in", picking_ids)],
            ["picking_id", "location_id"],
            limit=max(500, len(picking_ids) * 20),
        )
        groups: dict[str, dict[str, Any]] = defaultdict(
            lambda: {"picking_ids": set(), "line_count": 0}
        )
        line_zone_by_picking: dict[int, str] = {}
        for line in lines:
            pid = line["picking_id"][0] if line.get("picking_id") else None
            if pid is None:
                continue
            zone = _zone_of(line["location_id"][1] if line.get("location_id") else "")
            line_zone_by_picking.setdefault(pid, zone)
            groups[line_zone_by_picking[pid]]["picking_ids"].add(pid)
            groups[line_zone_by_picking[pid]]["line_count"] += 1
        result = []
        for zone, data in groups.items():
            pids = sorted(data["picking_ids"])
            result.append({
                "zone": zone,
                "picking_ids": pids,
                "order_count": len(pids),
                "line_count": data["line_count"],
                "picking_names": [name_by_id[p] for p in pids],
            })
        result.sort(key=lambda g: (-g["order_count"], g["zone"]))
        return result
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_cluster_service.py::TestSuggestBatches -v`
Expected: PASS.

- [ ] **Step 5: Commit + push**

```bash
git add backend/app/services/cluster_service.py backend/tests/test_cluster_service.py
git commit -m "feat(cluster): suggest_batches groups open pickings by zone (TDD)"
git push
```

---

### Task 3: `ClusterService.create_batch`

**Interfaces:**
- Produces: `async create_batch(self, picking_ids: list[int], picker_identity=None) -> dict` → ruft `odoo.create("stock.picking.batch", {...})` + `odoo.call_method("stock.picking.batch","action_confirm",[batch_id])`, dann `get_batch(batch_id)`. Rückgabe = `get_batch`-Payload.

- [ ] **Step 1: Write the failing test**

```python
class TestCreateBatch:
    @pytest.mark.anyio
    async def test_creates_batch_with_six_zero_command_and_confirms(self, service, odoo):
        odoo.create.return_value = 99
        async def fake_search_read(model, domain, fields, limit=100):
            if model == "stock.picking.batch":
                return [{"id": 99, "name": "BATCH/0099", "state": "in_progress",
                         "picking_ids": [1, 2], "user_id": [7, "Max Picker"]}]
            if model == "stock.picking":
                # create_batch reads company_id off the pickings; get_batch reads name
                return [{"id": 1, "name": "WH/OUT/001", "company_id": [1, "MyCo"]},
                        {"id": 2, "name": "WH/OUT/002", "company_id": [1, "MyCo"]}]
            if model == "stock.move.line":
                return []
            if model == "stock.move":
                return []
            if model == "product.product":
                return []
            raise AssertionError(model)
        odoo.search_read.side_effect = fake_search_read

        from app.services.mobile_workflow import PickerIdentity
        result = await service.create_batch([1, 2], PickerIdentity(user_id=7))

        create_args = odoo.create.call_args
        assert create_args.args[0] == "stock.picking.batch"
        vals = create_args.args[1]
        assert vals["picking_ids"] == [(6, 0, [1, 2])]
        assert vals["user_id"] == 7
        assert vals["company_id"] == 1            # taken from the pickings
        assert "name" not in vals                 # sequence fills it
        odoo.call_method.assert_any_call("stock.picking.batch", "action_confirm", [99])
        assert result["batch_id"] == 99

    @pytest.mark.anyio
    async def test_rejects_empty_picking_ids(self, service):
        with pytest.raises(ValueError):
            await service.create_batch([])
```

- [ ] **Step 2: Run** `pytest tests/test_cluster_service.py::TestCreateBatch -v` → FAIL (`no attribute create_batch`).

- [ ] **Step 3: Implement**

```python
    async def create_batch(self, picking_ids, picker_identity=None) -> dict[str, Any]:
        ids = [int(p) for p in (picking_ids or [])]
        if not ids:
            raise ValueError("picking_ids darf nicht leer sein")
        # company_id von den Pickings übernehmen -> verhindert _check_company beim confirm/done.
        pickings = await self._odoo.search_read(
            "stock.picking", [("id", "in", ids)], ["company_id"], limit=len(ids))
        company_id = None
        for p in pickings:
            if p.get("company_id"):
                company_id = p["company_id"][0]
                break
        # 'name' bewusst weglassen -> Odoo-Sequenz 'picking.batch' füllt es.
        vals: dict[str, Any] = {"picking_ids": [(6, 0, ids)]}
        if company_id is not None:
            vals["company_id"] = company_id
        if picker_identity and getattr(picker_identity, "user_id", None):
            vals["user_id"] = picker_identity.user_id
        batch_id = await self._odoo.create("stock.picking.batch", vals)
        await self._odoo.call_method("stock.picking.batch", "action_confirm", [batch_id])
        return await self.get_batch(batch_id)
```

- [ ] **Step 4: Run** → PASS. (Benötigt `get_batch` aus Task 4; bis dahin Test mit Stub-`get_batch` lauffähig — implementiere Task 4 unmittelbar danach, oder definiere `get_batch` zuerst als Skeleton, das die gemockten Reads bedient.)

> **Reihenfolge-Hinweis:** Task 3 und Task 4 zusammen committen, da `create_batch` auf `get_batch` aufbaut. Test aus Task 3 wird erst nach Task 4 vollständig grün.

- [ ] **Step 5: Commit + push** (gemeinsam mit Task 4)

---

### Task 4: `ClusterService.get_batch` (Sammelliste + Fortschritt)

**Interfaces:**
- Produces: `async get_batch(self, batch_id: int) -> dict` → `{"batch_id", "name", "state", "picker", "boxes":[{box_index,box_color,picking_id,picking_name}], "lines":[<cluster line>], "progress":{"total","done","ratio"}}`. Jede Zeile enthält `id, picking_id, box_index, box_color, product_name, product_barcode, tracking, quantity_demand, quantity_done, picked, location_src, location_src_short, voice_instruction_short`.

- [ ] **Step 1: Write the failing test**

```python
class TestGetBatch:
    @pytest.mark.anyio
    async def test_returns_route_sorted_lines_with_box_tags_and_progress(self, service, odoo):
        async def fake_search_read(model, domain, fields, limit=100):
            if model == "stock.picking.batch":
                return [{"id": 99, "name": "BATCH/0099", "state": "in_progress",
                         "picking_ids": [1, 2], "user_id": [7, "Max Picker"]}]
            if model == "stock.picking":
                return [{"id": 1, "name": "WH/OUT/001"}, {"id": 2, "name": "WH/OUT/002"}]
            if model == "stock.move.line":
                return [
                    {"id": 100, "picking_id": [1, "WH/OUT/001"], "product_id": [5, "[X] Wal"],
                     "quantity": 0, "move_id": [50, "m"], "location_id": [9, "WH/Stock/Mitte/E2-P5"]},
                    {"id": 200, "picking_id": [2, "WH/OUT/002"], "product_id": [6, "Ente"],
                     "quantity": 0, "move_id": [60, "m"], "location_id": [8, "WH/Stock/Links/E1-P1"]},
                ]
            if model == "stock.move":
                return [{"id": 50, "product_uom_qty": 2, "picked": False},
                        {"id": 60, "product_uom_qty": 1, "picked": True}]
            if model == "product.product":
                return [{"id": 5, "default_code": "WAL", "barcode": "111", "tracking": "serial"},
                        {"id": 6, "default_code": "ENT", "barcode": "222", "tracking": "none"}]
            raise AssertionError(model)
        odoo.search_read.side_effect = fake_search_read

        result = await service.get_batch(99)
        assert result["batch_id"] == 99
        assert result["state"] == "in_progress"
        # Links (Ente) vor Mitte (Wal): offene zuerst, route-sortiert
        ids = [l["id"] for l in result["lines"]]
        assert ids[0] == 200
        by_id = {l["id"]: l for l in result["lines"]}
        assert by_id[100]["box_index"] == 1 and by_id[200]["box_index"] == 2
        assert by_id[100]["tracking"] == "serial"
        assert result["progress"]["total"] == 2
        assert result["progress"]["done"] == 1
```

- [ ] **Step 2: Run** → FAIL.

- [ ] **Step 3: Implement** (mergt Reads, baut Zeilen, nutzt `assign_boxes`/`build_cluster_lines`)

```python
    async def get_batch(self, batch_id: int) -> dict[str, Any]:
        batches = await self._odoo.search_read(
            "stock.picking.batch", [("id", "=", batch_id)],
            ["name", "state", "picking_ids", "user_id"], limit=1,
        )
        if not batches:
            return {"error": "Batch nicht gefunden"}
        batch = batches[0]
        picking_ids = batch.get("picking_ids", []) or []
        pickings = await self._odoo.search_read(
            "stock.picking", [("id", "in", picking_ids)], ["name"], limit=len(picking_ids) or 1,
        ) if picking_ids else []
        name_by_picking = {p["id"]: p["name"] for p in pickings}
        box_map = assign_boxes(picking_ids)

        raw_lines = await self._odoo.search_read(
            "stock.move.line", [("picking_id", "in", picking_ids)],
            ["picking_id", "product_id", "quantity", "move_id", "location_id"],
            limit=max(500, len(picking_ids) * 20),
        ) if picking_ids else []

        move_ids = list({l["move_id"][0] for l in raw_lines if l.get("move_id")})
        moves = await self._odoo.search_read(
            "stock.move", [("id", "in", move_ids)], ["id", "product_uom_qty", "picked"],
        ) if move_ids else []
        move_map = {m["id"]: m for m in moves}

        product_ids = list({l["product_id"][0] for l in raw_lines if l.get("product_id")})
        products = await self._odoo.search_read(
            "product.product", [("id", "in", product_ids)],
            ["id", "default_code", "barcode", "tracking"],
        ) if product_ids else []
        product_map = {p["id"]: p for p in products}

        lines_by_picking: dict[int, list[dict[str, Any]]] = defaultdict(list)
        for raw in raw_lines:
            pid = raw["picking_id"][0] if raw.get("picking_id") else None
            move = move_map.get(raw["move_id"][0] if raw.get("move_id") else None, {})
            product_id = raw["product_id"][0] if raw.get("product_id") else None
            product = product_map.get(product_id, {})
            location = raw["location_id"][1] if raw.get("location_id") else ""
            loc_parts = [p.strip() for p in location.split("/") if p.strip()]
            lines_by_picking[pid].append({
                "id": raw["id"],
                "product_id": product_id,
                "product_name": re.sub(r"^\[.*?\]\s*", "", raw["product_id"][1]) if raw.get("product_id") else "",
                "product_barcode": product.get("barcode"),
                "product_sku": product.get("default_code") or "",
                "tracking": product.get("tracking"),
                "quantity_demand": move.get("product_uom_qty", raw.get("quantity", 0)),
                "quantity_done": raw.get("quantity", 0) if move.get("picked") else 0,
                "picked": bool(move.get("picked")),
                "location_src": location,
                "location_src_short": loc_parts[-1] if loc_parts else location,
            })

        ordered = build_cluster_lines(lines_by_picking, box_map)
        for line in ordered:
            short = line.get("location_src_short", "")
            qty = line.get("quantity_demand", 0)
            name = line.get("product_name", "")
            line["voice_instruction_short"] = f"{short}. {qty} Stück. {name}.".strip()
            line["picking_name"] = name_by_picking.get(line.get("picking_id"), "")

        total = len(ordered)
        done = sum(1 for l in ordered if l.get("picked"))
        return {
            "batch_id": batch_id,
            "name": batch.get("name", ""),
            "state": batch.get("state", ""),
            "picker": batch["user_id"][1] if batch.get("user_id") else "",
            "boxes": [
                {"picking_id": pid, "picking_name": name_by_picking.get(pid, ""),
                 "box_index": box_map[pid]["box_index"], "box_color": box_map[pid]["box_color"]}
                for pid in sorted(picking_ids)
            ],
            "lines": ordered,
            "progress": {"total": total, "done": done,
                         "ratio": round(done / total, 4) if total else 0.0},
        }
```

- [ ] **Step 4: Run** `pytest tests/test_cluster_service.py::TestGetBatch tests/test_cluster_service.py::TestCreateBatch -v` → PASS.

- [ ] **Step 5: Commit + push**

```bash
git add backend/app/services/cluster_service.py backend/tests/test_cluster_service.py
git commit -m "feat(cluster): create_batch + get_batch (merged route-sorted list, box tags, progress) (TDD)"
git push
```

---

### Task 5: `ClusterService.confirm_cluster_line` (Bestätigen OHNE Validate)

**Interfaces:**
- Produces: `async confirm_cluster_line(self, batch_id, picking_id, move_line_id, scanned_barcode="", quantity=0, serial_number="", picker_identity=None) -> dict` → schreibt `quantity` (+ optional `lot_name` bei tracking) + `stock.move.picked=True`; ruft **kein** `button_validate`; Telemetrie-Event `cluster_confirm`. Rückgabe `{"success", "message", "recorded_serial", "progress"}`.

- [ ] **Step 1: Write the failing test**

```python
class TestConfirmClusterLine:
    @pytest.mark.anyio
    async def test_writes_quantity_and_picked_without_validate(self, service, odoo):
        async def fake_execute_kw(model, method, args, kwargs=None):
            if model == "stock.move.line" and method == "read":
                return [{"id": 100, "product_id": [5, "Wal"], "quantity": 0,
                         "move_id": [50, "m"], "location_id": [9, "L"]}]
            raise AssertionError((model, method))
        odoo.execute_kw.side_effect = fake_execute_kw
        odoo.search_read.return_value = []  # get_batch progress reads -> leer ok

        await service.confirm_cluster_line(99, 1, 100, scanned_barcode="", quantity=2)

        # quantity + picked geschrieben, KEIN button_validate
        odoo.write.assert_any_call("stock.move.line", [100], {"quantity": 2})
        odoo.write.assert_any_call("stock.move", [50], {"picked": True})
        for call in odoo.call_method.call_args_list:
            assert call.args[1] != "button_validate"

    @pytest.mark.anyio
    async def test_records_serial_for_tracked_product(self, service, odoo):
        async def fake_execute_kw(model, method, args, kwargs=None):
            if model == "stock.move.line" and method == "read":
                return [{"id": 100, "product_id": [5, "Wal"], "quantity": 0,
                         "move_id": [50, "m"], "location_id": [9, "L"]}]
            raise AssertionError((model, method))
        odoo.execute_kw.side_effect = fake_execute_kw
        async def fake_search_read(model, domain, fields, limit=100):
            if model == "product.product":
                return [{"id": 5, "tracking": "serial", "barcode": "111"}]
            return []
        odoo.search_read.side_effect = fake_search_read

        result = await service.confirm_cluster_line(99, 1, 100, scanned_barcode="111",
                                                    quantity=1, serial_number="SN-1")
        written = [c.args[2] for c in odoo.write.call_args_list if c.args[0] == "stock.move.line"]
        assert any(v.get("lot_name") == "SN-1" for v in written)
        assert result["recorded_serial"] == "SN-1"
```

- [ ] **Step 2: Run** → FAIL.

- [ ] **Step 3: Implement** (orientiert an `confirm_pick_line`, aber OHNE Validate/all-done):

```python
import json
import logging
import time
logger = logging.getLogger(__name__)


    async def confirm_cluster_line(self, batch_id, picking_id, move_line_id,
                                   scanned_barcode="", quantity=0, serial_number="",
                                   picker_identity=None) -> dict[str, Any]:
        t0 = time.monotonic()
        lines = await self._odoo.execute_kw(
            "stock.move.line", "read", [[move_line_id]],
            {"fields": ["id", "product_id", "quantity", "move_id", "location_id"]},
        )
        if not lines:
            self._emit_cluster_confirm(False, batch_id, picking_id, move_line_id, None, False, t0)
            return {"success": False, "message": "Move-Line nicht gefunden", "progress": None}
        line = lines[0]
        product_id = line["product_id"][0] if line.get("product_id") else None
        move_id = line["move_id"][0] if line.get("move_id") else None

        if product_id and scanned_barcode:
            products = await self._odoo.search_read(
                "product.product", [("id", "=", product_id)], ["barcode", "tracking"])
            expected = products[0].get("barcode") if products else None
            if expected and scanned_barcode != expected:
                self._emit_cluster_confirm(False, batch_id, picking_id, move_line_id, product_id, False, t0)
                return {"success": False, "message": f"Falscher Artikel. Erwartet: {expected}", "progress": None}

        qty = quantity if quantity > 0 else line.get("quantity", 1.0)
        line_values: dict[str, Any] = {"quantity": qty}
        recorded_serial = ""
        serial_clean = (serial_number or "").strip()
        if serial_clean and product_id:
            tracked = await self._odoo.search_read("product.product", [("id", "=", product_id)], ["tracking"])
            if tracked and tracked[0].get("tracking") in ("serial", "lot"):
                line_values["lot_name"] = serial_clean
                recorded_serial = serial_clean
        await self._odoo.write("stock.move.line", [move_line_id], line_values)
        if move_id:
            await self._odoo.write("stock.move", [move_id], {"picked": True})

        self._emit_cluster_confirm(True, batch_id, picking_id, move_line_id, product_id, bool(recorded_serial), t0)
        batch = await self.get_batch(batch_id)
        return {"success": True, "message": "Bestätigt.", "recorded_serial": recorded_serial,
                "progress": batch.get("progress")}

    def _emit_cluster_confirm(self, success, batch_id, picking_id, move_line_id, product_id, serial_recorded, t0):
        logger.info(json.dumps({
            "event_type": "cluster_confirm", "batch_id": batch_id, "picking_id": picking_id,
            "move_line_id": move_line_id, "product_id": product_id, "success": success,
            "serial_recorded": serial_recorded, "latency_ms": int((time.monotonic() - t0) * 1000),
        }, ensure_ascii=False))
```

- [ ] **Step 4: Run** `pytest tests/test_cluster_service.py::TestConfirmClusterLine -v` → PASS.

- [ ] **Step 5: Commit + push**

```bash
git add backend/app/services/cluster_service.py backend/tests/test_cluster_service.py
git commit -m "feat(cluster): confirm_cluster_line records qty/serial without per-picking validate (TDD)"
git push
```

---

### Task 6: `ClusterService.validate_batch` (action_done + n8n)

**Interfaces:**
- Produces: `async validate_batch(self, batch_id, picker_identity=None) -> dict` → `odoo.call_method("stock.picking.batch","action_done",[batch_id], context={"skip_backorder": True, "skip_immediate": True})`; bei Erfolg `n8n.fire_event("batch-confirmed", {...})`; Rückgabe `{"success", "message", "batch_complete", "integration_status"?}`.

- [ ] **Step 1: Write the failing test**

```python
from app.services.n8n_webhook import N8NEventResult

class TestValidateBatch:
    @pytest.mark.anyio
    async def test_calls_action_done_with_backorder_ctx_and_fires_n8n(self, service, odoo, n8n):
        odoo.search_read.return_value = [{"id": 99, "picking_ids": [1, 2]}]
        odoo.call_method.return_value = True  # action_done completes, no wizard
        n8n.fire_event.return_value = N8NEventResult(delivered=True, error=None, correlation_id="c1")
        from app.services.mobile_workflow import PickerIdentity
        result = await service.validate_batch(99, PickerIdentity(user_id=7))
        done_call = [c for c in odoo.call_method.call_args_list
                     if c.args[:2] == ("stock.picking.batch", "action_done")]
        assert done_call, "action_done must be called"
        assert done_call[0].args[2] == [99]
        # Backorder-Wizard wird per Kontext unterdrückt
        assert done_call[0].kwargs["context"]["skip_backorder"] is True
        assert done_call[0].kwargs["context"]["picking_ids_not_to_backorder"] == [1, 2]
        n8n.fire_event.assert_called_once()
        assert result["batch_complete"] is True

    @pytest.mark.anyio
    async def test_reports_pending_when_action_done_returns_wizard(self, service, odoo, n8n):
        odoo.search_read.return_value = [{"id": 99, "picking_ids": [1, 2]}]
        odoo.call_method.return_value = {"res_model": "stock.backorder.confirmation",
                                         "type": "ir.actions.act_window"}
        result = await service.validate_batch(99)
        assert result["success"] is False
        assert result["batch_complete"] is False
        assert result["pending_action"] == "stock.backorder.confirmation"
        n8n.fire_event.assert_not_called()

    @pytest.mark.anyio
    async def test_reports_failure_when_action_done_raises(self, service, odoo, n8n):
        from app.services.odoo_client import OdooAPIError
        odoo.search_read.return_value = [{"id": 99, "picking_ids": [1, 2]}]
        odoo.call_method.side_effect = OdooAPIError("rpc error")
        result = await service.validate_batch(99)
        assert result["success"] is False
        assert result["batch_complete"] is False
```

- [ ] **Step 2: Run** → FAIL.

- [ ] **Step 3: Implement**

```python
from app.services.odoo_client import OdooAPIError
from app.services.n8n_webhook import coerce_event_result


    async def validate_batch(self, batch_id, picker_identity=None) -> dict[str, Any]:
        # Member-Picking-IDs für die Backorder-Policy (No-Backorder) laden.
        batches = await self._odoo.search_read(
            "stock.picking.batch", [("id", "=", batch_id)], ["picking_ids"], limit=1)
        member_ids = (batches[0].get("picking_ids", []) if batches else []) or []
        try:
            result = await self._odoo.call_method(
                "stock.picking.batch", "action_done", [batch_id],
                context={"skip_backorder": True,
                         "picking_ids_not_to_backorder": member_ids,
                         "skip_sms": True},
            )
        except OdooAPIError as exc:
            return {"success": False, "message": f"Batch-Abschluss fehlgeschlagen: {exc}",
                    "batch_complete": False}
        # action_done gibt bei offenen Rückfragen ein Wizard-Action-Dict zurück statt zu validieren.
        if isinstance(result, dict) and result.get("res_model"):
            return {"success": False, "batch_complete": False,
                    "pending_action": result.get("res_model"),
                    "message": ("Batch-Abschluss erfordert eine manuelle Bestätigung in Odoo "
                                f"({result.get('res_model')}).")}
        completed_by = "mobile-picking-assistant"
        user_id = False
        if picker_identity and getattr(picker_identity, "user_id", None):
            completed_by = getattr(picker_identity, "picker_name", None) or completed_by
            user_id = picker_identity.user_id
        event = coerce_event_result(await self._n8n.fire_event(
            "batch-confirmed",
            {"batch_id": batch_id, "completed_by": completed_by, "completed_by_user_id": user_id},
            picker={"user_id": user_id or None, "name": completed_by},
        ))
        if not event.delivered:
            return {"success": True, "message": "Batch abgeschlossen, n8n-Folgeprozess degradiert.",
                    "batch_complete": True, "integration_status": "degraded",
                    "integration_error": event.error}
        return {"success": True, "message": "Batch abgeschlossen.", "batch_complete": True}
```

- [ ] **Step 4: Run** `pytest tests/test_cluster_service.py::TestValidateBatch -v` → PASS. Dann gesamte Datei: `pytest tests/test_cluster_service.py -v`.

- [ ] **Step 5: Commit + push**

```bash
git add backend/app/services/cluster_service.py backend/tests/test_cluster_service.py
git commit -m "feat(cluster): validate_batch via action_done + batch-confirmed n8n event (TDD)"
git push
```

---

### Task 7: Router `/api/cluster/*` + Wiring

**Files:**
- Create: `backend/app/routers/cluster.py`
- Modify: `backend/app/main.py` (eine `include_router`-Zeile + Import)
- Modify: `backend/app/dependencies.py` (additiver `get_cluster_service`-Provider)
- Test: `backend/tests/test_cluster_routes.py`

**Interfaces:**
- Consumes: `ClusterService`, `get_required_picker_identity`, `get_write_request_context`, `MobileWorkflowService` Idempotenz.
- Produces Endpoints: `GET /api/cluster/suggestions`, `POST /api/cluster/batches` (body `{picking_ids:[int]}`), `GET /api/cluster/batches/{id}`, `POST /api/cluster/batches/{id}/confirm-line` (body `{picking_id, move_line_id, scanned_barcode?, quantity?, serial_number?}`), `POST /api/cluster/batches/{id}/validate`.

- [ ] **Step 1: Write the failing test** (FastAPI TestClient mit Dependency-Override; Muster aus `test_mobile_routes.py`)

```python
# backend/tests/test_cluster_routes.py
import pytest
from unittest.mock import AsyncMock
from fastapi.testclient import TestClient
from app.main import app
from app.dependencies import get_cluster_service, get_required_picker_identity
from app.services.mobile_workflow import PickerIdentity


@pytest.fixture
def cluster_service():
    return AsyncMock()


@pytest.fixture
def client(cluster_service):
    app.dependency_overrides[get_cluster_service] = lambda: cluster_service
    app.dependency_overrides[get_required_picker_identity] = lambda: PickerIdentity(user_id=7)
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_get_suggestions(client, cluster_service):
    cluster_service.suggest_batches.return_value = [{"zone": "Links", "picking_ids": [1, 2]}]
    resp = client.get("/api/cluster/suggestions", headers={"X-Picker-User-Id": "7"})
    assert resp.status_code == 200
    assert resp.json()[0]["zone"] == "Links"


def test_create_batch(client, cluster_service):
    cluster_service.create_batch.return_value = {"batch_id": 99}
    resp = client.post("/api/cluster/batches", json={"picking_ids": [1, 2]},
                       headers={"X-Picker-User-Id": "7", "X-Device-Id": "d1"})
    assert resp.status_code == 200
    assert resp.json()["batch_id"] == 99
```

- [ ] **Step 2: Run** `cd backend && python -m pytest tests/test_cluster_routes.py -v` → FAIL (`cannot import name 'get_cluster_service'`).

- [ ] **Step 3: Implement**

`dependencies.py` (additiv):
```python
from app.services.cluster_service import ClusterService

def get_cluster_service() -> ClusterService:
    return ClusterService(get_odoo_client(), get_n8n_client())
```

`routers/cluster.py` (neu):
```python
"""Cluster-/Batch-Picking-Endpoints."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.dependencies import (
    get_cluster_service, get_required_picker_identity,
    get_mobile_workflow_service, get_write_request_context,
)
from app.services.mobile_workflow import PickerIdentity, WriteRequestContext

router = APIRouter()


class CreateBatchRequest(BaseModel):
    picking_ids: list[int]


class ClusterConfirmRequest(BaseModel):
    picking_id: int
    move_line_id: int
    scanned_barcode: str = ""
    quantity: float = 0
    serial_number: str = ""


@router.get("/cluster/suggestions")
async def cluster_suggestions(_id: PickerIdentity = Depends(get_required_picker_identity),
                              service=Depends(get_cluster_service)):
    return await service.suggest_batches()


@router.post("/cluster/batches")
async def create_cluster_batch(body: CreateBatchRequest,
                               identity: PickerIdentity = Depends(get_required_picker_identity),
                               service=Depends(get_cluster_service)):
    if not body.picking_ids:
        raise HTTPException(status_code=400, detail="picking_ids darf nicht leer sein.")
    return await service.create_batch(body.picking_ids, picker_identity=identity)


@router.get("/cluster/batches/{batch_id}")
async def get_cluster_batch(batch_id: int,
                            _id: PickerIdentity = Depends(get_required_picker_identity),
                            service=Depends(get_cluster_service)):
    result = await service.get_batch(batch_id)
    if result.get("error"):
        raise HTTPException(status_code=404, detail=result["error"])
    return result


@router.post("/cluster/batches/{batch_id}/confirm-line")
async def confirm_cluster_line(batch_id: int, body: ClusterConfirmRequest,
                               identity: PickerIdentity = Depends(get_required_picker_identity),
                               service=Depends(get_cluster_service)):
    return await service.confirm_cluster_line(
        batch_id, body.picking_id, body.move_line_id,
        scanned_barcode=body.scanned_barcode, quantity=body.quantity,
        serial_number=body.serial_number, picker_identity=identity)


@router.post("/cluster/batches/{batch_id}/validate")
async def validate_cluster_batch(batch_id: int,
                                 identity: PickerIdentity = Depends(get_required_picker_identity),
                                 service=Depends(get_cluster_service)):
    return await service.validate_batch(batch_id, picker_identity=identity)
```

`main.py` (additiv): Import `cluster` ergänzen und
```python
app.include_router(cluster.router, prefix="/api", tags=["cluster"])
```

- [ ] **Step 4: Run** `cd backend && python -m pytest tests/test_cluster_routes.py -v` → PASS. Dann `python -m pytest -q` (gesamte Suite grün, keine Regression).

- [ ] **Step 5: Commit + push**

```bash
git add backend/app/routers/cluster.py backend/app/main.py backend/app/dependencies.py backend/tests/test_cluster_routes.py
git commit -m "feat(cluster): /api/cluster/* router + DI wiring (TestClient TDD)"
git push
```

---

### Task 8: PWA-API-Client (`api.js`)

**Files:**
- Modify: `pwa/js/api.js` (additive Funktionen, Muster wie `getPickings`/`confirmLine`)

**Interfaces:**
- Produces: `getClusterSuggestions(options)`, `createBatch(pickingIds, options)`, `getBatch(batchId, options)`, `confirmClusterLine(batchId, data, options)`, `validateBatch(batchId, options)`.

- [ ] **Step 1: Implement** (additiv ans Ende von `api.js`, vor `healthCheck` o. ä.)

```javascript
export async function getClusterSuggestions(options = {}) {
    return request('GET', '/cluster/suggestions', null, { headers: getReadHeaders(), signal: options.signal });
}

export async function createBatch(pickingIds, options = {}) {
    return request('POST', '/cluster/batches', { picking_ids: pickingIds }, {
        headers: getWriteHeaders(options.idempotencyKey), signal: options.signal });
}

export async function getBatch(batchId, options = {}) {
    return request('GET', `/cluster/batches/${batchId}`, null, { headers: getReadHeaders(), signal: options.signal });
}

export async function confirmClusterLine(batchId, data, options = {}) {
    return request('POST', `/cluster/batches/${batchId}/confirm-line`, data, {
        headers: getWriteHeaders(options.idempotencyKey), signal: options.signal });
}

export async function validateBatch(batchId, options = {}) {
    return request('POST', `/cluster/batches/${batchId}/validate`, null, {
        headers: getWriteHeaders(options.idempotencyKey), signal: options.signal });
}
```

- [ ] **Step 2: Verify** kein Build-Bruch: `make verify-ui` (oder `workflow.ps1 verify-ui`) startet — zumindest Lint/Import; Funktionsnamen kollidieren nicht.

- [ ] **Step 3: Commit + push**

```bash
git add pwa/js/api.js
git commit -m "feat(cluster/pwa): api.js client for /cluster/* endpoints"
git push
```

---

### Task 9: PWA Cluster-Auswahl-View (Design zuerst)

> **REQUIRED SUB-SKILL vor diesem Task:** `frontend-design` — bestehendes System aus `.design/picking-pwa/DESIGN_BRIEF.md` + `pwa/css/app.css` übernehmen (Tokens, `.pick-list-card`, mobile-first, Desktop-2-Spalten). Kein generischer Look.

**Files:**
- Modify: `pwa/js/app.js` (additive Funktionen + neue View-States `cluster_select`)
- Modify: `pwa/css/app.css` (additive `.cluster-*`-Klassen)

**Interfaces:**
- Consumes: `getClusterSuggestions`, `createBatch` aus `api.js`.
- Produces: `enterClusterMode()`, `renderClusterSelect(suggestions, openPickings)`, State `view === 'cluster_select'` mit `selectedPickingIds: Set`.

- [ ] **Step 1:** Einstiegspunkt additiv — Button „Batch starten" in der Listen-View (`renderPickingsView`/Workspace-Header), der `enterClusterMode()` ruft. Bestehende Card-Click-Logik bleibt unangetastet (kein Eingriff in `handleConfirmAll`).
- [ ] **Step 2:** `enterClusterMode()` lädt `getClusterSuggestions()` + bestehende `getPickings()`, setzt `setState({view:'cluster_select', clusterSuggestions, clusterOpenPickings, selectedPickingIds:new Set()})`.
- [ ] **Step 3:** `renderClusterSelect(...)` zeigt Vorschlags-Karten (Zone, #Aufträge) mit „Vorschlag übernehmen" (füllt Set) + Liste aller offenen Aufträge mit Checkbox-Toggle (manuelle Korrektur). Footer-Button „Batch starten (N)" ruft `createBatch([...selectedPickingIds])` → bei Erfolg `loadBatch(batch_id)` (Task 10).
- [ ] **Step 4:** CSS additive Klassen: `.cluster-suggestion-card`, `.cluster-pick-toggle`, `.cluster-start-bar` — Tokens/Radien aus `:root` wiederverwenden, Touch-Targets ≥ 48px.
- [ ] **Step 5: Verify** `make verify-ui` + `make verify-visual` (neuer Screen erscheint im Index). 
- [ ] **Step 6: Commit + push** `feat(cluster/pwa): batch selection view (suggestions + manual multi-select)`

---

### Task 10: PWA Cluster-Rundgang-View (Sammelliste + Confirm + Serial + Voice)

**Files:**
- Modify: `pwa/js/app.js` (View-State `cluster_walk`)
- Modify: `pwa/css/app.css`

**Interfaces:**
- Consumes: `getBatch`, `confirmClusterLine`, bestehendes Serial-Modal (`showSerialModal`/Pattern bei `app.js:2235`), `speak()` aus `voice.js`.
- Produces: `loadBatch(batchId)`, `renderClusterWalk(batch)`, `handleClusterConfirm(line)`.

- [ ] **Step 1:** `loadBatch(batchId)` ruft `getBatch`, `setState({view:'cluster_walk', batch})`.
- [ ] **Step 2:** `renderClusterWalk(batch)` rendert Fortschritts-Header (`progress.done/total`, Box-Legende aus `batch.boxes` farbcodiert) + route-sortierte Positionsliste. Jede Position: Lagerplatz prominent (Design-Prinzip „Ort vor Inhalt"), farbiger **Box-Tag** (`box_color`/`box_index` + `picking_name`), Menge, Voice-Button (`speak(line.voice_instruction_short)`), Confirm-Button.
- [ ] **Step 3:** `handleClusterConfirm(line)`: bei `line.tracking in ('serial','lot')` zuerst bestehendes Serial-Modal öffnen → dann `confirmClusterLine(batch.batch_id, {picking_id, move_line_id, scanned_barcode, quantity, serial_number})`; danach `loadBatch` refresh + `feedbackSuccess()`.
- [ ] **Step 4:** „Batch abschließen"-Button im Header, aktiv wenn `progress.done === progress.total` → ruft `validateBatch` (Task 11).
- [ ] **Step 5:** CSS: `.cluster-stop`, `.cluster-box-tag`, `.cluster-progress` — Box-Farbe als linker Border/Chip; ≥48px Targets; AAA-Kontrast für Ort/Menge/Confirm.
- [ ] **Step 6: Verify** `make verify-ui` + `make verify-visual` + `make verify-a11y`.
- [ ] **Step 7: Commit + push** `feat(cluster/pwa): cluster walk view (route list, box tags, serial, voice)`

---

### Task 11: PWA Batch-Abschluss

**Files:** Modify `pwa/js/app.js`, `pwa/css/app.css`

- [ ] **Step 1:** `handleValidateBatch()` ruft `validateBatch(batchId)`; bei `batch_complete` Erfolgs-View (`renderClusterComplete`) mit Zusammenfassung (#Aufträge, #Positionen), Buttons „Zur Liste" / „Neuer Batch".
- [ ] **Step 2:** `integration_status === 'degraded'` → Warn-Toast „n8n-Folgeprozess degradiert, bitte prüfen".
- [ ] **Step 3:** CSS additive `.cluster-complete`.
- [ ] **Step 4: Verify** `make verify-ui` + `make verify-visual`.
- [ ] **Step 5: Commit + push** `feat(cluster/pwa): batch completion view + degraded handling`

---

### Task 12: E2E + Visual + a11y

**Files:**
- Create: `e2e/cluster.spec.js` (Playwright, gemockte `/api/cluster/*`-Responses — Muster aus bestehenden Specs/`test-visual` mit gemockter API)
- Modify: ggf. `e2e/visual.spec.js` (Baseline für Cluster-Screens) — nur wenn bewusst gewollt.

- [ ] **Step 1:** Spec: Picker wählen → „Batch starten" → 2 Aufträge wählen → Batch anlegen (gemockt) → Sammelliste sichtbar mit Box-Tags → Position bestätigen (Serial-Pfad) → „Batch abschließen" → Erfolg.
- [ ] **Step 2:** Run `make test-ui` (bzw. `workflow.ps1 test-ui`) → grün.
- [ ] **Step 3:** `make verify-visual` Artefakte prüfen; optional `make test-visual-diff-update` für neue Baselines, wenn Layout final.
- [ ] **Step 4:** `make verify-a11y` für die neuen Views.
- [ ] **Step 5: Commit + push** `test(cluster): e2e + visual + a11y for cluster picking`

---

### Task 13: Abschluss — Review + Doku

- [ ] **Step 1:** `superpowers:requesting-code-review` über den gesamten Branch-Diff.
- [ ] **Step 2:** Review-Findings beheben (eigene Commits).
- [ ] **Step 3:** Spec/Obsidian/Memory `Verlauf` aktualisieren (Implementierung abgeschlossen), pushen.
- [ ] **Step 4:** **NICHT mergen** — landet als letztes Feature nach den Serial-Fixes (Chat 1 + 2).

---

## Self-Review

**Spec coverage:**
- E1 Odoo-Batch → Tasks 3/6 (create+action_confirm, action_done). ✓
- E2 Auto-Vorschlag + manuell → Tasks 2 (suggest) + 9 (select UI mit beidem). ✓
- E3 erst picken, dann validieren → Task 5 (confirm ohne validate) + Task 6 (validate_batch). ✓
- E4 Serial → Task 5 + Task 10; Box → Task 1 + Task 10; Voice → Task 10; n8n-Event → Task 6. ✓
- E5 Box nur logisch → Task 1 (assign_boxes, kein result_package_id). ✓
- E6 `/api/cluster/*` → Task 7. ✓
- Fehlerbehandlung (Modul fehlt/Barcode/Backorder) → Task 5 (Barcode), Task 6 (action_done-Fehler degraded). Modul-fehlt-Hinweis: action_done/create wirft OdooAPIError → in Task 6 abgefangen; expliziter 501 optional. ✓
- Tests → Tasks 1–7 (pytest) + Task 12 (Playwright/visual/a11y). ✓

**Placeholder scan:** Alle Code-Steps enthalten echten Code. Frontend-Tasks (9–12) sind absichtlich schrittbasiert ohne vollständigen Vanilla-JS-Dump, da additive Renderer + `frontend-design`-Skill den finalen Stil bestimmen — die Interfaces/Funktionsnamen sind aber festgelegt.

**Type consistency:** `assign_boxes`/`build_cluster_lines`/`ClusterService.*` Signaturen identisch zwischen Definition (Tasks 1–6) und Router-Konsum (Task 7) und api.js (Task 8). Felder `box_index`/`box_color`/`picking_id`/`voice_instruction_short`/`progress{total,done,ratio}` durchgängig gleich benannt.
