# Finaler Multi-Agent-Review — Cluster-/Batch-Picking

**Datum:** 2026-06-24
**Scope:** `origin/main..feat/cluster-picking` (Cluster-Feature + Serial-Telemetrie- + PWA-Serial-Fix)
**Reviewer:** security-reviewer (opus), code-reviewer (sonnet), silent-failure-hunter (sonnet)
**Gesamt-Verdikt:** FIXES-REQUIRED

Verifiziert wurde u.a., dass die 4 vorherigen Security-Runden halten: `confirm_cluster_line`
scoped search_read (IDOR), `get_batch`/`validate_batch` `_is_authorized`-Gate, fail-closed
`_is_authorized`, `safeColor`/`safeInt` gegen CSS-Injection/XSS — alles bestätigt intakt.
Architektur-Fakt: `OdooClient` läuft mit EINEM Service-Account; Odoo-Record-Rules greifen NICHT
→ die gesamte Autorisierung lebt im `cluster_service`-Domain-Scoping (keine zweite DB-Verteidigungslinie).

## Zu behebende Findings (Critical + Important)

### 1 — CRITICAL · `cluster_service.confirm_cluster_line` (Odoo-Writes ungeschützt)
Die `write("stock.move.line", …)` und `write("stock.move", …)` sind nicht in try/except. Bei
`OdooAPIError` (Netz/Lock/Constraint): Exception propagiert als HTTP 500, Erfolgs-Telemetrie wird
NICHT emittiert (Denominator unterzählt), und ein Teil-Write (move.line ok, move fehlgeschlagen)
hinterlässt inkonsistenten Zustand → Picker bestätigt evtl. doppelt.
**Fix:** beide Writes in try/except OdooAPIError; im Fehlerfall `_emit_cluster_confirm(False, …)`
und `{"success": False, "message": "…", "progress": None}` zurückgeben.

### 2 — CRITICAL · `cluster_service.create_batch` (create+action_confirm ungeschützt)
`create("stock.picking.batch")` + `action_confirm` ohne Error-Handling. Schlägt `action_confirm`
nach erfolgreichem `create` fehl, bleibt ein Draft-Batch verwaist (Pickings via `batch_id != False`
aus `suggest_batches` verschwunden, aber in PWA unerreichbar). Kein Log, kein Cleanup.
**Fix:** try/except OdooAPIError mit `logger.error`; optional kompensierendes `action_cancel([batch_id])`
vor Re-raise/Fehlerantwort.

### 3 — IMPORTANT · `cluster_service.create_batch` (IDOR / ungescopte picking_ids)
`create_batch` übernimmt beliebige Client-`picking_ids` und liest nur `company_id`. Kein Check auf
`state == 'assigned'` / `batch_id == False` / Zugehörigkeit. `picking_ids=[(6,0,ids)]` ist ein
REPLACE → ein Picker kann fremde, bereits gebündelte Pickings in seinen Batch ziehen (Hijack) und
offene-State-Bypass betreiben.
**Fix:** Eingabe wie in `suggest_batches` scopen:
`search_read("stock.picking", [("id","in",ids),("state","=","assigned"),("batch_id","=",False)], ["id","company_id"])`,
abgelehnte IDs zurückweisen (`forbidden: True`), `vals` nur aus erlaubten IDs + deren company_id bauen.

### 4 — IMPORTANT · `routers/cluster.py` (403 statt 200 bei Auth-Fehler)
`confirm-line` und `validate` geben bei Ownership-Verletzung HTTP 200 mit `success:false` zurück
(nur `get_batch` macht es korrekt via `forbidden`→403). Inkonsistent + erschwert Security-Monitoring.
**Fix:** Service-Ergebnisse der Auth-Fehlerpfade um `"forbidden": True` ergänzen; Router beider
Endpoints: `if result.get("forbidden"): raise HTTPException(403, result["message"])`.

### 5 — IMPORTANT · `cluster_service.validate_batch` (kein State-Guard)
Kein Check des aktuellen `state` vor `action_done`. Doppel-Tap (Race gegen JS-Button-Disable) ruft
`action_done` auf bereits `done`-Batch → undefiniertes Verhalten.
**Fix:** `"state"` zur `search_read`-Feldliste hinzufügen; früh `if batch.get("state")=="done": return
{"success": True, "batch_complete": True, "message": "Batch bereits abgeschlossen."}`.

### 6 — IMPORTANT · `cluster_service.validate_batch` (kein Logging/Telemetrie)
Wizard-Rückgabe (z.B. `stock.backorder.confirmation`) und alle Fehlerpfade haben weder Logging noch
ein Telemetrie-Event. Batch-Abschluss-Erfolgsrate ist damit unmessbar (thesis-relevant: success_rate).
**Fix:** `logger.warning` vor Wizard-Return, `logger.error` im except; `_emit_batch_validate`-Event
(analog `_emit_cluster_confirm`) auf ALLEN Exit-Pfaden (success/wizard/auth/not-found/OdooAPIError).

### 7 — IMPORTANT · `cluster_service.confirm_cluster_line` (get_batch nach Write)
Erfolgs-Telemetrie wird VOR `get_batch` emittiert. Schlägt der Progress-Read fehl → HTTP 500 trotz
erfolgreichem Write; Telemetrie zählt Erfolg, PWA zeigt Fehler → Doppel-Confirm.
**Fix:** `get_batch` separat in try/except; `progress=None` als best-effort, `success:True` bleibt.

### 8 — IMPORTANT · `app.js validateClusterBatch` (Wizard-UX Sackgasse)
`pending_action`/Wizard-Fall wird wie ein normaler Fehler als gelber Warning-Toast gezeigt, ohne
Eskalationspfad → Picker tappt endlos, Batch bleibt offen.
**Fix:** `pending_action` explizit behandeln: `feedbackError()` + Error-Toast „… Vorgesetzte:n
informieren (Odoo-Aktion erforderlich)".

### 9 — IMPORTANT · `cluster_service.confirm_cluster_line` (Doppel-Query)
Zwei `search_read` auf `product.product` (einmal `["barcode","tracking"]`, später erneut `["tracking"]`)
pro Confirm mit Barcode+Serial.
**Fix:** einmal `["barcode","tracking"]` lesen und Ergebnis für beide Checks wiederverwenden.

## Minor-Findings (für finalen Whole-Branch-Review notiert, nicht blockierend)

- 10 — `confirm_cluster_line`: Ownership-Gate fällt auf batch-only zurück, wenn `picker_identity` None
  (aktuell nicht über die API erreichbar; Defense-in-Depth-Parität mit `_is_authorized`).
- 11 — `app.js handleClusterConfirm`: `btn`-Referenz nach `loadBatch()`-Re-Render stale (harmlos, toter
  Re-enable-Pfad).
- 12 — `test_cluster_service.py`: `test_writes_quantity_and_picked_without_validate` Assertion zu schwach;
  Single-Write-Invariante (`len(writes)==1`) wie in `test_picking_service.py` ergänzen.
- 13 — `app.js enterClusterMode`: `Promise.all` short-circuit → Suggestions-Fehler blockt Einstieg,
  obwohl manuelle Auswahl ginge. `Promise.allSettled` nutzen.
- 14 — `suggest_batches`: kein Service-Logging bei `OdooAPIError`.
- 15 — `createClusterBatch` Idempotency-Key mit `Date.now()` — gegenstandslos (Server implementiert
  keine Cluster-Idempotenz), nur dokumentieren.
- 16 — `suggest_batches`: `line_count` zählt Multi-Zonen-Pickings unter Erst-Zonen-Heuristik über
  (rein Anzeige, kein Funktionsbug).
