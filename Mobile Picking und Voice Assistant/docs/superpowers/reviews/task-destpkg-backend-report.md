# Task Report — Destination Package (result_package_id) im Cluster-Picking-Backend

Branch: `feat/cluster-destination-package`
Datum: 2026-06-24
Methodik: TDD (RED -> GREEN), Commit-only (kein Push).

## Ziel
Jedes Picking (Order) in einem `stock.picking.batch` erhaelt ein eigenes echtes,
wiederverwendbares `stock.quant.package`, das als `result_package_id` (Ziel-Package)
auf allen Move-Lines des Pickings persistiert wird. Box N <-> Order N <-> 1 Package.
Beim `action_done` landen die Waren physisch in diesem Package — das definierende
Cluster-Picking-Merkmal laut Odoo-Doku.

## Aenderungen pro Finding

Datei: `backend/app/services/cluster_service.py`

1. **Modul-Docstring (Zeilen 1–13).** Hinweis "Box-Zuordnung ist rein logisch ... keine
   Odoo-Packages" ersetzt durch die echte Package-Semantik (Box N <-> Order N <-> 1
   reusable `stock.quant.package`, `result_package_id`, physisches Landen beim `action_done`).

2. **`create_batch` (nach erfolgreichem `action_confirm`, vor `get_batch`).** Neuer
   best-effort Block: `try: await self._assign_packages(allowed_ids) except OdooAPIError:
   logger.error(...)`. Bewusst KEIN `action_cancel` und KEIN `raise` — ein Package-Glitch
   darf den bereits bestaetigten Batch nie zerstoeren (Kommentar im Code erklaert dies).

3. **Neue Methode `_assign_packages(allowed_ids)`.** Reuse von `assign_boxes` fuer stabile
   `box_index`-Reihenfolge. Liest Picking-Namen (`stock.picking` -> `name`) und Move-Lines
   (`stock.move.line` mit Filter `[("picking_id","in",allowed_ids)]`, Felder `id`,
   `picking_id`), gruppiert Line-IDs je Picking. Pro Picking (sortiert nach `box_index`):
   `create("stock.quant.package", {"name": f"CLUSTER-B{box_index}/{picking_name}",
   "package_use": "reusable"})`, dann `write("stock.move.line", line_ids,
   {"result_package_id": package_id})`. Pickings ohne Lines werden uebersprungen.

4. **`get_batch` — `search_read` Feldliste.** `"result_package_id"` zur
   `stock.move.line`-Feldliste hinzugefuegt.

5. **`get_batch` — Line-Aufbau-Schleife.** Aus `result_package_id` (`[id, name]` oder
   `False`) werden `package_id`/`package_name` abgeleitet (fehlt -> `None`, abwaertskompatibel)
   und an jedes Line-Dict angehaengt. Zusaetzlich `package_by_picking`-Map (alle Lines eines
   Pickings teilen ein Package; erster nicht-leerer Wert gewinnt).

6. **`get_batch` — `boxes`-Rueckgabe.** Pro Box `package_id`/`package_name` aus
   `package_by_picking` ergaenzt; `box_index`/`box_color` unveraendert (additiv,
   abwaertskompatibel).

Unberuehrt: IDOR-/`_is_authorized`/Fail-closed-Logik, Telemetrie-Helfer
(`_emit_cluster_confirm`, `_emit_batch_validate`), `confirm_cluster_line`,
`validate_batch`, `suggest_batches`.

## Neue Tests

Datei: `backend/tests/test_cluster_service.py`

- `TestCreateBatch::test_creates_one_package_per_picking_and_writes_result_package` —
  zwei Pickings (Lines 100,101 bzw. 200) -> genau zwei `create("stock.quant.package",
  {"package_use":"reusable", ...})`; zwei `write("stock.move.line", <lineset>,
  {"result_package_id": <pkg>})` mit getrennten Packages je Picking.
- `TestCreateBatch::test_batch_still_succeeds_when_package_assignment_fails` —
  `create("stock.quant.package")` wirft `OdooAPIError`; `create_batch` gibt trotzdem
  `batch_id` zurueck, kein `error`, kein `action_cancel`.
- `TestGetBatch::test_surfaces_result_package_per_box_and_line` — `package_name`/`package_id`
  je Line und je Box aus `result_package_id`; `box_index`/`box_color` intakt.
- `TestGetBatch::test_package_name_none_when_no_result_package` — `result_package_id: False`
  -> `package_name`/`package_id` `None`, Box weiterhin intakt (abwaertskompatibel).

## Test-Ergebnis

Kommando (aus `backend/`):
`PYTHONPATH=.deps python -m pytest -p pytest_asyncio tests/ -q`

- Baseline vorher: **146 passed**
- Nach Implementierung: **150 passed** (146 bestehende + 4 neue), 0 failed.

## Commits

- `ba0d9d2` feat(cluster): echte Ziel-Packages (result_package_id) je Order im Batch
- `c821ecb` test(cluster): Ziel-Package-Zuweisung und -Surface abdecken

Commit-Range: `ba0d9d2..c821ecb` (Basis `e343ee1`). Kein Push.

## Concerns / Hinweise

- Package-Namensschema `CLUSTER-B{box_index}/{picking_name}` ist beschreibend, aber nicht
  global eindeutig ueber mehrere Batches/Tage hinweg. Falls Odoo `name` als unique
  erzwingt, koennte ein erneutes Anlegen kollidieren — derzeit best-effort (Fehler wird
  geloggt, Batch bleibt valide). Bei Bedarf `picking_id`/Timestamp ergaenzen.
- `_assign_packages` ist nicht idempotent: ein zweiter Aufruf wuerde neue Packages anlegen.
  Aktuell wird es nur einmal direkt nach `action_confirm` aufgerufen, daher unkritisch.
- Frontend/Route-Schicht nutzt die neuen Felder (`package_name`/`package_id` in `boxes`
  und `lines`) noch nicht — additive, abwaertskompatible Erweiterung; PWA-Anbindung ist
  ein separater Folgeschritt.
