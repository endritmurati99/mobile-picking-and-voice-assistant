# Cluster-Picking Odoo-19 Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Haerte die bestehende Cluster-Picking-Funktion so, dass Batchbildung, Put-to-Box und Demo-Daten fachlich zur Odoo-19-Cluster-Argumentation passen.

**Architecture:** Die vorhandenen Cluster-Dateien bleiben die zentrale Integrationsstelle: `ClusterService` bildet Eligibility, Suggestions, Batch-Erstellung und Put-to-Box-Regeln ab; die PWA zeigt und erzwingt dieselben Regeln vor dem Start. Odoo bleibt System of Record, Seed-Daten schreiben realistische Odoo-Partner/Pickings statt eine lokale Parallelwelt aufzubauen.

**Tech Stack:** Python 3, FastAPI, Pydantic, pytest/pytest-asyncio, Odoo JSON-RPC, Vanilla-JS-PWA, Playwright.

## Global Constraints

- Odoo 19 ist Zielstand; Odoo-18-Legacy-Fallback fuer Package-Modell bleibt erlaubt, solange er bestehende Tests nicht bricht.
- Odoo bleibt System of Record; keine neue Schatten-Datenbank fuer Cluster, Kunden, Versand oder Labeldaten.
- PWA spricht nur ueber FastAPI.
- Cluster-Batch: mindestens 2 Auftraege, maximal 8 Auftraege; 4 bis 8 ist der empfohlene PoC-Bereich.
- Put-to-Box bedeutet ein Wagen mit separaten Kartons/Totes je Auftrag, nicht ein gemeinsamer Karton.
- Fehlendes Odoo-Batch-Modul oder fehlendes `batch_id` muss fail-closed behandelt werden.
- Jede Task arbeitet mit TDD: erst Tests, dann Implementierung, dann gezielte Verifikation.

---

## File Structure

- Modify: `backend/app/services/cluster_service.py` — Eligibility, Suggestions, Authorization, Put-to-Box fail-closed, Batch-Erstellung.
- Modify: `backend/app/routers/cluster.py` — Picker-Identity an Suggestions, Fehlerstatus fuer Create.
- Modify: `backend/tests/test_cluster_service.py` — Service-Regeln und Odoo-Fake-Verhalten.
- Modify: `backend/tests/test_cluster_routes.py` — HTTP-Status und Identity-Weitergabe.
- Modify: `backend/app/services/picking_service.py` — Versand-/Adresskontext fuer Picking-Listen und Details.
- Modify: `backend/tests/test_picking_service.py` — API-Kontrakt fuer Adressen/Versandkontext.
- Modify: `infrastructure/scripts/seed-odoo.py` — realistische Demo-Kunden, Lieferadressen, ausgehende Pickings.
- Modify: `backend/tests/test_seed_odoo_script.py` — Seeder-Verhalten fuer Demo-Daten.
- Modify: `pwa/js/api.js` — falls neue Response-Felder normalisiert werden muessen.
- Modify: `pwa/js/app.js` — Kapazitaetsguard, Kriterienanzeige, Karton fail-closed.
- Modify: `pwa/css/app.css` — kompakte Kriterienchips und Kapazitaetszustand.
- Modify: `e2e/cluster.spec.js` — PWA-Negativfaelle und sichtbare Kriterien.
- Update: `Projekt-Wiki/12 - Funktionsdokumentation/10 - Cluster-Picking Odoo-19 Audit und Haertungsplan.md` — Abschlussnotiz nach Umsetzung.

---

### Task 1: Backend Capacity, Batch Availability, Authorization

**Files:**
- Modify: `backend/app/services/cluster_service.py`
- Modify: `backend/app/routers/cluster.py`
- Test: `backend/tests/test_cluster_service.py`
- Test: `backend/tests/test_cluster_routes.py`

**Interfaces:**
- Produces: `CLUSTER_MIN_ORDERS`, `CLUSTER_RECOMMENDED_MIN_ORDERS`, `CLUSTER_MAX_ORDERS`
- Produces: `validate_cluster_capacity(picking_ids: list[int]) -> dict[str, Any]`
- Changes: `ClusterService.suggest_batches(self, picker_identity=None)`
- Changes: `ClusterService.create_batch(self, picking_ids, picker_identity=None)`

- [ ] **Step 1: Write failing capacity and auth tests**

Add tests to `backend/tests/test_cluster_service.py`:

