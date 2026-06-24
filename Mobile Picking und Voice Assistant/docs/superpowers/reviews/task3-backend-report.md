# Task 3 — Backend-Review-Fixes (Cluster-/Batch-Picking)

**Datum:** 2026-06-24
**Branch:** `feat/cluster-picking`
**Vorgehen:** TDD (Test rot -> minimaler Fix -> Test gruen -> Vollsuite).
**Baseline vorher:** 132 passed. **Nachher:** 146 passed (14 net neue Tests).

## Commits

```
4342840 fix(cluster): return HTTP 403 on auth-failure for confirm-line and validate (#4)
97a8ba2 fix(cluster): harden cluster_service writes, scoping, state-guard and telemetry
```

Commit-Range: `795952d..97a8ba2` (die beiden neuen Commits auf dem Review-Doc-Commit aufsetzend).
**Nicht gepusht** (Controller uebernimmt Push/Merge).

---

## Findings — was geaendert wurde

### #1 (Critical) — confirm_cluster_line: ungeschuetzte Odoo-Writes
`cluster_service.py` `confirm_cluster_line` (Writes ~Z. 365-380): beide
`write("stock.move.line", …)` + `write("stock.move", …)` in `try/except OdooAPIError`.
Im Fehlerfall `logger.error(...)`, `_emit_cluster_confirm(False, …)` und Rueckgabe
`{"success": False, "message": "Bestaetigung fehlgeschlagen: …", "progress": None}` statt 500.
**Test:** `TestConfirmClusterLine::test_returns_error_when_write_fails`.

### #2 (Critical) — create_batch: create+action_confirm ungeschuetzt
`cluster_service.py` `create_batch` (~Z. 157-185): `create` und `action_confirm` je in
`try/except OdooAPIError` mit `logger.error`. Schlaegt `action_confirm` nach erfolgreichem
`create` fehl, wird ein kompensierendes `action_cancel([batch_id])` versucht (selbst in
`try/except` geloggt), danach Error-Result. Kein verwaister Draft mehr.
**Test:** `TestCreateBatch::test_compensating_cancel_when_confirm_fails`.

### #3 (Important) — create_batch: IDOR / ungescopte picking_ids
`cluster_service.py` `create_batch` (~Z. 141-156): Eingabe-IDs werden via
`search_read("stock.picking", [("id","in",ids),("state","=","assigned"),("batch_id","=",False)], ["id","company_id"])`
gescoped. Leeres Ergebnis -> `{"error": …, "forbidden": True}` (kein `create`). `vals`/`picking_ids`
nutzen ausschliesslich `allowed_ids` + deren `company_id`.
**Tests:** `TestCreateBatch::test_scopes_picking_ids_to_assigned_unbatched`,
`TestCreateBatch::test_rejects_when_no_allowed_pickings`.

