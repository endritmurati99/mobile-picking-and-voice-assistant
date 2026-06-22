---
title: Glossar
tags:
  - glossar
  - grundlagen
  - referenz
  - projekt-wiki
created: 2026-06-22
---

# Glossar

> [!info] Was ist das hier?
> Diese Notiz erklärt die wichtigsten technischen Begriffe des Projekts **„Mobile Picking und Voice Assistant"** in 2–4 einfachen Sätzen. Sie dient zwei Zielgruppen: (a) einem KI-Agenten, der daraus zitierfähige Textbausteine für die Bachelorarbeit zieht, und (b) dem Autor, um die Konzepte schnell nachzuschlagen. Wo möglich sind konkrete Beispiele aus diesem Projekt (Dateipfade, Endpunkte, Odoo-Modelle) hinterlegt, damit der Begriff nicht abstrakt bleibt.

> [!note] Lesehinweis
> Die Begriffe sind **alphabetisch** sortiert. Quellenbezüge stammen aus den Analysen von Backend (FastAPI), Infrastruktur (Docker/Caddy) und n8n-Workflows dieses Projekts. Wo eine Aussage über die belegten Quellen hinausgeht, ist sie ausdrücklich als **Annahme** markiert.

Verwandte Notizen: [[00 - Start Hier (Übersichtskarte)]] · [[02 - Architektur & Diagramm erklärt]] · [[03 - Docker & Container]] · [[05 - Backend (FastAPI)]] · [[07 - n8n]] · [[08 - PWA & Voice-Pfad]]

---

## Schnell-Index