```python
@pytest.mark.anyio
async def test_create_batch_rejects_single_order(service):
    result = await service.create_batch([101], picker_identity=SimpleNamespace(user_id=7))
    assert result["success"] is False
    assert result["code"] == "cluster_capacity"
    assert "mindestens 2" in result["message"]


@pytest.mark.anyio
async def test_create_batch_rejects_more_than_eight_orders(service):
    result = await service.create_batch(list(range(1, 10)), picker_identity=SimpleNamespace(user_id=7))
    assert result["success"] is False
    assert result["code"] == "cluster_capacity"
    assert "maximal 8" in result["message"]


@pytest.mark.anyio
async def test_ownerless_batch_is_forbidden(service, odoo):
    odoo.search_read.return_value = [{"id": 44, "name": "BATCH/44", "state": "in_progress", "picking_ids": [1, 2], "user_id": False}]
    result = await service.get_batch(44, picker_identity=SimpleNamespace(user_id=7))
    assert result == {"error": "Kein Zugriff auf diesen Batch.", "forbidden": True}


@pytest.mark.anyio
async def test_create_batch_missing_batch_field_fails_closed(service, odoo):
    odoo.search_read.side_effect = OdooAPIError("Invalid field 'batch_id' on model 'stock.picking'")
    result = await service.create_batch([1, 2], picker_identity=SimpleNamespace(user_id=7))
    assert result["success"] is False
    assert result["code"] == "stock_picking_batch_unavailable"
```

Add route tests to `backend/tests/test_cluster_routes.py`:

```python
@pytest.mark.anyio
async def test_suggestions_pass_picker_identity(client, cluster_service):
    cluster_service.suggest_batches.return_value = []
    response = await client.get("/api/cluster/suggestions", headers={"X-Picker-User-Id": "7", "X-Device-Id": "dev-1"})
    assert response.status_code == 200
    _, kwargs = cluster_service.suggest_batches.call_args
    assert kwargs["picker_identity"].user_id == 7


@pytest.mark.anyio
async def test_create_batch_maps_capacity_error_to_422(client, cluster_service):
    cluster_service.create_batch.return_value = {
        "success": False,
        "error": "Cluster braucht mindestens 2 Auftraege.",
        "message": "Cluster braucht mindestens 2 Auftraege.",
        "code": "cluster_capacity",
    }
    response = await client.post(
        "/api/cluster/batches",
        json={"picking_ids": [1]},
        headers={"X-Picker-User-Id": "7", "X-Device-Id": "dev-1"},
    )
    assert response.status_code == 422
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
cd backend
PYTHONPATH=.deps python3 -m pytest -p pytest_asyncio tests/test_cluster_service.py tests/test_cluster_routes.py -q
```

Expected: new tests fail because capacity helper, fail-closed ownerless behavior, missing batch fail-closed, and suggestion identity forwarding are not implemented.

- [ ] **Step 3: Implement constants and capacity helper**

In `backend/app/services/cluster_service.py` add below package constants:

```python
CLUSTER_MIN_ORDERS = 2
CLUSTER_RECOMMENDED_MIN_ORDERS = 4
CLUSTER_MAX_ORDERS = 8


def validate_cluster_capacity(picking_ids: list[int]) -> dict[str, Any]:
    unique_ids = sorted({int(pid) for pid in (picking_ids or [])})
    count = len(unique_ids)
    if count < CLUSTER_MIN_ORDERS:
        return {
            "ok": False,
            "code": "cluster_capacity",
            "message": f"Cluster braucht mindestens {CLUSTER_MIN_ORDERS} Auftraege.",
            "picking_ids": unique_ids,
        }
    if count > CLUSTER_MAX_ORDERS:
        return {
            "ok": False,
            "code": "cluster_capacity",
            "message": f"Cluster erlaubt maximal {CLUSTER_MAX_ORDERS} Auftraege pro Wagen.",
            "picking_ids": unique_ids,
        }
    return {"ok": True, "picking_ids": unique_ids, "count": count}
```

At the start of `create_batch`, replace the current raw id handling with:

```python
capacity = validate_cluster_capacity(picking_ids)
if not capacity["ok"]:
    return {
        "success": False,
        "error": capacity["message"],
        "message": capacity["message"],
        "code": capacity["code"],
    }
ids = capacity["picking_ids"]
```

- [ ] **Step 4: Make batch support and owner auth fail-closed**

In `create_batch`, remove the fallback that retries without `batch_id`. Replace the missing field branch with:

```python
if _is_missing_batch_field_error(exc):
    logger.error("create_batch: stock_picking_batch nicht verfuegbar: %s", exc)
    return {
        "success": False,
        "error": "Cluster-Picking ist in dieser Odoo-Instanz nicht verfuegbar.",
        "message": "Cluster-Picking ist in dieser Odoo-Instanz nicht verfuegbar.",
        "code": "stock_picking_batch_unavailable",
        "unavailable": True,
    }
```

Change `_is_authorized` to require an owner match:

```python
owner_id = self._owner_id(batch)
if owner_id is None:
    return False
return owner_id == requester_id
```

- [ ] **Step 5: Pass picker identity and map create errors**

In `backend/app/routers/cluster.py`, change suggestions:

```python
return await service.suggest_batches(picker_identity=_identity)
```

In `create_cluster_batch`, after service call:

```python
result = await service.create_batch(body.picking_ids, picker_identity=identity)
if result.get("forbidden"):
    raise HTTPException(status_code=403, detail=result.get("message") or result.get("error"))
if result.get("code") == "cluster_capacity":
    raise HTTPException(status_code=422, detail=result.get("message") or result.get("error"))
if result.get("code") == "stock_picking_batch_unavailable" or result.get("unavailable"):
    raise HTTPException(status_code=503, detail=result.get("message") or result.get("error"))
if result.get("error"):
    raise HTTPException(status_code=409, detail=result["error"])
return result
```

