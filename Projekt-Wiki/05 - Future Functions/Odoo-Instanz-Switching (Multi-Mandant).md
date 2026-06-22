---
title: "Odoo-Instanz-Switching (Multi-Mandant)"
tags:
  - feature
  - future
  - architecture
  - odoo
status: planned
component: backend
created: 2026-06-22
---

# Feature: Odoo-Instanz-Switching (Multi-Mandant)

## Beschreibung

Heute ist genau **eine** Odoo-Instanz fest verdrahtet: `ODOO_URL`, `ODOO_DB`, `ODOO_API_KEY`
liegen einmalig in `.env` und werden in `backend/app/config.py` als einzelne Felder geladen.

Die Idee: Das FastAPI-Backend soll **zur Laufzeit zwischen mehreren Odoo-Instanzen umschalten** können,
ohne Neustart oder Code-Änderung — z. B.:

- die **lokale PoC-Instanz** (`masterfischer`, läuft im Docker-Stack)
- eine Instanz vom **Logistik Innovation Lab (LogILab)**

> [!note] Demo-Nutzen fürs Kolloquium
> Live zeigen, dass **dieselbe PWA** je nach Anfrage gegen das lokale Odoo **oder** das LogILab-Odoo arbeitet.
> Ein einfacher Umschalter macht den Mehrwert „Backend ist austauschbar, PWA bleibt gleich" sofort sichtbar.

## Akzeptanzkriterien
- [ ] Backend kennt ein **Register** von Odoo-Profilen (`name → url, db, api_key`)
- [ ] Pro Request wählbar (Header `X-Odoo-Instance: local | logilab` oder `?instance=`)
- [ ] **Default bleibt die lokale Instanz** → voll rückwärtskompatibel
- [ ] Umschalten ohne Neustart, ohne Re-Deploy
- [ ] Secrets bleiben aus dem Repo (env / lokale Config, nicht committen)
- [ ] Unbekanntes Profil → sauberer Fehler (`400`), kein stiller Fallback

## Technische Umsetzung

### Betroffene Dateien
- `backend/app/config.py` — Profil-Register statt einzelner `odoo_*`-Felder
- `backend/app/services/odoo_client.py` — ein `OdooClient` **pro Profil** (gecacht)
- `backend/app/dependencies.py` — `get_odoo_client()` wählt das Profil anhand des Requests
- `pwa/` (optional) — kleiner Demo-Umschalter in der Oberfläche

### API-Endpunkte
- Auswahl per Header `X-Odoo-Instance` (oder Query `?instance=`)
- optional `GET /api/instances` → Liste der verfügbaren Profile (Name + Anzeigename)

### Odoo-Modelle
- **Keine neuen Modelle.** Gleiche Modelle (`stock.picking`, `quality.alert.custom` …), nur andere Instanz/DB.

## Tests
- [ ] Unit: Profil-Auswahl liefert den richtigen Client
- [ ] Integration: ohne Header → Verhalten **identisch** zu heute (Default = lokal)
- [ ] Sicherheit: unbekanntes Profil → `400`, keine Datenvermischung

## Notizen
- **Constraint / Invariante:** Odoo bleibt **System of Record** — pro Instanz für sich. Keine Datenvermischung zwischen lokal und LogILab.
- **Risiko:** Unterschiedliche Datenmodelle/Felder je Instanz (z. B. fehlt `quality.alert.custom` extern) → ggf. Adapter / Feature-Flags pro Profil.
- **n8n-Hinweis:** Wird der Async-Pfad genutzt, müssen die Webhooks/Callbacks **instanz-bewusst** sein (richtige Instanz im Callback). Für eine reine Lese-Demo unkritisch.
- Verwandt: [[System Architektur]] · [[01 - Architektur/Odoo 18 Entscheidungen]] · [[Future Functions]]
