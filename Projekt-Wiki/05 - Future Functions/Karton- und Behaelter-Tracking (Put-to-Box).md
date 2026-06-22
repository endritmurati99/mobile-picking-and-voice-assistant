---
title: "Karton- und Behälter-Tracking (Put-to-Box)"
tags:
  - feature
  - future
  - scanning
  - odoo
  - traceability
status: planned
component: backend, pwa
created: 2026-06-22
---

# Feature: Karton- und Behälter-Tracking (Put-to-Box)

## Beschreibung

Beim Kommissionieren legt der Picker die Artikel in einen **Korb / Karton / Behälter**.
Dieser Behälter hat **selbst einen Barcode**. Die Idee: per Klick/Scan wird der Artikel diesem
Behälter zugeordnet — der Behälter wird zum **gelabelten Versandkarton (Package)**.

**Nutzen — lückenlose Rückverfolgbarkeit:** Es ist nachweisbar, **welcher Artikel in welchem Karton**
liegt und an welchen Kunden er geht. Sinngemäß: *„Ich bin sicher, dass die teure CPU wirklich beim
richtigen Kunden ankommt — und nicht verloren geht."*

> [!info] Passt direkt auf Odoo
> Odoo kennt dieses Konzept bereits als **„Put in Pack"** über `stock.quant.package`
> (`result_package_id` an der Move Line). Wir bauen also auf Bestehendem auf, keine Parallelwelt.

## Akzeptanzkriterien
- [ ] PWA-Aktion „In Karton legen" pro bestätigter Position
- [ ] Karton-Barcode scannen → Behälter (Package) anlegen/zuordnen
- [ ] Backend setzt `result_package_id` an den betroffenen Move Lines in Odoo
- [ ] Mehrere Artikel in denselben Karton möglich; ein Karton ↔ ein Kunde/Auftrag
- [ ] Übersicht „Was ist in Karton X?" abrufbar (Rückverfolgbarkeit)
- [ ] Touch-Fallback bleibt (Karton manuell wählbar)

## Technische Umsetzung

### Betroffene Dateien
- `backend/app/routers/pickings.py` + `services/picking_service.py` — Aktion „put in pack", `result_package_id` setzen
- `backend/app/routers/scan.py` — Karton-Barcode validieren/auflösen
- `backend/app/services/odoo_client.py` — Aufruf der Odoo-Package-Logik
- `pwa/` — Button „In Karton legen" + Karton-Scan-Schritt

### API-Endpunkte
- `POST /api/pickings/{id}/put-in-pack` (Body: `move_line_ids`, `package_barcode`)
- optional `GET /api/packages/{barcode}` → Inhalt/Status eines Kartons

### Odoo-Modelle
- `stock.quant.package` — der Karton/Behälter (Barcode = `name`)
- `stock.move.line.result_package_id` — Zuordnung Artikel → Karton
- ggf. `stock.package.type` — Karton-Typ/Größe

## Tests
- [ ] Karton anlegen + Artikel zuordnen
- [ ] mehrere Artikel in einen Karton
- [ ] Inhaltsabfrage „Was ist in Karton X?"
- [ ] Karton-Barcode unbekannt → sauberer Fehler

## Notizen
- **Kombiniert ideal mit** [[Barcode als Seriennummer-Bestätigung]]: Serial (welches Stück) **+** Package (in welchem Karton) = vollständige Kette Artikel → Exemplar → Karton → Kunde.
- **Constraint / Invariante:** Odoo bleibt System of Record (Package liegt in Odoo). Touch ist Fallback.
- Verwandt: [[03 - Features/Phase 3 - Barcode Scanning]] · [[System Architektur]] · [[Future Functions]]