- [ ] **Step 6: Run verification**

Run:

```bash
cd backend
PYTHONPATH=.deps python3 -m pytest -p pytest_asyncio tests/test_cluster_service.py tests/test_cluster_routes.py -q
```

Expected: cluster service and route tests pass.

- [ ] **Step 7: Commit**

```bash
git add backend/app/services/cluster_service.py backend/app/routers/cluster.py backend/tests/test_cluster_service.py backend/tests/test_cluster_routes.py
git commit -m "fix(cluster): enforce capacity and fail-closed batch ownership"
```

---

### Task 2: Backend Eligibility and Scored Suggestions

**Files:**
- Modify: `backend/app/services/cluster_service.py`
- Test: `backend/tests/test_cluster_service.py`

**Interfaces:**
- Produces: `build_cluster_rule_report(candidates: list[dict[str, Any]]) -> dict[str, Any]`
- Changes: `suggest_batches` response includes `score`, `reasons`, `warnings`, `delivery_date`, `product_overlap_count`
- Changes: `create_batch` rejects mixed company, mixed delivery day, and zero product overlap

- [ ] **Step 1: Write failing eligibility tests**

Add tests:

```python
@pytest.mark.anyio
async def test_create_batch_rejects_mixed_company(service, odoo):
    odoo.search_read.side_effect = [
        [
            {"id": 1, "name": "OUT/1", "company_id": [1, "A"], "scheduled_date": "2026-07-09 08:00:00", "batch_id": False},
            {"id": 2, "name": "OUT/2", "company_id": [2, "B"], "scheduled_date": "2026-07-09 08:00:00", "batch_id": False},
        ]
    ]
    result = await service.create_batch([1, 2], picker_identity=SimpleNamespace(user_id=7))
    assert result["success"] is False
    assert result["code"] == "mixed_company"


@pytest.mark.anyio
async def test_create_batch_rejects_mixed_delivery_date(service, odoo):
    odoo.search_read.side_effect = [
        [
            {"id": 1, "name": "OUT/1", "company_id": [1, "A"], "scheduled_date": "2026-07-09 08:00:00", "batch_id": False},
            {"id": 2, "name": "OUT/2", "company_id": [1, "A"], "scheduled_date": "2026-07-10 08:00:00", "batch_id": False},
        ],
        [
            {"id": 10, "picking_id": [1, "OUT/1"], "location_id": [5, "WH/Stock/Links/A1"], "product_id": [100, "SKU-A"]},
            {"id": 20, "picking_id": [2, "OUT/2"], "location_id": [6, "WH/Stock/Links/A2"], "product_id": [100, "SKU-A"]},
        ],
    ]
    result = await service.create_batch([1, 2], picker_identity=SimpleNamespace(user_id=7))
    assert result["success"] is False
    assert result["code"] == "mixed_delivery_date"


@pytest.mark.anyio
async def test_suggest_batches_returns_reasons_and_score(service, odoo):
    async def fake_search_read(model, domain, fields, limit=100):
        if model == "stock.picking":
            return [
                {"id": 1, "name": "OUT/1", "batch_id": False, "company_id": [1, "A"], "scheduled_date": "2026-07-09 08:00:00", "partner_id": [50, "ACME GmbH"]},
                {"id": 2, "name": "OUT/2", "batch_id": False, "company_id": [1, "A"], "scheduled_date": "2026-07-09 10:00:00", "partner_id": [51, "Meyer KG"]},
            ]
        if model == "stock.move.line":
            return [
                {"id": 10, "picking_id": [1, "OUT/1"], "location_id": [5, "WH/Stock/Links/A1"], "product_id": [100, "SKU-A"]},
                {"id": 11, "picking_id": [1, "OUT/1"], "location_id": [6, "WH/Stock/Links/A2"], "product_id": [101, "SKU-B"]},
                {"id": 20, "picking_id": [2, "OUT/2"], "location_id": [7, "WH/Stock/Links/A3"], "product_id": [100, "SKU-A"]},
            ]
        raise AssertionError(model)
    odoo.search_read.side_effect = fake_search_read
    result = await service.suggest_batches(picker_identity=SimpleNamespace(user_id=7))
    assert result[0]["delivery_date"] == "2026-07-09"
    assert result[0]["product_overlap_count"] == 1
    assert result[0]["score"] > 0
    assert any("Ausliefertag" in reason for reason in result[0]["reasons"])
```

- [ ] **Step 2: Run tests to verify failure**

```bash
cd backend
PYTHONPATH=.deps python3 -m pytest -p pytest_asyncio tests/test_cluster_service.py -q
```

Expected: new eligibility tests fail.

- [ ] **Step 3: Implement candidate helpers**

Add helpers near `_zone_of`:

```python
def _many2one_id(value: Any) -> int | None:
    if isinstance(value, list) and value:
        return int(value[0])
    if isinstance(value, int):
        return value
    return None


def _many2one_name(value: Any) -> str:
    if isinstance(value, list) and len(value) > 1:
        return str(value[1] or "")
    return ""


def _date_key(value: Any) -> str:
    raw = str(value or "").strip()
    return raw[:10] if len(raw) >= 10 else ""
```

