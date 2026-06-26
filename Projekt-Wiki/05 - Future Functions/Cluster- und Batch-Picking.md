---
title: "Cluster-/Batch-Picking (richtiger Empfängerkarton)"
tags:
  - feature
  - future
  - picking
  - odoo
status: implemented
component: backend, pwa, odoo
created: 2026-06-22
implemented: 2026-06-24
---

> [!success] Umgesetzt & in `main` (2026-06-24)
> Feature ist implementiert, multi-agent-reviewt, live gegen echtes Odoo (`masterfischer`) verifiziert
> und per Fast-Forward nach `main` gemergt (HEAD `dd72b9e`). Tests: 146 Backend + 5 e2e grün.
> **Live-Zyklus bestanden:** suggest → create_batch (BATCH/00001) → 6× confirm → validate_batch
> (`action_done`) → Batch + Picking `done`. Voraussetzung erfüllt: Odoo-Modul `stock_picking_batch`
> in `masterfischer` installiert.
>
> **Realisierte Architektur** (weicht von der ursprünglichen Planung unten ab): eigener
> `backend/app/services/cluster_service.py` + `routers/cluster.py` (statt picking_service zu erweitern),
> **echtes Odoo-Cluster mit Ziel-Verpackung** — je Auftrag eine reusable `stock.quant.package`,
> `result_package_id` auf den Move-Lines (Odoo-Feature „Packages" aktiviert; nachgerüstet 2026-06-24
> gemäß offizieller Odoo-Cluster-Doku; Put-to-Box damit in den Cluster-Flow integriert), Abschluss
> gesammelt via `action_done` (Cluster-Confirm validiert NICHT pro Picking). Sicherheit: fail-closed
> Autorisierung, IDOR-Scoping inkl. create_batch, HTTP-403-Parität, CSS-Injection-Schutz.
>
> **n8n-Webhook `batch-confirmed` — erledigt (2026-06-24):** Workflow `n8n/workflows/batch-confirmed.json`
> (mit durablem `webhookId`) erstellt, importiert + aktiviert; live verifiziert (backend→n8n = HTTP 200) →
> `validate_batch` liefert künftig `integration_status: success`.
>
> Artefakte: `docs/superpowers/plans/2026-06-24-cluster-picking-abschluss.md`,
> `docs/superpowers/reviews/2026-06-24-cluster-picking-review.md`.

