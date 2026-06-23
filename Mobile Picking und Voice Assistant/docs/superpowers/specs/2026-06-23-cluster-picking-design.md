# Design Spec: Cluster-/Batch-Picking (PoC)

- **Datum:** 2026-06-23
- **Branch:** `feat/cluster-picking` (abgezweigt von `feat/seriennummer-bestaetigung`)
- **Status:** Design abgenommen — Implementierung ausstehend
- **Autor:** Claude Code (Chat 3), abgestimmt mit Endrit Murati
- **Bezug:** Prof-Wunsch „Cluster-/Batch-Picking"; Vault-Leitlinie *„Auf dem PoC aufbauen, keine Parallelwelt, Odoo bleibt System of Record"*

---

## 1. Ziel

Mehrere offene Pickaufträge gebündelt in **einem** Lager-Rundgang abarbeiten. Der Picker
entnimmt pro Lagerplatz ggf. für mehrere Aufträge gleichzeitig und sortiert die Mengen in
getrennte Körbe/Kartons (ein Korb ↔ ein Auftrag). Vollständig integriert: Backend + PWA,
inklusive sauberem Frontend-Design, Serial-Erfassung und Voice-Guidance.

## 2. Kernentscheidungen (abgenommen)

| # | Entscheidung | Wahl |
|---|---|---|
| E1 | Batch-Fundament | **Odoo-natives `stock.picking.batch`** (persistent, Odoo = System of Record). Setzt Modul `stock_picking_batch` voraus → beim ersten Stack-Lauf verifizieren. |
| E2 | Batch-Zusammenstellung | **Auto-Vorschlag (Zonen-Heuristik) + manuelle Korrektur** durch den Picker. |
| E3 | Abschluss-Flow | **Alles picken, dann Batch gesammelt validieren** via `action_done` auf `stock.picking.batch` (keine Pro-Picking-Validierung während des Rundgangs). |
| E4 | Scope | Serial-Erfassung **+** Box-/Korb-Zuordnung **+** Voice-Guidance **+** Auto-Batch-Validierung mit n8n-Event — **alles drin**. |
| E5 | Box-Zuordnung | **Nur logisch/visuell** (Box N ↔ Auftrag/Picking N). **Keine** echten Odoo-Packages — das ist das separate Feature *Put-to-Box* (`result_package_id`), bewusst nicht hier. |
| E6 | Endpoint-Pfad | `/api/cluster/*` (passt zum bestehenden `/api`-Prefix in `main.py`). |

## 3. Architektur & Datenfluss

```
PWA (neue Cluster-View)
   │  HTTPS, nur FastAPI
   ▼
FastAPI  /api/cluster/*  (routers/cluster.py)
   │
   ▼
ClusterService (services/cluster_service.py)
   │  JSON-RPC
   ▼
Odoo  stock.picking.batch + stock.picking / stock.move / stock.move.line
   │
   └→ n8n  (Event nach Batch-Abschluss)
```

Invarianten gewahrt: PWA spricht nur mit FastAPI (Inv. 2); Odoo bleibt System of Record
(echter Batch-Datensatz, kein Schatten-State, Inv. 1); n8n nur als Folge-Orchestrator (Inv. 3);
Touch bleibt Fallback (Inv. 5).

## 4. Backend — nur NEUE Dateien

### `backend/app/services/cluster_service.py` — `ClusterService`

| Methode | Aufgabe | Odoo-Berührung |
|---|---|---|
| `suggest_batches()` | Offene `assigned`-Pickings ohne Batch laden, per Zonen-Heuristik (`route_optimizer`) gruppieren → Vorschläge `{picking_ids, zone, order_count, line_count}` | `search_read` stock.picking, stock.move.line |
| `create_batch(picking_ids, picker)` | `stock.picking.batch` anlegen (`user_id`=Picker, `picking_ids`=`[(6,0,ids)]`), `action_confirm` → `in_progress`; liefert `batch_id` + Sammelliste | `create`, `call_method` action_confirm |
| `get_batch(batch_id)` | Alle Move-Lines aller Batch-Pickings mergen, via `build_route_plan` route-sortieren, je Zeile **Box-Index/Farbe + Auftrag** + `voice_instruction_short` taggen, Fortschritt aggregieren | `search_read` |
| `confirm_cluster_line(batch_id, picking_id, move_line_id, scanned_barcode, quantity, serial_number, picker)` | Barcode prüfen, `quantity` (+ optional `lot_name` bei tracking) + `move.picked=True` schreiben — **ohne** Picking-Validierung. Telemetrie-Event | `read`, `write` |
| `validate_batch(batch_id, picker)` | `action_done` auf den Batch (validiert alle Pickings gesammelt); n8n-Event feuern; Abschluss-Summary | `call_method` action_done |

**Box-Zuordnung (deterministisch):** Pickings im Batch werden sortiert (nach `picking_id`),
Index 1..N = Box-Nummer; Farbe aus fester Token-Palette (zyklisch). Reine Anzeige-/Sortierhilfe.

**Wiederverwendung statt Duplikat:** `build_route_plan`, `_enrich_line_payload`,
`_build_voice_instruction_short` u. ä. werden importiert/wiederverwendet, **nicht** kopiert.
`picking_service.py` bleibt unberührt.

### `backend/app/routers/cluster.py`