| Begriff | Kurz | Wo im Projekt |
|---|---|---|
| [API / Schnittstelle](#api--schnittstelle) | Definierter Zugang zu einer Software | FastAPI-Backend unter `/api/*` |
| [Callback](#callback) | Rückruf eines Systems an ein anderes | n8n → `/api/internal/n8n/*` |
| [Caddy → siehe Reverse Proxy](#reverse-proxy-caddy) | HTTPS-Eingangstür | `infrastructure/caddy/Caddyfile` |
| [Container](#container) | Isoliert laufendes Programmpaket | Alle 10 Dienste |
| [Docker](#docker) | Werkzeug zum Bau/Betrieb von Containern | `docker-compose.yml` |
| [ERP / Odoo](#erp--odoo) | Warenwirtschaftssystem | Odoo 18 Community |
| [FastAPI](#fastapi) | Python-Web-Framework | `backend/app/main.py` |
| [Hot-Reload](#hot-reload) | Auto-Neuladen bei Codeänderung | `uvicorn --reload` |
| [HTTPS / mkcert](#https--mkcert) | Verschlüsselte Verbindung + Zertifikate | `infrastructure/certs/` |
| [Idempotenz](#idempotenz) | Wiederholung ohne Doppelwirkung | `picking.assistant.idempotency` |
| [Image](#image) | Bauplan/Vorlage für Container | `backend/Dockerfile` |
| [Intent-Engine](#intent-engine) | Absichtserkennung aus Text | `intent_engine.py` |
| [JSON-RPC](#json-rpc) | Methodenaufruf über JSON | `odoo_client.py` |
| [Orchestrator](#orchestrator) | Dirigent für Abläufe | n8n |
| [picking-net](#picking-net) | Internes Docker-Netzwerk | `docker-compose.yml` |
| [PWA](#pwa-progressive-web-app) | Web-App wie native App | `pwa/` |
| [Reverse Proxy (Caddy)](#reverse-proxy-caddy) | Verteilt Anfragen an Dienste | `caddy`-Service |
| [REST](#rest) | Stil für Web-Schnittstellen | `/api/pickings`, `/api/voice` |
| [STT (Whisper)](#stt-whisper) | Sprache → Text | `whisper_client.py` |
| [System of Record](#system-of-record) | Die führende Datenquelle | Odoo |
| [TTS (Piper)](#tts-piper) | Text → Sprache | `piper_client.py` |
| [Volume / Mount](#volume--mount) | Daten/Ordner in Container einhängen | `./backend/app:/app/app` |
| [Webhook](#webhook) | „Push"-Benachrichtigung per HTTP | n8n-Webhooks |

---

## API / Schnittstelle

Eine **API** (Application Programming Interface) ist ein klar definierter Zugang, über den ein Programm Funktionen eines anderen Programms nutzen kann – wie eine Steckdose, bei der nur die Form des Steckers zählt, nicht die Verkabelung dahinter. In diesem Projekt stellt das FastAPI-Backend seine API unter dem Präfix `/api` bereit (registriert in `backend/app/main.py`), z. B. `GET /api/health` oder `POST /api/pickings/{picking_id}/confirm-line`. Die PWA spricht **ausschließlich** mit dieser API und nie direkt mit Odoo oder n8n – das ist eine bewusste Architektur-Invariante.

> [!info] Im Projekt
> Interaktive API-Dokumentation: `/api/docs`, Maschinen-Schema: `/api/openapi.json` (gesetzt in `main.py`).

## Callback

Ein **Callback** ist ein „Rückruf": Statt auf eine Antwort zu warten, ruft das aufgerufene System später aktiv beim ursprünglichen Aufrufer zurück, sobald es fertig ist. In diesem Projekt nutzt n8n Callbacks, um Ergebnisse asynchroner Verarbeitung zurück ins Backend zu schreiben – etwa nach einer KI-Qualitätsbewertung über `POST /api/internal/n8n/quality-assessment` (definiert in `backend/app/routers/n8n_internal.py`). Jeder Callback ist mit dem Header `X-N8N-Callback-Secret` abgesichert und über einen `Idempotency-Key` gegen Doppelausführung geschützt.

> [!note] Abgrenzung zu Webhook
> Grob: Ein **Webhook** ist die Tür, an die das fremde System klopft; ein **Callback** ist hier der konkrete Rückruf von n8n an das Backend, nachdem ein Arbeitsschritt erledigt ist. Beide sind technisch HTTP-POSTs – der Unterschied liegt in Richtung und Zweck.

## Container

Ein **Container** ist ein leichtgewichtiges, isoliert laufendes Paket aus einem Programm und allem, was es zum Laufen braucht (Bibliotheken, Konfiguration). Man kann ihn sich wie eine standardisierte Versandbox vorstellen: Innen ist alles fertig eingerichtet, außen passt sie auf jedes „Schiff" (jeden Rechner). In diesem Projekt läuft jeder Dienst in seinem eigenen Container – insgesamt zehn (u. a. `caddy`, `db`, `odoo`, `backend`, `whisper`, `piper`, `n8n`, `pwa`), definiert in `docker-compose.yml`.

## Docker

**Docker** ist das Werkzeug, mit dem Container gebaut, gestartet und verwaltet werden. Statt Software mühsam direkt auf dem Betriebssystem zu installieren, beschreibt man einmal, was gebraucht wird, und Docker erzeugt daraus reproduzierbar laufende Container – auf jedem Rechner gleich. Das Projekt nutzt **Docker Compose** (`docker-compose.yml`), um alle Dienste mit einem Befehl (`docker compose up -d` bzw. `make up`) gemeinsam zu starten.

> [!info] Hierarchie der drei Begriffe
> **Dockerfile** (Rezept) → `docker build` → **Image** (Tiefkühlgericht) → `docker run` → **Container** (das servierte, laufende Gericht). Siehe [[03 - Docker & Container]].

## ERP / Odoo

Ein **ERP** (Enterprise Resource Planning) ist eine Unternehmenssoftware, die zentrale Geschäftsprozesse wie Lager, Einkauf, Verkauf und Buchhaltung in einem System bündelt. **Odoo** ist das in diesem Projekt eingesetzte ERP (Version 18 Community), das die Lager- und Picking-Daten verwaltet. Es läuft als eigener Container (Build aus `odoo/Dockerfile`) und ist in diesem Projekt das [System of Record](#system-of-record). Das Backend spricht mit Odoo über [JSON-RPC](#json-rpc) (`backend/app/services/odoo_client.py`).

> [!info] Odoo-18-Besonderheiten (belegt aus `odoo_client.py`)
> - Mengenfeld heißt `stock.move.line.quantity` (nicht mehr `qty_done`).
> - Bewegungen liegen unter `stock.picking.move_ids` (nicht `move_lines`).
> - Eigene Modelle des Projekts: `quality.alert.custom` und `picking.assistant.idempotency`.

## FastAPI

**FastAPI** ist ein modernes Python-Framework zum Bauen von Web-APIs. Es ist schnell, prüft eingehende Daten automatisch (über Pydantic-Modelle) und erzeugt selbsttätig eine API-Dokumentation. In diesem Projekt ist FastAPI das Herzstück des Backends – die App wird in `backend/app/main.py` als `FastAPI(title="Picking Assistant API", ...)` erstellt und bündelt Router für Picking, Voice, Quality, Scan und n8n-Callbacks.

> [!info] Im Projekt
> Das Backend enthält die [Intent-Engine](#intent-engine), ruft Odoo per [JSON-RPC](#json-rpc) auf, spricht [Whisper](#stt-whisper) und [Piper](#tts-piper) an und tauscht Events mit [n8n](#orchestrator) aus. Start im Container: `uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload`.

## Hot-Reload

**Hot-Reload** bedeutet, dass laufende Software bei einer Code-Änderung automatisch neu lädt, ohne dass man sie manuell neu starten muss – man speichert, und Sekunden später ist die Änderung aktiv. Im Backend ist dies durch den Uvicorn-Schalter `--reload` aktiviert (siehe `command` des `backend`-Service in `docker-compose.yml`): Dateien unter `./backend/app` lösen einen automatischen Neustart aus (~1–2 s), ganz ohne `docker compose restart`.

> [!warning] Grenze des Hot-Reload
> Hot-Reload greift nur bei **Python-Code** unter `backend/app`. Ändert sich `requirements.txt` oder das `Dockerfile`, muss das Image neu gebaut werden: `make build-backend && docker compose up -d`. Beim Frontend (`pwa/`) reicht dank statischer Auslieferung ein Browser-Refresh (F5). Siehe [[04 - Dev-Workflow Code ändern]].

## HTTPS / mkcert

**HTTPS** ist die verschlüsselte Variante von HTTP: Die Verbindung zwischen Browser und Server ist gegen Mitlesen geschützt. Damit der Browser der Verbindung vertraut, braucht es ein **Zertifikat** – im Internet von einer offiziellen Stelle, lokal von **mkcert**, einem Werkzeug, das selbst gültige Entwickler-Zertifikate ausstellt. Das Projekt erzeugt seine Zertifikate per `infrastructure/scripts/setup-certs.sh <LAN-IP>` und legt sie als `cert.pem`/`key.pem` in `infrastructure/certs/` ab; [Caddy](#reverse-proxy-caddy) nutzt sie für den Port 443.

> [!info] Warum HTTPS hier Pflicht ist
> Die [PWA](#pwa-progressive-web-app) benötigt für Mikrofonzugriff (Voice) und Service Worker eine sichere Herkunft (HTTPS). Für mobile Testgeräte muss zusätzlich das mkcert-Root-Zertifikat (`mkcert -CAROOT`/`rootCA.pem`) auf iOS/Android installiert werden.

## Idempotenz

**Idempotenz** heißt: Dieselbe Operation mehrfach auszuführen, hat genau dieselbe Wirkung wie einmalig. Beispiel: Ein Lichtschalter, der gezielt „an" schaltet, bleibt auch beim zweiten Drücken „an" – kein Schaden durch Wiederholung. Das ist entscheidend, wenn ein Handheld bei wackeligem WLAN eine Anfrage doppelt sendet: Eine Pick-Bestätigung darf nicht doppelt verbucht werden. Im Projekt sichern alle Schreib-Endpunkte dies über einen `Idempotency-Key`-Header plus einen SHA256-Fingerabdruck der Nutzdaten ab.

> [!info] Mechanismus (belegt aus `mobile_workflow.py` / `dependencies.py`)
> Der Zustand wird in der Odoo-Tabelle **`picking.assistant.idempotency`** gespeichert (Felder u. a. `endpoint`, `idempotency_key`, `fingerprint`, `status`, `response_payload`, `status_code`). Statusverlauf: `reserved → finalized | aborted | replay | pending | conflict`. Gleicher Key + gleicher Fingerabdruck → gecachte Antwort wird zurückgegeben; gleicher Key, aber **anderer** Fingerabdruck → HTTP 409 (Conflict). Speicherdauer (TTL): `mobile_idempotency_ttl_seconds`, Standard 86400 s = 24 h.

## Image

Ein **Image** ist die unveränderliche Vorlage, aus der ein [Container](#container) gestartet wird – vergleichbar mit einem Tiefkühlgericht: einmal gebaut, beliebig oft aufwärmbar, immer identisch. Images entstehen entweder fertig aus dem Internet (z. B. `caddy:2-alpine`, `postgres:16-alpine`, `onerahmet/openai-whisper-asr-webservice:latest`) oder werden lokal aus einem `Dockerfile` gebaut (z. B. `backend`, `odoo`, `piper`). Welcher Dienst welches Image nutzt, steht in `docker-compose.yml`.

## Intent-Engine

Die **Intent-Engine** ist die Komponente, die aus gesprochenem/getipptem Text die **Absicht** des Nutzers herausliest – also was er erreichen will, nicht bloß welche Wörter er sagte. „Passt", „jep", „ok" werden z. B. alle als Aktion `confirm` (Bestätigen) erkannt. Im Projekt ist sie **deterministisch** (regelbasiert, keine KI) in `backend/app/services/intent_engine.py` umgesetzt und arbeitet in Stufen: exakter Treffer → Regex → Fuzzy-Match (Levenshtein) → Segment-Fallback.

> [!info] Kennzahlen (belegt aus `intent_engine.py`)
> Schwellenwerte: `EXACT_MATCH_CONFIDENCE = 0.95`, `FUZZY_SINGLE_THRESHOLD = 0.73`, `FUZZY_PHRASE_THRESHOLD = 0.68`. Jede Aktion (`confirm`, `next`, `problem`, `stock_query`, `done`, `pause`, `photo`, `repeat`, `help`, …) hat hunderte umgangssprachliche Alias-Varianten. Die Spracherkennung ([STT](#stt-whisper)) liefert den Text; die Intent-Engine deutet ihn lokal – n8n ist hier **nicht** beteiligt.

## JSON-RPC

**JSON-RPC** ist ein einfaches Protokoll, um eine Methode (Funktion) auf einem entfernten Server aufzurufen, wobei Anfrage und Antwort als JSON-Nachrichten übertragen werden – man schickt „rufe Methode X mit diesen Argumenten auf" und bekommt das Ergebnis zurück. In diesem Projekt kommuniziert das Backend so mit Odoo: `backend/app/services/odoo_client.py` ruft `common.authenticate` (Login) und `object.execute_kw` (Datenzugriff: `search_read`, `create`, `write`, …) auf.

> [!note] Abgrenzung zu REST
> [REST](#rest) denkt in *Ressourcen* (URLs wie `/pickings/123`), JSON-RPC denkt in *Methodenaufrufen* (`execute_kw(model, method, args)`). Im Projekt findet man beides: REST zwischen PWA und Backend, JSON-RPC zwischen Backend und Odoo.

## Orchestrator

Ein **Orchestrator** ist der „Dirigent", der mehrere Schritte und Systeme zu einem Gesamtablauf zusammenführt – er macht die Arbeit nicht selbst, sondern koordiniert, wer wann was tut. In diesem Projekt ist **n8n** der Orchestrator: Es nimmt Events vom Backend entgegen (z. B. `quality-alert-created`, `shortage-reported`), verarbeitet sie (KI-Bewertung, Nachschublogik) und ruft per [Callback](#callback) zurück. n8n läuft als eigener Container (`docker.n8n.io/n8nio/n8n:2.13.3`).

> [!warning] Architektur-Invariante
> n8n liegt **nicht im Voice-Hot-Path**: Spracherkennung ([Whisper](#stt-whisper)) und Absichtserkennung ([Intent-Engine](#intent-engine)) laufen lokal im Backend. n8n wird beim Voice-Pfad nur **optional und synchron** über `voice-exception-query` befragt (Timeout, danach lokaler Fallback). Fällt n8n aus, antwortet das Backend selbst. Siehe [[07 - n8n]] und [[08 - PWA & Voice-Pfad]].

## picking-net

**`picking-net`** ist das interne Docker-Netzwerk (Bridge-Treiber), über das alle Container dieses Projekts miteinander reden – ein privates „LAN" nur für die Dienste. Innerhalb dieses Netzwerks sprechen sie sich über ihre Container-Namen an (z. B. `http://backend:8000`, `http://whisper:9000`, `http://n8n:5678`), nicht über `localhost`. Definiert ist es in `docker-compose.yml`.

> [!info] Warum Namen statt Ports?
> Weil im selben Netzwerk jeder Container den anderen unter seinem Service-Namen erreicht, müssen interne Ports nicht nach außen freigegeben werden. Nur [Caddy](#reverse-proxy-caddy) (443/80) ist von außen erreichbar – alle anderen Dienste bleiben hinter dem Reverse Proxy.

## PWA (Progressive Web App)

Eine **PWA** ist eine Web-Anwendung, die sich wie eine native Handy-App verhält: Sie kann installiert werden, offline-fähig sein (über einen Service Worker) und auf Gerätefunktionen wie das Mikrofon zugreifen. In diesem Projekt ist die PWA die Bedienoberfläche für den Picker auf dem mobilen Gerät; sie liegt im Ordner `pwa/` und wird statisch ausgeliefert (Service `pwa`, Image `caddy:2-alpine`, Konfiguration `infrastructure/caddy/Caddyfile.pwa` mit SPA-Fallback `try_files {path} /index.html`).

> [!info] Im Projekt
> Die PWA spricht ausschließlich mit dem [FastAPI](#fastapi)-Backend. Sie nimmt Audio auf, sendet es an `POST /api/voice/recognize`, zeigt Picking-Listen, bestätigt Zeilen und spielt Sprachantworten ab – mit Browser-TTS als Fallback, falls [Piper](#tts-piper) nicht antwortet. Header `Service-Worker-Allowed: /` erlaubt den Service Worker im gesamten Pfad.

## Reverse Proxy (Caddy)

Ein **Reverse Proxy** ist die zentrale Eingangstür eines Server-Systems: Er nimmt alle Anfragen von außen entgegen und leitet sie intern an den jeweils zuständigen Dienst weiter – der Nutzer sieht nur eine Adresse, dahinter verteilt der Proxy. In diesem Projekt übernimmt **Caddy** diese Rolle (Service `caddy`, Image `caddy:2-alpine`, Ports 443/80, Konfiguration `infrastructure/caddy/Caddyfile`). Er terminiert auch [HTTPS](#https--mkcert) mit den mkcert-Zertifikaten.

> [!info] Routing-Regeln (belegt aus `Caddyfile`)
> - `/api/*` → `reverse_proxy backend:8000` (FastAPI)
> - `/n8n/*` bzw. `/nn/*` → Präfix entfernen → `reverse_proxy n8n:5678`
> - `/odoo/*` → Redirect auf `http://{LAN_HOST}:8069/`
> - `/*` (alles übrige) → `reverse_proxy pwa:80` (die PWA)
>
> Auf Port 80 leitet Caddy HTTP-Anfragen nach HTTPS um.

## REST

**REST** (Representational State Transfer) ist ein verbreiteter Stil für Web-Schnittstellen: Man spricht „Ressourcen" über URLs an und nutzt die HTTP-Verben `GET` (lesen), `POST` (anlegen/auslösen), `PUT`/`PATCH` (ändern), `DELETE` (löschen). In diesem Projekt ist die Backend-API in diesem Stil aufgebaut, z. B. `GET /api/pickings` (offene Aufträge lesen) oder `POST /api/pickings/{picking_id}/confirm-line` (eine Pick-Zeile bestätigen).

> [!note] Annahme
> Die Bezeichnung „REST" beschreibt hier den erkennbaren Aufbau (Ressourcen-URLs + HTTP-Verben) der FastAPI-Endpunkte. Ob das Projekt formal alle REST-Reifegrade (z. B. HATEOAS) erfüllt, ist aus den Quellen **nicht** belegt und wird hier nicht behauptet.

## STT (Whisper)

**STT** (Speech-to-Text) wandelt gesprochene Sprache in geschriebenen Text um. Das Projekt nutzt dafür **Whisper** (von OpenAI), das **lokal** in einem eigenen Container läuft (Image `onerahmet/openai-whisper-asr-webservice:latest`, Modell `small`, Engine `faster_whisper`, Port 9000) – die Audiodaten verlassen das System also nicht. Angesprochen wird Whisper serverseitig über `backend/app/services/whisper_client.py` (`POST {whisper_url}/asr`, Sprache `de`, Timeout 60 s).

> [!info] Datenfluss
> PWA nimmt Audio auf → `POST /api/voice/recognize` → Backend ruft Whisper auf → Rückgabe als Text → weiter an die [Intent-Engine](#intent-engine). STT bleibt bewusst lokal und läuft nicht über [n8n](#orchestrator).

## System of Record

Ein **System of Record** ist die eine, verbindlich führende Datenquelle für eine Information – die „Single Source of Truth". Wenn mehrere Systeme dieselben Daten kennen, entscheidet das System of Record im Zweifel, was korrekt ist. In diesem Projekt ist das **Odoo**: Alle Quality-Alerts, Nachschubaufträge (Replenishments) und Picking-Bestätigungen landen letztlich in Odoo, nicht in n8n.

> [!warning] Architektur-Invariante
> „Odoo ist System of Record" ist eine Kern-Designregel des Projekts (aus der `CLAUDE.md` referenziert). [n8n](#orchestrator) orchestriert nur Abläufe und schreibt Ergebnisse per [Callback](#callback) **zurück nach Odoo** – es hält selbst keine maßgeblichen Geschäftsdaten.

## TTS (Piper)

**TTS** (Text-to-Speech) ist die Umkehrung von [STT](#stt-whisper): geschriebener Text wird in hörbare Sprache umgewandelt. Das Projekt nutzt **Piper** mit der deutschen Stimme „thorsten-high", lokal in einem eigenen Container (Build aus `piper/Dockerfile`, Port 5500). Das Backend ruft Piper über `backend/app/services/piper_client.py` auf (`POST {piper_url}/synthesize`, Timeout 5 s).

> [!info] Fallback-Verhalten
> Antwortet Piper nicht innerhalb von 5 s (oder schlägt fehl), gibt der Client `None` zurück und die [PWA](#pwa-progressive-web-app) spricht den Text über die im Browser eingebaute Sprachausgabe (Browser-TTS) aus. So bleibt die Sprachausgabe auch bei Ausfall des TTS-Dienstes funktionsfähig.

## Volume / Mount

Ein **Volume** bzw. **Mount** hängt einen Ordner oder Datenspeicher in einen Container ein, damit dieser darauf zugreifen kann oder Daten dauerhaft erhalten bleiben (Container selbst sind sonst „vergesslich"). Man unterscheidet **Bind-Mounts** (ein konkreter Host-Ordner wird eingehängt, z. B. `./backend/app:/app/app:ro`) und **Named Volumes** (von Docker verwalteter Speicher, z. B. `pg_data` für die Datenbank). Beides ist in `docker-compose.yml` konfiguriert.

> [!info] Beispiele im Projekt
> - **Bind-Mount + Hot-Reload:** `./backend/app:/app/app:ro` (Code-Änderungen sofort sichtbar), `./pwa:/srv:ro` (Frontend), `../Notzien:/obsidian:ro` (Obsidian-Vault für Kontextsuche).
> - **Named Volumes (Persistenz):** `pg_data` (Postgres), `odoo_data` (Odoo-Filestore), `n8n_data` (n8n-Workflows + Schlüssel – kritisch!), `caddy_data`/`caddy_config`.
> - `:ro` steht für **read-only** (nur lesen). Alle Volumes löschen: `docker compose down -v`.

## Webhook

Ein **Webhook** ist eine umgekehrte Schnittstelle: Statt dass man regelmäßig nachfragt „gibt's was Neues?", schickt das andere System von sich aus eine HTTP-Nachricht, sobald etwas passiert – eine „Push"-Benachrichtigung zwischen Programmen. In diesem Projekt feuert das Backend Webhooks an [n8n](#orchestrator), wenn Ereignisse eintreten, z. B. `pick-confirmed`, `quality-alert-created`, `shortage-reported` (gesendet über `backend/app/services/n8n_webhook.py`).

> [!info] Outbound-Webhooks (Backend → n8n)
> Es gibt zwei Modi: **Fire-and-Forget** (`fire_event`, asynchron, keine Antwort erwartet – z. B. `quality-alert-created`) und **synchrones Request/Reply** (`request_reply`, wartet auf Antwort, Standard-Timeout 7000 ms – z. B. `voice-exception-query`). Jeder Webhook-Pfad hat einen **Circuit Breaker**: Nach `n8n_circuit_breaker_failures` (Standard 3) Fehlern öffnet er für `n8n_circuit_breaker_open_seconds` (Standard 60 s) und liefert sofort eine Fallback-Antwort.

> [!warning] Bekanntes Webhook-Problem (belegt aus n8n-Analyse)
> In den Workflow-JSONs (`pick-confirmed.json`, `quality-alert-created.json`, `shortage-reported.json`, `voice-exception-query.json`) fehlt teilweise eine gespeicherte `webhookId` im Webhook-Node. Folge: Der Workflow erscheint zwar „active", der produktive Webhook-Pfad ist aber nicht registriert → eingehende POSTs scheitern mit **404 Not Found**. Behebung: Im n8n-UI Webhook-Node öffnen, einmal „Test"/Aktivierung auslösen, damit n8n die `webhookId` erzeugt und speichert.

---

## Begriffsbeziehungen auf einen Blick

> [!note] Wie die Begriffe zusammenspielen
> - **[Docker](#docker)** baut aus einem **Dockerfile** ein **[Image](#image)**, daraus startet ein **[Container](#container)**; alle Container hängen am Netzwerk **[picking-net](#picking-net)** und teilen Daten über **[Volumes/Mounts](#volume--mount)**.
> - **[Caddy](#reverse-proxy-caddy)** ist die HTTPS-Eingangstür (**[HTTPS/mkcert](#https--mkcert)**) und verteilt: `/api/*` → **[FastAPI](#fastapi)**, `/*` → **[PWA](#pwa-progressive-web-app)**, `/n8n/*` → **[Orchestrator](#orchestrator)**.
> - Die **[PWA](#pwa-progressive-web-app)** spricht per **[REST](#rest)** nur mit **[FastAPI](#fastapi)**; FastAPI spricht per **[JSON-RPC](#json-rpc)** mit **[Odoo](#erp--odoo)** (dem **[System of Record](#system-of-record)**).
> - Voice-Pfad: Audio → **[STT/Whisper](#stt-whisper)** → **[Intent-Engine](#intent-engine)** → Antwort als Text → **[TTS/Piper](#tts-piper)**.
> - **[Webhooks](#webhook)** schicken Events an **[n8n](#orchestrator)**; n8n meldet Ergebnisse per **[Callback](#callback)** zurück; **[Idempotenz](#idempotenz)** verhindert Doppelwirkungen; **[Hot-Reload](#hot-reload)** beschleunigt die Entwicklung.

---

## Quellen & Verweise

Diese Notiz fasst Begriffe zusammen, deren Belege in den projektinternen Analysen liegen:

- **Backend (FastAPI):** `backend/app/main.py`, `config.py`, `dependencies.py`, `services/odoo_client.py`, `services/n8n_webhook.py`, `services/whisper_client.py`, `services/piper_client.py`, `services/intent_engine.py`, `services/mobile_workflow.py`, `routers/n8n_internal.py`.
- **Infrastruktur:** `docker-compose.yml`, `infrastructure/caddy/Caddyfile`, `infrastructure/caddy/Caddyfile.pwa`, `infrastructure/scripts/setup-certs.sh`, `Makefile`.
- **n8n-Workflows:** `n8n/workflows/{pick-confirmed,quality-alert-created,shortage-reported,voice-exception-query,error-trigger}.json`.

Vertiefende Schwesternotizen: [[02 - Architektur & Diagramm erklärt]] · [[03 - Docker & Container]] · [[04 - Dev-Workflow Code ändern]] · [[05 - Backend (FastAPI)]] · [[06 - Odoo]] · [[07 - n8n]] · [[08 - PWA & Voice-Pfad]] · [[00 - Start Hier (Übersichtskarte)]]
