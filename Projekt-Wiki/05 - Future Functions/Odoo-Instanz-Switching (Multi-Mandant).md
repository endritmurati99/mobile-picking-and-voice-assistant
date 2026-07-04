---
title: "Odoo-Instanz-Switching (Multi-Mandant)"
tags:
  - feature
  - future
  - architecture
  - odoo
status: implemented
component: backend,pwa
created: 2026-06-22
implemented: 2026-06-29
---

# Feature: Odoo-Instanz-Switching (Multi-Mandant)

## Beschreibung

Früher war genau **eine** Odoo-Instanz fest verdrahtet: `ODOO_URL`, `ODOO_DB`, `ODOO_API_KEY`
lagen einmalig in `.env` und wurden in `backend/app/config.py` als einzelne Felder geladen.

Umgesetzt ist jetzt: Das FastAPI-Backend kann **zur Laufzeit zwischen mehreren Odoo-Instanzen umschalten**,
ohne Neustart oder Code-Änderung. Die PWA zeigt dafür rechts oben einen kompakten Lager-Umschalter. Fachlich
wird das im Kolloquium als Lager-/Instanz-Auswahl gezeigt, technisch wird pro Request der Header
`X-Odoo-Instance` gesetzt.

Mögliche Profile:

- die **lokale PoC-Instanz** (`masterfischer`, läuft im Docker-Stack)
- eine zweite lokale oder externe Instanz (z. B. LogILab oder „Lager 2")

> [!note] Demo-Nutzen fürs Kolloquium
> Live zeigen, dass **dieselbe PWA** je nach Anfrage gegen das lokale Odoo **oder** das LogILab-Odoo arbeitet.
> Ein einfacher Umschalter macht den Mehrwert „Backend ist austauschbar, PWA bleibt gleich" sofort sichtbar.

## Akzeptanzkriterien
- [x] Backend kennt ein **Register** von Odoo-Profilen (`name → url, db, api_key`)
- [x] Pro Request wählbar (Header `X-Odoo-Instance: local | lager-2` oder `?instance=`)
- [x] **Default bleibt die lokale Instanz** → voll rückwärtskompatibel
- [x] Umschalten ohne Neustart, ohne Re-Deploy
- [x] Secrets bleiben aus dem Repo (env / lokale Config, nicht committen)
- [x] Unbekanntes Profil → sauberer Fehler (`400`), kein stiller Fallback
- [x] `GET /api/instances` liefert nur `name` und `display_name`, keine URL/DB/Secrets
- [x] PWA-Umschalter setzt den Header zentral über `pwa/js/api.js`

## Technische Umsetzung

### Betroffene Dateien
- `backend/app/config.py` — Profil-Register zusätzlich zu den bestehenden `odoo_*`-Feldern
- `backend/app/services/odoo_client.py` — ein `OdooClient` **pro Profil** (gecacht)
- `backend/app/dependencies.py` — `get_request_odoo_client()` wählt das Profil anhand des Requests
- `backend/app/routers/instances.py` — `/api/instances`
- `pwa/js/api.js` — zentraler Header `X-Odoo-Instance`
- `pwa/index.html`, `pwa/js/app.js`, `pwa/css/app.css` — Lager-Umschalter in der Oberfläche
- `docker-compose.yml`, `odoo/odoo-lager2.conf` — optionales lokales Profil `second-odoo` fuer eine zweite Odoo-Testinstanz

### API-Endpunkte
- Auswahl per Header `X-Odoo-Instance` (oder Query `?instance=`)
- optional `GET /api/instances` → Liste der verfügbaren Profile (Name + Anzeigename)

### Odoo-Modelle
- **Keine neuen Modelle.** Gleiche Modelle (`stock.picking`, `quality.alert.custom` …), nur andere Instanz/DB.

## Tests
- [x] Unit: Profil-Auswahl liefert den richtigen Client
- [x] Integration: ohne Header → Verhalten **identisch** zu heute (Default = lokal)
- [x] Sicherheit: unbekanntes Profil → `400`, keine Datenvermischung
- [x] PWA-Unit: Header nur bei Nicht-`local`, `getInstances()` ruft `/api/instances`
- [x] Playwright: Lager-Umschalter setzt `X-Odoo-Instance` auf Folge-Requests

## Live-Test mit zweiter Instanz

Für den echten End-to-End-Test braucht die zweite Odoo-Instanz denselben fachlichen Mindeststand wie die lokale PoC-Instanz:

- `quality_alert_custom` muss installiert oder aktualisiert sein, sonst scheitert `POST /api/quality-alerts` beim Modell `quality.alert.custom`.
- Die Testprodukte müssen Barcodes tragen, sonst kann der Scanner keine fachliche Bestätigung prüfen.
- Serien-/chargengeführte Produkte müssen in Odoo `tracking = serial` oder `tracking = lot` haben, sonst schreibt das Backend keine `lot_name`-Seriennummer.
- Es muss Bestand (`stock.quant`) am erwarteten Lagerplatz vorhanden sein, sonst blockiert der Confirm-Pfad mit `out_of_stock`.
- Picker-Benutzer müssen aktiv und intern sein (`res.users`, nicht Portal/Share), sonst kann die PWA keine Session starten.
- Die Lager-/Instanznamen für die PWA kommen aus `display_name` in `ODOO_INSTANCES_JSON`, z. B. `Lager 1` und `Lager 2`.
- Lokal kann die zweite Testinstanz ueber `docker compose --profile second-odoo up -d odoo-lager-2` auf Port `8070` gestartet werden; die Datenbank heisst im dokumentierten Testsetup `lager2`.

## Folgepunkte aus dem Review vom 2026-06-29

- **Quality-Addon-Parität:** Prüfen, ob jede Zielinstanz das Custom-Addon und die `ai_*`-Felder besitzt.
- **Seriennummern-Datenqualität:** Für Demo-Produkte muss Tracking bewusst gesetzt sein; wenn es fehlt, eigene Testprodukte mit Seriennummernpflicht anlegen.
- **Bestands-Setup:** Für beide Lager/Instanzen Seed-Daten oder manuelle Odoo-Bestände anlegen, damit Scanner- und Confirm-Flows real durchlaufen.
- **Scanner-Funktion schärfen:** Der vorhandene Scanner ist bereits mit Barcode-Confirm verbunden; für die zweite Instanz müssen die Barcodes in Odoo konsistent gepflegt sein.
- **Fehlbestand/Quality-Pfad live prüfen:** Shortage- und Quality-Flows hängen am Custom-Addon und an n8n; das bleibt ein separater Live-Stack-Test nach Docker-Start.

## Notizen
- **Constraint / Invariante:** Odoo bleibt **System of Record** — pro Instanz für sich. Keine Datenvermischung zwischen lokal und Lager 2.
- **Risiko:** Unterschiedliche Datenmodelle/Felder je Instanz (z. B. fehlt `quality.alert.custom` extern) → ggf. Adapter / Feature-Flags pro Profil.
- **n8n-Hinweis:** Der aktuelle PoC lässt n8n-Callbacks bewusst auf `local`; volle n8n-Instanz-Bewusstheit ist eine spätere Erweiterung.
- Verwandt: [[System Architektur]] · [[01 - Architektur/Odoo 18 Entscheidungen]] · [[Future Functions]]