Add a report builder:

```python
def build_cluster_rule_report(candidates: list[dict[str, Any]]) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []
    reasons: list[str] = []

    capacity = validate_cluster_capacity([c["id"] for c in candidates])
    if not capacity["ok"]:
        errors.append(capacity["code"])

    companies = {c.get("company_id") for c in candidates if c.get("company_id") is not None}
    if len(companies) > 1:
        errors.append("mixed_company")

    delivery_dates = {c.get("delivery_date") for c in candidates if c.get("delivery_date")}
    if len(delivery_dates) > 1:
        errors.append("mixed_delivery_date")

    product_sets = [set(c.get("product_ids", [])) for c in candidates]
    overlap = set.intersection(*product_sets) if product_sets and all(product_sets) else set()
    if len(candidates) > 1 and not overlap:
        errors.append("no_product_overlap")

    zones = [c.get("primary_zone") for c in candidates if c.get("primary_zone")]
    if len(set(zones)) == 1 and zones:
        reasons.append(f"Zone {zones[0]}")
    if delivery_dates:
        reasons.append(f"Ausliefertag {sorted(delivery_dates)[0]}")
    if overlap:
        reasons.append(f"{len(overlap)} gemeinsame Produkte")

    score = 0
    if not errors:
        score += 40
    if delivery_dates:
        score += 20
    if zones and len(set(zones)) == 1:
        score += 20
    score += min(20, len(overlap) * 5)

    count = len(candidates)
    if CLUSTER_MIN_ORDERS <= count < CLUSTER_RECOMMENDED_MIN_ORDERS:
        warnings.append(f"{count} Auftraege sind gueltig, empfohlen sind {CLUSTER_RECOMMENDED_MIN_ORDERS}-{CLUSTER_MAX_ORDERS}.")

    return {
        "eligible": not errors,
        "errors": errors,
        "warnings": warnings,
        "reasons": reasons,
        "score": min(score, 100),
        "product_overlap_count": len(overlap),
        "delivery_date": sorted(delivery_dates)[0] if len(delivery_dates) == 1 else "",
    }
```

- [ ] **Step 4: Enrich `suggest_batches`**

Change `suggest_batches` to read picking fields:

```python
["name", "batch_id", "company_id", "scheduled_date", "date_deadline", "partner_id"]
```

Change move-line fields to include products:

```python
["picking_id", "location_id", "product_id"]
```

Build candidate dicts per picking:

```python
candidate = {
    "id": picking_id,
    "name": name_by_id[picking_id],
    "company_id": _many2one_id(picking.get("company_id")),
    "delivery_date": _date_key(picking.get("date_deadline") or picking.get("scheduled_date")),
    "partner_name": _many2one_name(picking.get("partner_id")),
    "primary_zone": zone_by_picking.get(picking_id, "Unbekannt"),
    "product_ids": sorted(product_ids_by_picking.get(picking_id, set())),
}
```

Group by `(delivery_date, primary_zone)`, run `build_cluster_rule_report`, and return groups with:

```python
{
    "zone": zone,
    "delivery_date": report["delivery_date"],
    "picking_ids": pids,
    "order_count": len(pids),
    "line_count": data["line_count"],
    "picking_names": [name_by_id[p] for p in pids],
    "score": report["score"],
    "reasons": report["reasons"],
    "warnings": report["warnings"],
    "product_overlap_count": report["product_overlap_count"],
}
```

- [ ] **Step 5: Apply same report to manual create**

After `allowed` is loaded in `create_batch`, read move-lines for `allowed_ids`, build candidates with the same helper logic, and reject:

```python
if not report["eligible"]:
    code = report["errors"][0]
    messages = {
        "mixed_company": "Cluster darf keine Pickings aus mehreren Companies enthalten.",
        "mixed_delivery_date": "Cluster-Pickings brauchen denselben Ausliefertag.",
        "no_product_overlap": "Cluster braucht Produktueberlappung zwischen den Auftraegen.",
    }
    return {
        "success": False,
        "error": messages.get(code, "Cluster-Auswahl ist fachlich nicht gueltig."),
        "message": messages.get(code, "Cluster-Auswahl ist fachlich nicht gueltig."),
        "code": code,
        "eligibility": report,
    }
```

- [ ] **Step 6: Run verification**

```bash
cd backend
PYTHONPATH=.deps python3 -m pytest -p pytest_asyncio tests/test_cluster_service.py -q
```

Expected: service tests pass.

- [ ] **Step 7: Commit**

```bash
git add backend/app/services/cluster_service.py backend/tests/test_cluster_service.py
git commit -m "feat(cluster): score suggestions with delivery and product overlap"
```

---

### Task 3: Required Put-to-Box and Carton Fail-Closed

**Files:**
- Modify: `backend/app/services/cluster_service.py`
- Modify: `pwa/js/app.js`
- Test: `backend/tests/test_cluster_service.py`
- Test: `e2e/cluster.spec.js`