| Methode & Pfad | Zweck |
|---|---|
| `GET  /api/cluster/suggestions` | Auto-Vorschläge für Batches |
| `POST /api/cluster/batches` | Batch aus `picking_ids` anlegen |
| `GET  /api/cluster/batches/{batch_id}` | Sammelliste + Fortschritt |
| `POST /api/cluster/batches/{batch_id}/confirm-line` | Position bestätigen (ohne Validate) |
| `POST /api/cluster/batches/{batch_id}/validate` | Ganzen Batch validieren |

Picker-Identity + Idempotenz analog `pickings.py` (über `mobile_workflow`).

### Touch-Punkte außerhalb neuer Dateien (minimal, additiv)

1. `backend/app/main.py`: **eine** Zeile `app.include_router(cluster.router, prefix="/api", tags=["cluster"])`.
2. `ClusterService` wird wenn möglich im Router über bestehende Provider (`get_odoo_client`,
   n8n) instanziiert, um `dependencies.py` **nicht** anzufassen. Falls ein
   `get_cluster_service`-Provider nötig wird, ist auch das eine additive Funktion.

> Beides liegt in der Chat-1-Zone (`backend/**`), ist aber je eine additive Zeile/Funktion und
> trivial mergebar. Kein Eingriff in `picking_service.py`.

## 5. Frontend — additiv in `pwa/`

- **Auswahl-Screen:** Auto-Vorschläge oben + offene Aufträge; Multi-Select-Toggle zum
  Hinzufügen/Entfernen; „Batch starten".
- **Cluster-Rundgang:** route-sortierte Sammelliste nach Lagerplatz; je Position farbcodierter
  **Box-/Auftrags-Tag** („Box 1 → WH/OUT/001"), Menge, Voice-Button; Bestätigung pro Position
  (Serial-Modal aus Basis-Branch bei `tracking`-Produkten).
- **Fortschritts-Header** über alle Aufträge; „Batch abschließen" aktiv, wenn alles gepickt →
  ruft `validate` auf.
- **Voice-Guidance:** wiederverwendete TTS spricht `voice_instruction_short` pro Cluster-Stop.
- **Design:** mobile-first + Desktop-2-Spalten gemäß `.design/picking-pwa/DESIGN_BRIEF.md`;
  bestehende Tokens/Klassen, kein generischer KI-Look. Vor dem Bau `frontend-design`-Skill.
- **Additiv:** neue Funktionen/Views; berührt `handleConfirmAll` (Chat 2) nicht.

## 6. Fehlerbehandlung

- Modul `stock_picking_batch` nicht installiert → klare `501`-Antwort + Hinweis; im PWA-UI als
  „Cluster-Picking benötigt das Odoo-Batch-Modul" anzeigen.
- Barcode-Mismatch pro Zeile → bestehende Fehlersemantik (erwarteter Barcode).
- Teilweise fehlgeschlagene Batch-Validierung (`action_done`) → melden, welche Pickings hängen
  blieben (Backorder/Fehlbestand), Rest bleibt gültig.
- Leerer/ungültiger `picking_ids`-Satz → `400`.

## 7. Tests (TDD)

**Backend `pytest`** (`backend/tests/test_cluster_service.py`, gemockter OdooClient):
- `suggest_batches` gruppiert nach Zone korrekt; ignoriert bereits gebatchte Pickings.
- `create_batch` baut korrekte Vals (`user_id`, `picking_ids` 6,0-Befehl) + ruft `action_confirm`.
- `confirm_cluster_line` schreibt `quantity`/`picked`, **ruft nicht** `button_validate`.
- Serial: tracking-Produkt → `lot_name` gesetzt; untracked → ignoriert.
- `validate_batch` ruft `action_done`; feuert n8n-Event; Summary korrekt.
- Box-Zuordnung deterministisch (gleiche Eingabe → gleiche Box-Indizes/Farben).

**PWA:** Playwright-E2E für Auswahl → Rundgang → Abschluss; Visual-Snapshot der neuen View; a11y.

## 8. Bewusste PoC-Vereinfachungen (YAGNI)

- Kein Claim/Heartbeat-Tanz pro Picking im Cluster — `batch.user_id` genügt als Ownership.
  Idempotenz auf Schreib-Endpoints bleibt.
- Keine echten Odoo-Packages (siehe E5 — separates Put-to-Box-Feature).
- Auto-Gruppierungs-Heuristik bewusst schlank (Zone aus `route_optimizer`), keine echte
  Laufzeit-Optimierung.

## 9. Anschlusspunkte / spätere Kombination

- **Put-to-Box** (`stock.quant.package`, `result_package_id`): aus der logischen Box-Zuordnung
  könnten später echte Odoo-Packages werden → Artikel → Exemplar (Serial) → Karton → Kunde.
- **Serial-Bestätigung** (Basis-Branch): bereits integriert (E4).

## 10. Definition of Done

- Backend-Endpoints + `ClusterService` implementiert, `pytest` grün.
- PWA-Cluster-View gebaut, `verify-ui` / `verify-visual` / `verify-a11y` grün.
- Code-Review (`superpowers:requesting-code-review`) durchlaufen.
- **Nicht gemergt** — landet als letztes Feature nach den Serial-Fixes (Chat 1+2).
- Spec + Fortschritt in Obsidian (`05 - Future Functions/Cluster- und Batch-Picking.md`) und
  Memory festgehalten.
