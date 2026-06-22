---
title: "Kommunikation & Datenaktualität (Pull vs Push)"
tags:
  - architecture
  - rpc
  - odoo
  - docker
  - current-state
created: 2026-06-22
---

# Kommunikation & Datenaktualität (Pull vs Push)

> [!question] Frage von Prof. Fischer (2026-06-22)
> „Wie kommuniziert die Software (FastAPI im Container) mit Docker / mit Odoo? Wenn man Änderungen *sofort* sieht, bräuchte man einen Webhook aus Odoo — den gibt es aber nicht (Odoo wurde nicht verändert). Greift man von außen per RPC zu (pollt), sieht man Änderungen nicht sofort."

## Die Auflösung: zwei verschiedene „Änderungen" werden vermischt

### 1. Code-Änderungen (Entwicklung) — sofort, OHNE Odoo-Webhook
Hat **nichts** mit Odoo zu tun — rein ein Docker-Mechanismus:
- Backend-Code ist als **Volume** in den Container gemountet (`./backend/app` → `/app/app`).
- `uvicorn --reload` startet den Prozess bei Dateiänderung automatisch neu (~1–2 s).
→ Das ist die „sofort sichtbare Änderung", die wir besprochen haben. Details: [[04 - Dev-Workflow Code ändern]].

### 2. Odoo-Daten-Änderungen — Pull on demand, kein Push
- Backend ↔ Odoo läuft über **JSON-RPC** (Request/Response). Das Backend **fragt** Odoo; Odoo ruft **nie** von sich aus das Backend.
- **Kein Webhook in Odoo** → Odoo bleibt unverändert (Architektur-Invariante).
- **Kein Hintergrund-Polling** → das Backend fragt Odoo nur, wenn die **PWA** etwas anfordert (Liste laden, Pull-to-Refresh, Bestätigung senden).

> [!note] Folge
> - Was der **Picker über die App** tut → sofort in Odoo (die App schreibt synchron per JSON-RPC).
> - Was **jemand direkt in Odoo** ändert → die App sieht es beim **nächsten Abruf/Refresh**, nicht in Echtzeit gepusht.

Das ist eine **bewusste Pull-Entscheidung**, genau um Odoo **nicht** zu verändern. Für einen Picking-Assistenten passend: Der **Picker ist der Akteur** — die App treibt den Ablauf, schreibt direkt nach Odoo und holt sich für ihre eigenen Schritte stets den aktuellen Stand.

## Wie „mit Docker kommuniziert"
Docker liefert nur **Netzwerk + Namensauflösung (DNS)**. Die Container reden über das Netz `picking-net` per **Service-Namen**: Backend erreicht Odoo als `odoo:8069`, dazu `whisper:9000`, `piper:5500`, `n8n:5678`. Die Kommunikation selbst ist normales **HTTP** (JSON-RPC zu Odoo, REST `/api` zur PWA, Webhooks zu/von n8n). Siehe [[03 - Docker & Container]] · [[02 - Architektur & Diagramm erklärt]].

## Wenn echtes Echtzeit-Push nötig wäre (Optionen)
| Option | Bedeutet | Bewertung |
| --- | --- | --- |
| Odoo-Automation / Webhook aus Odoo | Odoo schickt bei Änderung aktiv ans Backend | **Verändert Odoo** → gegen Invariante |
| Polling | Backend fragt Odoo periodisch ab | nicht „sofort", erzeugt Dauerlast |
| n8n-Events (heute) | App feuert Events an n8n (nicht Odoo→App) | bereits genutzt; aber **kein** Odoo→App-Push |

→ Für den PoC ist **Pull on demand** die richtige und ehrliche Wahl.

## Bezug Odoo 19 (Schnittstelle)
`/jsonrpc` ist in **Odoo 19 als deprecated markiert, funktioniert aber weiterhin** (Entfernung erst Odoo Online 19.1 / on-prem Odoo 20 / vollständig Odoo 22, ~2028). Nachfolger ist die **JSON-2-API** (`POST /json/2/<model>/<method>`, API-Key im `Authorization: Bearer`-Header, saubere HTTP-Statuscodes). Ein Umstieg auf Odoo 19 bricht unseren JSON-RPC-Client also **kurzfristig nicht**, der saubere Zukunftsweg wäre aber JSON-2.

## Verwandt
- [[04 - Dev-Workflow Code ändern]] · [[05 - Backend (FastAPI)]] · [[06 - Odoo]] · [[07 - n8n]]