**Interfaces:**
- Changes: Package assignment failure aborts new batch before returning it to PWA.
- Changes: `confirm_cluster_line` rejects missing `result_package_id` in cluster mode.
- Produces PWA helper: `resolveClusterPackageToken(line, boxes) -> string`

- [ ] **Step 1: Write failing backend tests**

```python
@pytest.mark.anyio
async def test_create_batch_aborts_when_package_assignment_fails(service, odoo, monkeypatch):
    async def fail_assign(_ids):
        raise OdooAPIError("package create failed")
    monkeypatch.setattr(service, "_assign_packages", fail_assign)
    odoo.search_read.return_value = [
        {"id": 1, "name": "OUT/1", "company_id": [1, "A"], "scheduled_date": "2026-07-09 08:00:00", "batch_id": False},
        {"id": 2, "name": "OUT/2", "company_id": [1, "A"], "scheduled_date": "2026-07-09 08:00:00", "batch_id": False},
    ]
    odoo.create.return_value = 55
    result = await service.create_batch([1, 2], picker_identity=SimpleNamespace(user_id=7))
    assert result["success"] is False
    assert result["code"] == "package_assignment_failed"
    odoo.call_method.assert_any_await("stock.picking.batch", "action_cancel", [55])


@pytest.mark.anyio
async def test_confirm_cluster_line_without_package_fails_closed(service, odoo):
    odoo.search_read.side_effect = [
        [{"id": 9, "product_id": [100, "A"], "quantity": 1, "move_id": [200, "M"], "location_id": [5, "L"], "result_package_id": False, "lot_id": False}],
        [{"id": 100, "barcode": "ABC", "tracking": "none"}],
    ]
    result = await service.confirm_cluster_line(1, 2, 9, picker_identity=SimpleNamespace(user_id=7))
    assert result["success"] is False
    assert result["carton_required"] is True
```

- [ ] **Step 2: Run tests to verify failure**

```bash
cd backend
PYTHONPATH=.deps python3 -m pytest -p pytest_asyncio tests/test_cluster_service.py -q
```

- [ ] **Step 3: Make package assignment required**

Move `_assign_packages(allowed_ids)` before `action_confirm`. If `_assign_packages` raises, cancel the draft batch and return:

```python
try:
    await self._assign_packages(allowed_ids)
except Exception as exc:
    logger.error("create_batch: Package-Zuweisung fehlgeschlagen (batch %s): %s", batch_id, exc)
    try:
        await self._odoo.call_method("stock.picking.batch", "action_cancel", [batch_id])
    except OdooAPIError as cancel_exc:
        logger.error("create_batch: action_cancel nach Package-Fehler fehlgeschlagen (batch %s): %s", batch_id, cancel_exc)
    return {
        "success": False,
        "error": "Zielkartons konnten nicht angelegt werden.",
        "message": "Zielkartons konnten nicht angelegt werden.",
        "code": "package_assignment_failed",
    }
```

- [ ] **Step 4: Make confirm fail closed without target package**

In `confirm_cluster_line`, before accepting quantity writes:

```python
if expected_pkg_id is None:
    self._emit_cluster_confirm(False, batch_id, picking_id, move_line_id, product_id, False, t0, carton_ok=False)
    return {
        "success": False,
        "carton_required": True,
        "missing_package": True,
        "message": "Cluster-Position hat keinen Zielkarton. Batch bitte neu bilden.",
        "progress": None,
    }
```

- [ ] **Step 5: Add PWA package resolver**

In `pwa/js/app.js` near cluster helpers:

```javascript
function resolveClusterPackageToken(line, boxes = []) {
    if (line?.package_name) return String(line.package_name);
    if (line?.package_id) return String(line.package_id);
    const box = (boxes || []).find((item) => Number(item.picking_id) === Number(line?.picking_id));
    if (box?.package_name) return String(box.package_name);
    if (box?.package_id) return String(box.package_id);
    return '';
}
```

In `handleClusterConfirm`, replace the conditional package check with:

```javascript
const packageToken = resolveClusterPackageToken(line, batch.boxes);
if (!packageToken) {
    showToast('Zielkarton fehlt. Batch bitte neu laden oder neu bilden.', 'error');
    reenableBtn();
    return;
}
const scannedPackage = await askCartonConfirm({ ...line, package_name: packageToken }, batch.boxes);
if (!scannedPackage) {
    reenableBtn();
    return;
}
```

- [ ] **Step 6: Run verification**

```bash
cd backend
PYTHONPATH=.deps python3 -m pytest -p pytest_asyncio tests/test_cluster_service.py -q

cd ..
npx playwright test e2e/cluster.spec.js
```

Expected: backend tests and existing cluster e2e pass; add one e2e case if current fixtures can simulate missing package.

- [ ] **Step 7: Commit**

```bash
git add backend/app/services/cluster_service.py backend/tests/test_cluster_service.py pwa/js/app.js e2e/cluster.spec.js
git commit -m "fix(cluster): require put-to-box packages"
```

---

### Task 4: PWA Cluster Governance UI

**Files:**
- Modify: `pwa/js/app.js`
- Modify: `pwa/css/app.css`
- Test: `e2e/cluster.spec.js`

