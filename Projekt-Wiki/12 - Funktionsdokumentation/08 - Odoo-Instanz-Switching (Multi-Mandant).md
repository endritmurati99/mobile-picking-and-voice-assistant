---
title: "Odoo-Instanz-Switching (Multi-Mandant)"
tags: [funktionsdoku, odoo, pwa, multi-mandant]
status: dokumentiert
stand: 2026-07-04
---

# Odoo-Instanz-Switching (Multi-Mandant)

> [!abstract] Kurzfassung
> Die PWA kann zur Laufzeit zwischen konfigurierten Odoo-Profilen wechseln. Sichtbar ist das als Lager-Umschalter rechts oben in der Kopfzeile. Technisch setzt `pwa/js/api.js` zentral den Header `X-Odoo-Instance`; FastAPI loest diesen Header in `resolve_instance` auf und nutzt pro Profil einen eigenen gecachten `OdooClient`. Ohne Auswahl bleibt alles bei `local`.

## 1. Wie es funktioniert

1. Das Backend baut aus den bestehenden `ODOO_*`-Variablen immer das Profil `local` und liest weitere Profile aus `ODOO_INSTANCES_JSON` (`backend/app/config.py:53`).
2. `GET /api/instances` gibt nur `name` und `display_name` aus (`backend/app/routers/instances.py:10`).
3. Die PWA befuellt den Select `#instance-switch` beim Start ueber `getInstances()` (`pwa/js/app.js:574`, `pwa/js/api.js:226`).
4. Waehlt der Picker ein anderes Lager, speichert die PWA den Profilnamen in `localStorage` und laedt die App neu (`pwa/js/app.js:621`).
5. Alle Folge-Requests erhalten zentral in `request(...)` den Header `X-Odoo-Instance`, aber nur wenn die aktive Instanz nicht `local` ist (`pwa/js/api.js:194`).
6. FastAPI normalisiert den Header oder Query-Parameter `?instance=` in `resolve_instance`; unbekannte Profile werden mit HTTP 400 abgelehnt (`backend/app/dependencies.py:51`).
7. `get_request_odoo_client` liefert den passenden Client aus dem Per-Profil-Cache (`backend/app/dependencies.py:62`).

## 2. Wie es mit Odoo kommuniziert

Jedes Profil besitzt eigene Verbindungsdaten (`url`, `db`, `user`, `api_key`/`password`). Der `OdooClient` nimmt ein `OdooProfile` entgegen (`backend/app/services/odoo_client.py:20`) und kapselt dadurch URL, Datenbank und Auth-Secret pro Instanz. Der Client-Cache in `dependencies.py` trennt die Auth-/UID-Caches je Profil.

Direkte nutzerseitige Sync-Pfade nutzen den request-aware Client:

- Produktbild/Picker-nahe direkte Odoo-Zugriffe in `pickings.py` (`backend/app/routers/pickings.py:109`)
- Quality-Alert-Anlage in `quality.py` (`backend/app/routers/quality.py:173`)
- Voice-Assist-Odoo-Kontext in `voice.py` (`backend/app/routers/voice.py:345`)

Die Service-Factories fuer Picking, Cluster und Mobile Workflow beziehen ebenfalls `get_request_odoo_client` (`backend/app/dependencies.py:67`, `:74`, `:81`). n8n-Callbacks bleiben im PoC bewusst auf der lokalen Instanz ueber `get_odoo_client`, damit keine Rueckschreibungen versehentlich in eine externe Demo-Instanz laufen.

## 3. Was genau zugegriffen wird

Der Odoo-Switch legt keine neuen Odoo-Modelle an. Er entscheidet nur, welche Odoo-Instanz die bestehenden Zugriffe bedient.

| Bereich | Technischer Zugriff | Instanzverhalten |
|---|---|---|
| Picker/Pickings | bestehende Reads/Writes auf `res.users`, `stock.picking`, `stock.move.line`, `stock.move` | folgt `X-Odoo-Instance` |
| Produktbilder | `product.product` Bildfelder | folgt `X-Odoo-Instance` |
| Bestand/Fehlbestand | `stock.quant` und Nachschub-Kontext | folgt bei direktem Read der Auswahl; n8n-Folgepfade bleiben PoC-Grenze |
| Quality Alert | `quality.alert.custom` ueber das Custom-Addon | Anlage folgt der Auswahl; Callback-Auswertung bleibt aktuell `local` |
| Charge/Seriennummer | `product.product.tracking`, `stock.lot`, `stock.quant`, `stock.move.line.lot_id` | folgt der gewaehlten Instanz im Confirm-Pfad |

## 4. PWA-Seite

