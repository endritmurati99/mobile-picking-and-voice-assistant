---
title: "Barcode als Seriennummer-Bestätigung (Serial/Lot-Scan)"
tags:
  - feature
  - future
  - scanning
  - odoo
status: partially-implemented
component: backend, pwa
created: 2026-06-22
---

# Feature: Barcode als Seriennummer-Bestätigung (Serial/Lot-Scan)

## Beschreibung

Heute bestätigt der Scan den **Produkt-Barcode**: die PWA scannt (HID), `POST /api/scan/validate`
prüft den Wert gegen den erwarteten Barcode, und `confirm-line` bucht die Position mit `scanned_barcode`.
Das beantwortet die Frage *„richtiger Artikel?"*.

Die Erweiterung beantwortet zusätzlich *„welches **genaue Exemplar**?"*:
Beim Bestätigen wird die **Seriennummer bzw. Charge (Lot)** des konkreten Stücks gescannt und als
Nachweis erfasst — für **Rückverfolgbarkeit** (Traceability).

> [!example] Ablauf in der PWA
> 1. Produkt-Barcode scannen → wie heute (Artikel korrekt?)
> 2. **Zweiter Scan: Seriennummer / Lot** des physischen Stücks
> 3. Backend erfasst die Seriennummer an der Move Line → bestätigt

> [!note] Prof-Wunsch (2026-06-22): Fokus auf hochwertige Güter
> Seriennummer-Dokumentation v. a. für **hochwertige Güter** (z. B. teure CPUs) — dort lohnt der Mehraufwand.
> **Optional zusätzliches Foto** beim Erfassen als visueller Nachweis (verknüpft mit der [[Lokale Bild-KI-Qualitaetspruefung (Design und Recherche)|Bild-KI]] und mit [[Karton- und Behaelter-Tracking (Put-to-Box)]] / [[Cluster- und Batch-Picking]]).

## Akzeptanzkriterien
- [x] PWA kann nach dem Produkt-Scan einen zweiten Scan „Seriennummer/Lot" erfassen
- [x] Backend schreibt die Seriennummer an die Move Line (`lot_id` fuer `tracking=serial`, `lot_name` fuer `tracking=lot`)
- [x] Bei **serialisierten** Produkten (`tracking = serial`) ist der Serial-Scan **Pflicht**, sonst optional
- [ ] Bereits verwendete / doppelte Seriennummern werden erkannt und abgelehnt
- [x] Touch-Fallback bleibt: Seriennummer auch manuell eingebbar (Invariante 5: Touch ist Fallback)
- [x] Retouren-Soll/Ist-Abgleich per API (`/api/pickings/{picking_id}/returns/reconcile`) vergleicht ausgelieferte mit zurückgescannten Seriennummern

> [!status] Stand 2026-07-03
> Der Pick-Confirm ist gehärtet: `tracking=serial` erzwingt eine vorhandene Odoo-Seriennummer (`stock.lot`) fuer genau eine Einheit und schreibt `lot_id`, statt freie Phantom-Seriennummern per `lot_name` zu erzeugen. Seit 2026-07-03 gibt es zusätzlich einen read-only Retouren-Abgleich (`/api/pickings/{picking_id}/returns/reconcile`) für `missing`, `unknown` und `duplicates`. Offen bleibt eine explizite Wiederverwendungsprüfung gegen frühere Lieferungen/Retouren sowie die Persistenz von Abweichungen.

## Technische Umsetzung

### Betroffene Dateien
- `backend/app/routers/scan.py` — erweiterter Validate-/Capture-Pfad für Serial/Lot
- `backend/app/utils/barcode.py` — Seriennummer-Parsing (z. B. GS1 Application Identifier `21` für Serial, `10` für Lot)
- `backend/app/routers/pickings.py` + `services/picking_service.py` — `confirm-line` nimmt `serial_number` / `lot_name` entgegen
- `pwa/` — zweiter Scan-Schritt im Confirm-Flow

### API-Endpunkte
- `confirm-line`-Body erweitern um `serial_number` / `lot_name`
- `POST /api/pickings/{picking_id}/returns/reconcile` zum Soll/Ist-Abgleich zurückgescannter Seriennummern
- optional `POST /api/scan/serial` zur Vorab-Validierung (analog zu `/api/scan/validate`)

### Odoo-Modelle
- `stock.lot` — Serien-/Chargennummern
- `stock.move.line.lot_id` / `lot_name` — Zuordnung zur gebuchten Menge
- `product.product.tracking` (`none | lot | serial`) — steuert, ob Pflicht

## Tests
- [ ] EAN/GS1-Parsing inkl. AI `21` (Serial) und `10` (Lot)
- [x] Pflicht-Erzwingung bei `tracking = serial`
- [ ] Duplikat-/Wiederverwendungs-Erkennung
- [x] Touch-Eingabe als Fallback funktioniert
- [x] Retouren-Abgleich erkennt fehlende, unbekannte und doppelt zurückgegebene Seriennummern

## Notizen
- **Baut auf vorhandener Scan-Infrastruktur auf** (HID-Scan + `/scan/validate`) — keine Parallelwelt.
- Sinnvoll nur für Produkte mit `tracking = serial | lot`; bei `none` bleibt der heutige Flow.
- Verwandt: [[03 - Features/Phase 3 - Barcode Scanning]] · die „MQTT-Barcode-Scanner"-Idee in [[Future Functions]] · [[System Architektur]]