**Interfaces:**
- Produces: `getClusterSelectionStatus(selectedIds: number[]) -> { ok: boolean, message: string }`
- Renders: capacity `n/8`, suggestion reason chips, delivery date, score, and separate-carton legend

- [ ] **Step 1: Write failing Playwright tests**

Add to `e2e/cluster.spec.js`:

```javascript
test('Cluster-Auswahl sperrt Einzelauftrag und Ueberladung', async ({ page }) => {
  await openClusterSelect(page);
  await page.locator('[data-cluster-pick-id]').first().click();
  await expect(page.locator('[data-cluster-confirm]')).toBeDisabled();
  await expect(page.getByText(/mindestens 2/i)).toBeVisible();
});

test('Cluster-Vorschlag zeigt fachliche Gruende', async ({ page }) => {
  await openClusterSelect(page);
  await expect(page.getByText(/Ausliefertag/i)).toBeVisible();
  await expect(page.getByText(/gemeinsame Produkte/i)).toBeVisible();
  await expect(page.getByText(/separate Kartons/i)).toBeVisible();
});
```

- [ ] **Step 2: Run tests to verify failure**

```bash
npx playwright test e2e/cluster.spec.js
```

- [ ] **Step 3: Add PWA constants and selection status**

In `pwa/js/app.js` near cluster helpers:

```javascript
const CLUSTER_MIN_ORDERS = 2;
const CLUSTER_RECOMMENDED_MIN_ORDERS = 4;
const CLUSTER_MAX_ORDERS = 8;

function getClusterSelectionStatus(selectedIds) {
    const count = selectedIds.length;
    if (count < CLUSTER_MIN_ORDERS) {
        return { ok: false, message: `Mindestens ${CLUSTER_MIN_ORDERS} Aufträge wählen.` };
    }
    if (count > CLUSTER_MAX_ORDERS) {
        return { ok: false, message: `Maximal ${CLUSTER_MAX_ORDERS} Aufträge pro Wagen.` };
    }
    if (count < CLUSTER_RECOMMENDED_MIN_ORDERS) {
        return { ok: true, message: `Gültig; empfohlen sind ${CLUSTER_RECOMMENDED_MIN_ORDERS}-${CLUSTER_MAX_ORDERS}.` };
    }
    return { ok: true, message: `${count}/${CLUSTER_MAX_ORDERS} Aufträge im Wagen.` };
}
```

- [ ] **Step 4: Render criteria and disable start**

In `renderClusterSelect`, calculate:

```javascript
const ids = Array.from(selected);
const status = getClusterSelectionStatus(ids);
```

Render suggestion chips:

```javascript
const reasonChips = Array.isArray(group.reasons)
    ? group.reasons.map((reason) => `<span class="cluster-rule-chip">${escapeHtml(reason)}</span>`).join('')
    : '';
```

Update the start button:

```html
<div class="cluster-capacity ${status.ok ? 'cluster-capacity--ok' : 'cluster-capacity--bad'}">
    ${escapeHtml(status.message)}
</div>
<button type="button" class="btn-big btn-big--primary cluster-start"
    data-cluster-confirm ${status.ok ? '' : 'disabled'}>
    Batch starten${count ? ` (${count}/${CLUSTER_MAX_ORDERS})` : ''}
</button>
```

In `createClusterBatch`, fail before API:

```javascript
const status = getClusterSelectionStatus(ids);
if (!status.ok) {
    showToast(status.message, 'error');
    return;
}
```

- [ ] **Step 5: Add CSS**

In `pwa/css/app.css`:

```css
.cluster-rule-chip,
.cluster-capacity {
  display: inline-flex;
  align-items: center;
  min-height: 28px;
  padding: 0 10px;
  border-radius: 8px;
  font-size: 0.82rem;
  line-height: 1.2;
  background: var(--surface-muted);
  color: var(--text-secondary);
}

.cluster-capacity--ok {
  background: color-mix(in srgb, var(--success) 14%, var(--surface));
  color: var(--text-primary);
}

.cluster-capacity--bad {
  background: color-mix(in srgb, var(--danger) 14%, var(--surface));
  color: var(--danger);
}
```

- [ ] **Step 6: Add separate-carton legend**

In `renderClusterWalk`, add a short helper line under the title:

```html
<div class="cluster-progress__helper">Wagen: separate Kartons je Auftrag.</div>
```

- [ ] **Step 7: Run verification**

```bash
npx playwright test e2e/cluster.spec.js
```

Expected: cluster e2e passes and new criteria are visible.

- [ ] **Step 8: Commit**

```bash
git add pwa/js/app.js pwa/css/app.css e2e/cluster.spec.js
git commit -m "feat(pwa): show cluster rules and capacity"
```

---

### Task 5: Shipping and Customer Context API

**Files:**
- Modify: `backend/app/services/picking_service.py`
- Modify: `backend/app/services/cluster_service.py`
- Test: `backend/tests/test_picking_service.py`
- Test: `backend/tests/test_cluster_service.py`