- `#instance-switch` sitzt in der Header-Action-Leiste (`pwa/index.html:21`).
- `getActiveInstance()` und `setActiveInstance()` kapseln den `localStorage`-Wert (`pwa/js/api.js:79`, `:83`).
- `request(...)` haengt den Header an einer zentralen Stelle an (`pwa/js/api.js:194`).
- Der Playwright-Test `e2e/instance-switch.spec.js` prueft, dass nach Wechsel auf `Lager 2` ein Folge-Request `X-Odoo-Instance: lager-2` sendet.

## 5. Live-Test-Voraussetzungen

Fuer eine zweite reale Odoo-Instanz reicht der Switch allein nicht; die Zielinstanz muss fachlich denselben Mindeststand haben:

- `quality_alert_custom` muss installiert/aktualisiert sein.
- Picker-Benutzer muessen aktiv und intern sein.
- Testprodukte brauchen Barcodes.
- Serienpflichtige Produkte brauchen `tracking = serial` oder `tracking = lot`.
- Erwartete Lagerplaetze brauchen verfuegbaren Bestand (`stock.quant`).

Diese Punkte sind bewusst als eigene Integrations-Checkliste dokumentiert, weil sie Daten-/Addon-Setup in Odoo betreffen und nicht nur PWA/FastAPI-Code.

Im lokalen Stack gibt es dafuer ein optionales Compose-Profil `second-odoo`: `odoo-lager-2` laeuft mit eigenem Filestore auf Host-Port `8070` und nutzt die DB `lager2`. Das Backend nimmt dieses Profil nur dann in die PWA-Liste auf, wenn `ODOO_INSTANCES_JSON` einen Eintrag wie `lager-2` enthaelt.

## 6. Odoo-19-Trial als aktueller Demo-Mandant

Seit 2026-07-04 ist zusaetzlich das Profil `o19-trial` angebunden. Es zeigt auf die migrierte Trial-Datenbank `masterfischer_o19_trial` und dient ausschliesslich fuer Demo, Migrationstest und Traceability-Umschaltung.

Aktueller Stand:

| Profil | Zweck | Odoo | DB | Port |
| --- | --- | --- | --- | --- |
| `local` | Live/Default | 18.0 | `masterfischer` | `8069` |
| `lager-2` | zweite Testinstanz | 18.0 | `lager2` | `8070` |
| `o19-trial` | Odoo-19-Demo/Migration | 19.0 | `masterfischer_o19_trial` | `8100` |

Der Trial-Mandant ist in der PWA bewusst ueber denselben Instanzschalter erreichbar. Nur dort erscheint der Traceability-Demo-Schalter. Die Demo-API ist zusaetzlich serverseitig auf erlaubte DBs begrenzt (`DEMO_TRACEABILITY_ALLOWED_DBS=masterfischer_o19_trial`), damit keine Produkt-Tracking-Stammdaten in der Live-DB versehentlich umgeschaltet werden.

Docker-Sicherheit:

- `odoo` bleibt Default/Live-Odoo 18 und ist im Compose-Build hart auf `odoo:18.0` gepinnt.
- `odoo` und `odoo-lager-2` mounten `odoo/addons18`.
- `odoo19-trial` ist ein eigener Compose-Service mit Profil `odoo19-trial`.
- `odoo19-trial` mountet den Odoo-19-Port unter `odoo/addons`.
- `odoo19-trial` verwendet `odoo/odoo19-trial.conf` mit `dbfilter = ^masterfischer_o19_trial$`.
- Ein normaler Compose-Start soll nicht automatisch Odoo 19 gegen `masterfischer` starten.

## 7. Quellen im Code

- `backend/app/config.py:7`, `:53-90` — `OdooProfile`, `get_instance_registry`
- `backend/app/dependencies.py:18-62` — Per-Profil-Cache, `resolve_instance`, `get_request_odoo_client`
- `backend/app/routers/instances.py:10-14` — `GET /api/instances`
- `backend/app/services/odoo_client.py:20-41` — Client pro Profil
- `docker-compose.yml:64-88`, `odoo/odoo-lager2.conf` — optionale zweite lokale Odoo-Testinstanz
- `docker-compose.yml` — `odoo` als Odoo-18-Default, `odoo19-trial` als explizites Odoo-19-Profil
- `odoo/odoo19-trial.conf` — Trial-DB-Filter fuer `masterfischer_o19_trial`
- `pwa/js/api.js:79-94`, `:190-198`, `:226` — aktive Instanz, Header, `getInstances`
- `pwa/js/app.js:574-624` — PWA-Umschalter
- `e2e/instance-switch.spec.js` — Browser-Regressionstest
