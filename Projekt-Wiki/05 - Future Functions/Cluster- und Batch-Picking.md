---
title: "Cluster-/Batch-Picking (richtiger Empfängerkarton)"
tags:
  - feature
  - future
  - picking
  - odoo
status: planned
component: backend, pwa, odoo
created: 2026-06-22
---

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
- [ ] Mehrere offene Pickings zu einem **Batch** zusammenfassen
- [ ] PWA führt durch die kombinierte, optimierte Route (ein Lauf, mehrere Aufträge)
- [ ] Beim Bestätigen: Ziel-Karton scannen/wählen → System prüft, ob es der **richtige** Auftrag/Karton ist
- [ ] Falscher Karton → klare Warnung (Verwechslungsschutz)
- [ ] Touch-Fallback bleibt (Invariante 5)

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