**Interfaces:**
- Adds payload fields: `customer_name`, `shipping_address`, `delivery_date`, `carrier_name`, `customer_reference`
- Keeps Odoo-derived data as source

- [ ] **Step 1: Write failing payload tests**

In `backend/tests/test_picking_service.py`, add an assertion that a picking detail includes:

```python
assert result["customer_name"] == "ACME Demo GmbH"
assert result["shipping_address"] == {
    "street": "Musterstrasse 12",
    "street2": "",
    "zip": "48149",
    "city": "Muenster",
    "country": "Deutschland",
}
assert result["customer_reference"] == "SO-DEMO-001"
assert result["delivery_date"] == "2026-07-09"
```

In `backend/tests/test_cluster_service.py`, assert `get_batch` boxes expose customer context:

```python
box = result["boxes"][0]
assert box["customer_name"] == "ACME Demo GmbH"
assert box["shipping_address"]["city"] == "Muenster"
```

- [ ] **Step 2: Run tests to verify failure**

```bash
cd backend
PYTHONPATH=.deps python3 -m pytest -p pytest_asyncio tests/test_picking_service.py tests/test_cluster_service.py -q
```

- [ ] **Step 3: Read partner fields from Odoo**

When picking payloads have `partner_id`, collect partner IDs and read:

```python
["name", "street", "street2", "zip", "city", "country_id", "email", "phone"]
```

Normalize:

```python
def _shipping_address(partner: dict[str, Any]) -> dict[str, str]:
    country = partner.get("country_id")
    return {
        "street": partner.get("street") or "",
        "street2": partner.get("street2") or "",
        "zip": partner.get("zip") or "",
        "city": partner.get("city") or "",
        "country": country[1] if isinstance(country, list) and len(country) > 1 else "",
    }
```

- [ ] **Step 4: Add context to picking and cluster payloads**

For each picking:

```python
"customer_name": _many2one_name(picking.get("partner_id")),
"shipping_address": _shipping_address(partner_map.get(partner_id, {})),
"customer_reference": picking.get("origin") or picking.get("name") or "",
"delivery_date": _date_key(picking.get("date_deadline") or picking.get("scheduled_date")),
"carrier_name": _many2one_name(picking.get("carrier_id")) if "carrier_id" in picking else "",
```

In `ClusterService.get_batch`, include the same fields in `boxes`.

- [ ] **Step 5: Run verification**

```bash
cd backend
PYTHONPATH=.deps python3 -m pytest -p pytest_asyncio tests/test_picking_service.py tests/test_cluster_service.py -q
```

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/picking_service.py backend/app/services/cluster_service.py backend/tests/test_picking_service.py backend/tests/test_cluster_service.py
git commit -m "feat(picking): expose customer shipping context"
```

---

### Task 6: Realistic Odoo Demo Seed Data

**Files:**
- Modify: `infrastructure/scripts/seed-odoo.py`
- Test: `backend/tests/test_seed_odoo_script.py`

**Interfaces:**
- Produces realistic partners and outgoing customer pickings with overlapping products.
- Keeps existing BOM/internal demo behavior unless explicitly replaced by a CLI flag.

- [ ] **Step 1: Write failing seed tests**

Add tests that inspect helper payloads without contacting Odoo:

```python
def test_demo_customer_payload_contains_shipping_address():
    customers = build_demo_customers()
    assert customers[0]["name"]
    assert customers[0]["street"]
    assert customers[0]["zip"]
    assert customers[0]["city"]
    assert customers[0]["email"]


def test_demo_order_plan_has_product_overlap_and_delivery_dates():
    plan = build_demo_customer_order_plan()
    dates = {order["delivery_date"] for order in plan}
    assert len(dates) >= 2
    product_sets = [set(order["products"]) for order in plan[:4]]
    assert set.intersection(*product_sets)
```

- [ ] **Step 2: Run tests to verify failure**

```bash
cd backend
PYTHONPATH=.deps python3 -m pytest -p pytest_asyncio tests/test_seed_odoo_script.py -q
```

- [ ] **Step 3: Add deterministic demo customers**

In `seed-odoo.py`, add:

```python
def build_demo_customers():
    return [
        {
            "name": "ACME Demo GmbH",
            "street": "Musterstrasse 12",
            "zip": "48149",
            "city": "Muenster",
            "country_code": "DE",
            "email": "logistik@acme-demo.example",
            "phone": "+49 251 000001",
        },
        {
            "name": "Meyer Spielwaren KG",
            "street": "Hafenweg 7",
            "zip": "48155",
            "city": "Muenster",
            "country_code": "DE",
            "email": "wareneingang@meyer-demo.example",
            "phone": "+49 251 000002",
        },
        {
            "name": "Fischer Techniklabor AG",
            "street": "Industriestrasse 4",
            "zip": "72178",
            "city": "Waldachtal",
            "country_code": "DE",
            "email": "lab@fischer-demo.example",
            "phone": "+49 7443 000003",
        },
        {
            "name": "FH Demo Logistik",
            "street": "Leonardo-Campus 10",
            "zip": "48149",
            "city": "Muenster",
            "country_code": "DE",
            "email": "laborlogistik@fh-demo.example",
            "phone": "+49 251 000004",
        },
    ]