### #4 (Important) — Router: 403 statt 200 bei Auth-Fehler
`cluster_service.py`: Auth-Fehlerpfade von `confirm_cluster_line` (#10-Guard) und
`validate_batch` (Ownership-Gate) tragen jetzt `"forbidden": True`.
`routers/cluster.py` `confirm_cluster_line`/`validate_cluster_batch`:
`if result.get("forbidden"): raise HTTPException(status_code=403, detail=result["message"])`
(mirror get_batch). Erfolgs-Result wird unveraendert durchgereicht.
**Tests:** `test_cluster_routes.py::test_confirm_line_forbidden_returns_403`,
`test_validate_forbidden_returns_403`.

### #5 (Important) — validate_batch: State-Guard
`cluster_service.py` `validate_batch` (~Z. 405-432): `"state"` zur `search_read`-Feldliste
hinzugefuegt; bei `state == "done"` Early-Return
`{"success": True, "batch_complete": True, "message": "Batch bereits abgeschlossen."}`
(kein `action_done`).
**Test:** `TestValidateBatch::test_early_return_when_batch_already_done`.

### #6 (Important) — validate_batch: Logging/Telemetrie
`cluster_service.py`: `logger.warning` vor Wizard-Return, `logger.error` im `except`.
Neuer Helper `_emit_batch_validate(success, batch_id, outcome, t0)` (analog
`_emit_cluster_confirm`), emittiert auf ALLEN Exit-Pfaden:
`success`, `success_degraded`, `wizard`, `auth_denied`, `not_found`, `already_done`, `odoo_error`.
**Tests:** `TestValidateBatch::test_validate_emits_telemetry_on_success`,
`test_validate_logs_and_emits_on_wizard`, `test_validate_logs_error_on_odoo_error`.

### #7 (Important) — confirm_cluster_line: get_batch nach Write
`cluster_service.py` (~Z. 382-398): Erfolgs-`_emit_cluster_confirm(True, …)` VOR dem
nachgelagerten `get_batch`; `get_batch` separat in `try/except OdooAPIError`. Bei Read-Fehler
`progress = None`, `success: True` bleibt (Write best effort, kein Doppel-Confirm-Risiko).
**Test:** `TestConfirmClusterLine::test_success_when_progress_read_fails`.

### #9 (Important) — confirm_cluster_line: Doppel-Query
`cluster_service.py` (~Z. 348-362): `product.product` einmalig mit `["barcode","tracking"]`
gelesen (nur wenn Barcode oder Serial vorliegt) und fuer Barcode-Check UND Serial/Tracking-Check
wiederverwendet. Zweiter `["tracking"]`-Read entfernt.
**Test:** `TestConfirmClusterLine::test_reads_product_once_for_barcode_and_serial`.

### #10 (Minor) — confirm_cluster_line: fail-closed ohne picker_identity
`cluster_service.py` (~Z. 318-331): bei `requester_id is None` Fail-Closed-Guard
(Fehler-Telemetrie + `{"success": False, "forbidden": True, "progress": None}`).
Owner-Filter `("picking_id.batch_id.user_id","=",requester_id)` ist jetzt **unbedingt**
in der Domain (kein Fallback auf batch-only).
**Test:** `TestConfirmClusterLine::test_confirm_fail_closed_without_picker_identity`.

### #12 (Minor) — Single-Write-Assertion gestaerkt
`test_cluster_service.py::test_writes_quantity_and_picked_without_validate`: prueft jetzt
`len([Writes auf stock.move.line]) == 1` (wie der picking_service-Test). Test ruft nun mit
`PickerIdentity(user_id=7)` (sonst greift #10-Guard).

### #14 (Minor) — suggest_batches: Logging bei OdooAPIError
`cluster_service.py` `suggest_batches` (~Z. 85-107): beide `search_read` in `try/except OdooAPIError`
mit `logger.error(...)` vor `raise` (sichtbares Service-Logging statt stiller 500-Propagation).
**Test:** `TestSuggestBatchesLogging::test_logs_error_on_odoo_error`.

---

## Sicherheits-Invarianten (alle gehalten)
- IDOR-Scoping (`confirm_cluster_line`-Domain, jetzt zusaetzlich `create_batch`-Scoping) intakt.
- `_is_authorized` fail-closed unveraendert; `confirm_cluster_line` jetzt paritaetisch fail-closed (#10).
- Gate-Paritaet `get_batch`/`validate_batch`/`confirm_cluster_line` (alle 403 ueber `forbidden`).
- Odoo-18-Fakten beachtet: kein per-Picking-`button_validate` im Cluster-Confirm;
  Wizard-Dict aus `action_done` = NICHT komplett; `picking_ids=[(6,0,ids)]` als REPLACE bewusst
  nur mit gescopten ids.

## Finale Testausgabe
```
146 passed, 62 warnings in 2.39s
```
(132 Baseline + 14 neue Tests; Findings #1/#2/#3/#4/#5/#6/#7/#9/#10/#12/#14 abgedeckt.)
Finding #8 ist Frontend (app.js) und nicht Teil dieses Backend-Tasks.

## Concerns
Keine. #1-Teilwrite-Konsistenz: bei Write-Fehler kann theoretisch `stock.move.line` geschrieben,
`stock.move.picked` nicht gesetzt sein. Das war im Finding so akzeptiert (klare Fehlermeldung
statt 500); eine echte Transaktionsklammer ist auf Odoo-RPC-Ebene nicht verfuegbar.