> [!success] Live end-to-end im echten PWA verifiziert (2026-06-26)
> Reproduzierbarer Browser-Klick-Durchlauf via Playwright-Harness `e2e/cluster.live.js`
> (UNGEMOCKT gegen `https://localhost` → Caddy → FastAPI → Odoo `masterfischer`). Zwei grüne Läufe:
> **BATCH/00005** (manuelle Auswahl 323+347, 13 Pos.) und **BATCH/00006** (Auto-Vorschlag „Lager Links"
> 353+359, 5 Pos.). Odoo-Datenebene bestätigt: Batch+Pickings=`done`, `result_package_id` auf allen
> Move-Lines, Waren physisch in `CLUSTER-Bx`-Packages (`stock.quant`), n8n `batch-confirmed` ohne
> `degraded`. Demo danach via `seed-odoo.py --lego-seed` re-seeded (7 offene Aufträge, Zone „Stock").
> Branch `test/cluster-live-e2e` (commit `ebff339`). Visual-Artefakt: `.claude/artifacts/cluster-live/`.
>
> [!success] Empfängerkarton-Bestätigung umgesetzt (2026-06-26) — Akzeptanz #3 + #4 erfüllt
> Der Prof-Wunsch „Bestätigung für richtigen Empfängerkarton" ist jetzt umgesetzt: im Rundgang
> bestätigt der Picker pro Position den **richtigen Ziel-Karton** per **Scan-oder-Tippen** (Hybrid);
> ein **falscher Karton** löst eine klare Warnung aus und blockiert die Bestätigung (Verwechslungsschutz).
> Backend (`confirm_cluster_line`) prüft den gescannten Karton gegen `result_package_id`
> (`_carton_matches`: Package-Name ODER -ID); bei fehlendem/falschem Karton **kein Odoo-Write** +
> Telemetrie `carton_ok=False`. Rückwärtskompatibel: Lines ohne Ziel-Package erzwingen keinen Scan.
> Touch bleibt Fallback (Invariante 5). Der **tatsächlich gescannte Token** wird ans Backend gereicht,
> sodass die Server-Prüfung echt re-validiert (Multi-Agent-Review-Fix, Defense-in-depth).
> Verifiziert: 155 Backend-Tests (5 neue Karton-Tests), 3 PWA-e2e (inkl. Verwechslungsschutz-Test),
> live BATCH/00008 + BATCH/00009 end-to-end (Karton-Schritt aktiv) mit `result_package_id` bestätigt.
> Visual: `.claude/artifacts/cluster-live/carton-02-modal.png` + `carton-03-wrong-warning.png`.
> Bekannte PoC-Grenze: `stock.quant.package` hat kein Barcode-Feld → scanbarer Identifier ist der
> Package-Name; für echtes Put-to-Box muss dieser als Barcode-Label am Karton hängen.

# Feature: Cluster-/Batch-Picking

## Beschreibung
Beim **Cluster-Picking** kommissioniert ein Picker **mehrere Aufträge gleichzeitig** in einem Durchgang —
jeder Auftrag hat seinen **eigenen Karton/Position** auf dem Wagen. Kern: beim Pick wird bestätigt,
dass der Artikel in den **richtigen Empfängerkarton** gelegt wird (Verwechslungsschutz, Effizienz durch
weniger Laufwege).

> [!info] Odoo kennt das nativ
> Odoo: **Batch Transfers / Cluster Picking** über `stock.picking.batch`. Wir bauen darauf auf — keine Parallelwelt.
> (Doku: Odoo 19 → Inventory → Operations → Picking methods → Cluster.)

**Prof-Wunsch (2026-06-22):** „Cluster-Picking (Bestätigung für richtigen Empfängerkarton)".

## Akzeptanzkriterien
- [x] Mehrere offene Pickings zu einem **Batch** zusammenfassen *(live verifiziert 2026-06-26)*
- [x] PWA führt durch die kombinierte, optimierte Route (ein Lauf, mehrere Aufträge) *(route-sortierte Sammelliste, live verifiziert)*
- [x] Beim Bestätigen: Ziel-Karton scannen/wählen → System prüft, ob es der **richtige** Auftrag/Karton ist *(2026-06-26: Scan-oder-Tippen-Modal + Backend-`_carton_matches`)*
- [x] Falscher Karton → klare Warnung (Verwechslungsschutz) *(2026-06-26: Inline-Warnung blockiert Bestätigung; live + e2e verifiziert)*
- [x] Touch-Fallback bleibt (Invariante 5) *(Bestätigen-Button ist Touch-Fallback)*

## Technische Umsetzung
### Betroffene Dateien
- `backend/app/services/picking_service.py` + `routers/pickings.py` — Batch-Abruf, Karton-Zuordnung
- `backend/app/services/odoo_client.py` — `stock.picking.batch`-Aufrufe
- `backend/app/services/route_optimizer.py` — Route über mehrere Aufträge
- `pwa/` — Batch-/Cluster-Ansicht + Karton-Bestätigung

### Odoo-Modelle
- `stock.picking.batch` (Batch/Cluster) · `stock.picking` (Aufträge im Batch) · `stock.quant.package` (Kartons)

## Notizen
- Kombiniert ideal mit [[Karton- und Behaelter-Tracking (Put-to-Box)]] (Karton-Barcode) und [[Barcode als Seriennummer-Bestätigung]] (welches Exemplar).
- Verwandt: [[Future Functions]] · [[02 - Architektur & Diagramm erklärt]]