```

- [ ] **Step 4: Add customer order plan**

```python
def build_demo_customer_order_plan():
    return [
        {"origin": "SO-DEMO-001", "customer_index": 0, "delivery_date": "2026-07-09", "zone": "Links", "products": ["301121", "343721", "4166960"]},
        {"origin": "SO-DEMO-002", "customer_index": 1, "delivery_date": "2026-07-09", "zone": "Links", "products": ["301121", "343724", "4166960"]},
        {"origin": "SO-DEMO-003", "customer_index": 2, "delivery_date": "2026-07-09", "zone": "Links", "products": ["301121", "343701", "4166960"]},
        {"origin": "SO-DEMO-004", "customer_index": 3, "delivery_date": "2026-07-09", "zone": "Links", "products": ["301121", "343721", "4166960"]},
        {"origin": "SO-DEMO-005", "customer_index": 0, "delivery_date": "2026-07-10", "zone": "Rechts", "products": ["4216758", "4250172"]},
        {"origin": "SO-DEMO-006", "customer_index": 1, "delivery_date": "2026-07-10", "zone": "Rechts", "products": ["4216758", "4185178"]},
    ]
```

- [ ] **Step 5: Use partners when creating pickings**

In the picking creation helper, include:

```python
"partner_id": partner_id,
"origin": order["origin"],
"scheduled_date": f'{order["delivery_date"]} 08:00:00',
"date_deadline": f'{order["delivery_date"]} 16:00:00',
```

Use outgoing picking type when available:

```python
out_type = find_picking_type("outgoing") or find_picking_type("internal")
```

- [ ] **Step 6: Run verification**

```bash
cd backend
PYTHONPATH=.deps python3 -m pytest -p pytest_asyncio tests/test_seed_odoo_script.py -q
```

- [ ] **Step 7: Commit**

```bash
git add infrastructure/scripts/seed-odoo.py backend/tests/test_seed_odoo_script.py
git commit -m "feat(seed): add customer order cluster demo data"
```

---

### Task 7: Full Verification and Wiki Handoff

**Files:**
- Modify: `Projekt-Wiki/12 - Funktionsdokumentation/10 - Cluster-Picking Odoo-19 Audit und Haertungsplan.md`
- Optional Modify: `Projekt-Wiki/12 - Funktionsdokumentation/03 - Cluster- & Batch-Picking.md`
- Optional Modify: `Projekt-Wiki/05 - Future Functions/Cluster- und Batch-Picking.md`

**Interfaces:**
- Produces final verification record with commands and outcomes.

- [ ] **Step 1: Run backend cluster/picking/seed tests**

```bash
cd "/mnt/c/Users/endri/Desktop/Bachelor/Mobile Picking und Voice Assistant/backend"
PYTHONPATH=.deps python3 -m pytest -p pytest_asyncio tests/test_cluster_service.py tests/test_cluster_routes.py tests/test_picking_service.py tests/test_seed_odoo_script.py -q
```

Expected: all selected tests pass.

- [ ] **Step 2: Run PWA cluster e2e**

```bash
cd "/mnt/c/Users/endri/Desktop/Bachelor/Mobile Picking und Voice Assistant"
npx playwright test e2e/cluster.spec.js
```

Expected: all cluster e2e tests pass.

- [ ] **Step 3: Run focused grep sanity checks**

```bash
rg "stock_picking_batch_unavailable|cluster_capacity|mixed_delivery_date|no_product_overlap|separate Kartons" backend pwa e2e infrastructure
```

Expected: all new rule names and copy exist in the intended files.

- [ ] **Step 4: Update wiki handoff**

Append a section:

```markdown
## Umsetzung abgeschlossen am 2026-07-08

- Backend-Regeln: Ergebnis der Tests eintragen.
- PWA-Regeln: Ergebnis der Playwright-Tests eintragen.
- Seed-Daten: Anzahl Demo-Kunden und Demo-Auftraege eintragen.
- Bekannte Restgrenzen: Versandlabel-Druck noch nicht im Scope.
```

If execution happens on a later date, replace `2026-07-08` with that execution date and use the actual command results from Steps 1 and 2.

- [ ] **Step 5: Commit documentation**

```bash
git add "Projekt-Wiki/12 - Funktionsdokumentation/10 - Cluster-Picking Odoo-19 Audit und Haertungsplan.md" "Projekt-Wiki/12 - Funktionsdokumentation/03 - Cluster- & Batch-Picking.md" "Projekt-Wiki/05 - Future Functions/Cluster- und Batch-Picking.md"
git commit -m "docs(cluster): record Odoo 19 hardening outcome"
```

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-07-08-cluster-picking-odoo19-hardening.md`.

Two execution options:

1. **Subagent-Driven (recommended)** - dispatch a fresh subagent per task, review between tasks, fast iteration.
2. **Inline Execution** - execute tasks in this session using `superpowers:executing-plans`, batch execution with checkpoints.

For the next implementation session, use `superpowers:subagent-driven-development` or `superpowers:executing-plans` before touching code.
