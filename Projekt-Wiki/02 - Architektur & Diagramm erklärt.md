---
title: Architektur & Diagramm erklärt
tags:
  - architektur
  - diagramm
  - docker
  - caddy
  - reverse-proxy
  - container
  - infrastruktur
created: 2026-06-22
---

# Architektur & Diagramm erklärt

![[architektur.png]]

> [!info] Worum geht es hier?
> Diese Notiz erklärt das oben eingebettete Architektur-Diagramm **Baustein für Baustein**. Das Ziel: Du sollst nach dem Lesen genau verstehen, *welche* Bausteine es gibt, *wer mit wem* spricht und *in welche Richtung* die Pfeile zeigen. Pfeilrichtung bedeutet immer: **wer ruft wen auf** (wer ist der Aufrufer, wer der Angerufene).

---

## Die Kernidee in einem Satz

Alle Bausteine sind **eigenständige Docker-Container** im selben virtuellen Netzwerk `picking-net`. Ein einziger Eingang (der Reverse Proxy **Caddy**) nimmt allen Verkehr von außen entgegen und verteilt ihn intern an die richtigen Container weiter. Jeder Container macht **genau eine Aufgabe** (Single-Responsibility-Prinzip auf Infrastruktur-Ebene).

> [!note] Analogie für Nicht-Experten
> Stell dir ein Bürogebäude vor: **Caddy** ist der Empfang/Pförtner an der einzigen Eingangstür. Besucher (Anfragen) sagen am Empfang, wohin sie wollen, und der Pförtner schickt sie in das richtige Büro (Container). Die Büros (PWA, Backend, n8n, Odoo, Datenbank …) sind getrennte Räume, jeder mit einer klaren Funktion. Sie reden untereinander über interne Flure (das Docker-Netzwerk `picking-net`), nicht über die Straße.

---

## Die Leserfrage zuerst: "Ist das sinnvoll? Sind das wirklich alles einzelne Container?"

> [!info] Kurze Antwort: **Ja.**
> Es sind **10 einzelne Container** im Docker-Netz `picking-net`. Jeder hat **genau eine Aufgabe**. Das ist bewusst so gewählt und gilt als sinnvolle, gängige Praxis ("eine Verantwortlichkeit pro Container"). Vorteile:
> - **Isolierung:** Stürzt ein Container ab (z. B. `piper` TTS), laufen die anderen weiter.
> - **Austauschbarkeit:** Man kann einen Baustein einzeln neu bauen/aktualisieren, ohne den Rest anzufassen (z. B. nur `docker compose build backend`).
> - **Klarheit:** Pfeilrichtung im Diagramm = Aufrufrichtung. Man sieht sofort, wer von wem abhängt.
>
> **Quelle:** Die 10 Container und das Netzwerk `picking-net` (bridge-driver) sind in `docker-compose.yml` definiert (Projektpfad: `Mobile Picking und Voice Assistant/docker-compose.yml`).

Die 10 Container im Überblick (faktisch aus `docker-compose.yml`):

| # | Container | Aufgabe (genau eine) | Port (intern) | Build vs. Image |
|---|-----------|----------------------|---------------|-----------------|
| 1 | `caddy` | Reverse Proxy / Verteiler (HTTPS-Eingang) | 443, 80 | Image (`caddy:2-alpine`) |
| 2 | `db` | PostgreSQL 16 Datenbank | 5433 (nur lokal) | Image (`postgres:16-alpine`) |
| 3 | `odoo` | Warenwirtschaft / System of Record (Odoo 18) | 8069 | Build (`./odoo/Dockerfile`) |
| 4 | `backend` | FastAPI – Intent-Engine & API-Logik | 8000 | Build (`./backend/Dockerfile`) |
| 5 | `whisper` | Spracherkennung STT (Deutsch, Modell `small`) | 9000 | Image |
| 6 | `piper` | Sprachausgabe TTS (Deutsch „thorsten-high") | 5500 | Build (`./piper/Dockerfile`) |
| 7 | `n8n` | Workflow-Orchestrator | 5678 | Image (`n8n:2.13.3`) |
| 8 | `tunnel` | Cloudflare Named Tunnel (externe HTTPS-URL) | — | Image (`cloudflared`) |
| 9 | `mailpit` | SMTP-Mock / E-Mail-Test-Utility | 8025 (UI) | Image |
| 10 | `pwa` | Statischer Webserver für die PWA (Frontend) | 80 (intern) | Image (`caddy:2-alpine`) |

> [!note] Warum taucht Caddy "zweimal" auf?
> Es gibt zwei Caddy-Container mit unterschiedlichen Rollen: `caddy` (Nr. 1) ist der **Haupt-Verteiler** am Eingang (Port 443/80). `pwa` (Nr. 10) ist ein **zweiter, kleiner Caddy**, der nur die statischen Frontend-Dateien ausliefert. Der Haupt-Caddy leitet den Frontend-Verkehr intern an den PWA-Caddy weiter (`reverse_proxy pwa:80`). Das sind zwei getrennte Container mit je einer Aufgabe — kein Widerspruch zur Single-Responsibility-Regel.

---

## Baustein 1: Caddy – der Verteiler mit 4 Zweigen

**Caddy** ist der **Reverse Proxy**: der einzige Container, der von außen erreichbar ist (Ports **443** für HTTPS, **80** für HTTP-Redirect). Er entscheidet anhand des angefragten Pfads, an welchen internen Container die Anfrage geht.

> [!info] Was ist ein Reverse Proxy?
> Ein Reverse Proxy ist ein "Vorschalt-Server", der Anfragen von außen annimmt und im Hintergrund an den passenden internen Dienst weiterreicht. Der Browser sieht nur **eine** Adresse (z. B. `https://localhost`), obwohl dahinter mehrere getrennte Dienste arbeiten.

**Konfigurationsdateien (faktisch):**
- Haupt-Routing: `infrastructure/caddy/Caddyfile`
- PWA-eigenes Caddy: `infrastructure/caddy/Caddyfile.pwa`

### Die 4 Zweige (Routing-Regeln aus dem Caddyfile)

```text
Anfrage an  →  Caddy verteilt an
─────────────────────────────────────────────────────────
/           →  PWA-Container          (reverse_proxy pwa:80)
/api/*      →  Backend (FastAPI)      (reverse_proxy backend:8000)
/n8n, /n8n/* →  n8n-Container         (strip prefix /n8n, reverse_proxy n8n:5678)
/odoo, /odoo/* →  Redirect            (HTTP-Redirect zu http://{LAN_HOST}:8069/)
```

| Zweig | Pfad | Ziel-Container | Mechanismus |
|-------|------|----------------|-------------|
| 1 | `/` (Catch-all) | `pwa` | `reverse_proxy pwa:80` – Frontend (PWA) |
| 2 | `/api/*` | `backend` | `reverse_proxy backend:8000` – FastAPI |
| 3 | `/n8n`, `/n8n/*` | `n8n` | Präfix `/n8n` entfernen, dann `reverse_proxy n8n:5678` |
| 4 | `/odoo`, `/odoo/*` | (Redirect) | **Kein Proxy**, sondern HTTP-Redirect auf `http://{LAN_HOST}:8069/` |

> [!warning] Wichtiger Unterschied: /odoo ist KEIN echter Proxy-Zweig
> Bei `/`, `/api` und `/n8n` reicht Caddy die Anfrage **intern** durch (Reverse Proxy → der Browser bleibt auf derselben Adresse). Bei **`/odoo`** macht Caddy stattdessen einen **Redirect**: Der Browser wird auf den direkten Port `8069` umgeleitet (`http://{LAN_HOST}:8069/`). Odoo läuft also als Container, wird aber im Diagramm nicht "durchgeproxyt", sondern per Weiterleitung direkt angesteuert (Fallback auf den direkten Port).

**Zusätzliche Aliase / Host-Routing (faktisch im Caddyfile):**
- `/nn`, `/nn/*` → wie `/n8n` ein Alias auf `n8n:5678` (Präfix `/nn` wird entfernt).
- Host-basiert (`nn`, `n8n`, `n8n.localhost`, `nn.localhost`) → `reverse_proxy n8n:5678`.
- HTTP-Listener (`:80`) leitet generell auf HTTPS um (`https://{LAN_HOST}`).

**TLS / Zertifikate:** Caddy nutzt `/certs/cert.pem` + `/certs/key.pem` (per `mkcert` erzeugt, siehe `infrastructure/scripts/setup-certs.sh`). Für mobile Geräte muss die mkcert-Root-CA manuell installiert werden.

---

## Baustein 2: PWA – das Frontend

Der **`pwa`-Container** ist ein schlanker Caddy (`caddy:2-alpine`), der die statischen Frontend-Dateien aus `./pwa` ausliefert (`file_server`). Er nutzt SPA-Routing (`try_files {path} /index.html`) und setzt Header für den Service Worker (`Service-Worker-Allowed: /`, `Cache-Control: no-cache`).

- **Pfeil:** Caddy (Zweig 1, `/`) **→** PWA. Caddy ruft die PWA auf (`reverse_proxy pwa:80`).
- **Konfig:** `infrastructure/caddy/Caddyfile.pwa`
- **Wichtig:** Die PWA spricht **nur** mit dem Backend (über `/api/*`) — **niemals direkt** mit n8n oder Odoo. (Architektur-Invariante: "PWA spricht nur FastAPI".)

---

## Baustein 3: Backend (FastAPI) – das Gehirn

Der **`backend`-Container** ist die zentrale API (FastAPI). Caddy leitet alles unter `/api/*` hierher (`reverse_proxy backend:8000`). Das Backend ist der einzige Baustein, der mit fast allen anderen redet: Odoo, Whisper, Piper und n8n.

- **Pfeil:** Caddy (Zweig 2, `/api/*`) **→** Backend.
- **Build:** `./backend/Dockerfile`. **Hängt ab von:** `odoo`, `whisper`, `piper`.
- **Hot-Reload:** Läuft mit `uvicorn ... --reload`. Code-Änderungen unter `./backend/app` triggern automatisch einen Neustart — **kein** `docker compose restart` nötig.

> [!note] Mehr Details zum Backend
> Endpunkte, Services und Datenflüsse stehen in der Schwesternotiz [[05 - Backend (FastAPI)]].

---

## Baustein 4: Backend ↔ n8n – die bidirektionale Beziehung

Dies ist die wichtigste Beziehung im Diagramm und die einzige, die in **beide Richtungen** zeigt:

> [!info] Zwei Pfeile, zwei Richtungen
> 1. **Webhook raus (Backend → n8n):** Das Backend ruft n8n-Webhooks auf, um Ereignisse zu melden oder eine Antwort anzufordern. Service: `backend/app/services/n8n_webhook.py`, Klasse `N8NWebhookClient`. Basis-URL intern: `http://n8n:5678/webhook`.
> 2. **Callback rein (n8n → Backend):** n8n ruft danach das Backend zurück, um Ergebnisse zu speichern. Endpunkte: `POST /api/internal/n8n/...` in `backend/app/routers/n8n_internal.py`.

**Die Webhook-Pfade (Backend → n8n), faktisch:**

| Webhook (raus) | Typ | Zweck |
|----------------|-----|-------|
| `quality-alert-created` | async (fire-and-forget) | Qualitäts-Alert gemeldet → n8n bewertet (AI/Heuristik) |
| `voice-exception-query` | **sync** (request-reply, 7 s Timeout) | Sprach-Anfrage → n8n antwortet synchron mit `tts_text` |
| `shortage-reported` | async | Fehlmenge gemeldet → n8n erzeugt Nachschub |
| `pick-confirmed` | async | Pick-Zeile bestätigt (Quittierung) |

**Die Callback-Pfade (n8n → Backend), faktisch:**

| Callback (rein, `/api/internal/n8n/...`) | Zweck |
|------------------------------------------|-------|
| `POST /quality-assessment` | AI-Bewertung in Odoo speichern (`quality.alert.custom`) |
| `POST /quality-assessment-ai` | Shadow-Heuristik protokollieren (Forschung) |
| `POST /replenishment-action` | Nachschubauftrag in Odoo anlegen |
| `POST /quality-assessment-failed` | AI-Fehler → Status "failed" setzen |
| `POST /manual-review-activity` | Manuelle Prüfung anlegen (mail.activity + Chatter) |

> [!warning] Sicherheit der Rückrufe
> Alle Callbacks (n8n → Backend) sind durch den Header `X-N8N-Callback-Secret` geschützt (geprüft via `secrets.compare_digest()`, timing-sicher) und sind **idempotent**: Der Header `Idempotency-Key` muss gleich der `correlation_id` im Body sein. Mismatch ⇒ 409, fehlend ⇒ 400.

> [!note] n8n liegt NICHT im Voice-Hot-Path
> Die Spracherkennung (STT) läuft **lokal** im Backend über Whisper — **nicht** über n8n. n8n wird im Sprachpfad nur für die synchrone `voice-exception-query` angefragt, und selbst da gibt es einen lokalen Fallback (Stock-Query + Obsidian-Kontext), falls n8n ausfällt oder der Circuit Breaker offen ist. n8n ist **Orchestrator, nicht kritischer Pfad**. Details: [[07 - n8n]] und [[08 - PWA & Voice-Pfad]].

---

## Baustein 5: n8n → OpenAI (extern)

Vom **`n8n`-Container** geht ein Pfeil **nach außen** zu **OpenAI** (externe API). n8n ruft also einen externen Dienst auf, um z. B. Qualitäts-Fotos per Vision-Modell zu bewerten.

- **Pfeil:** n8n **→** OpenAI (extern, verlässt das Docker-Netz `picking-net`).
- **Richtung:** n8n ist der Aufrufer, OpenAI der externe Dienstleister.
- **Sicherheit (faktisch in `docker-compose.yml`):** n8n ist per `N8N_SSRF_ALLOWED_HOSTNAMES: backend` und `N8N_RESTRICT_FILE_ACCESS_TO` eingeschränkt — interne SSRF-Aufrufe sind auf den `backend`-Host begrenzt.

> [!info] Annahme zur Kanten-Beschriftung
> Das Diagramm zeigt einen Pfeil `n8n → OpenAI`. Welches konkrete OpenAI-Modell genutzt wird, ist im Workflow-JSON konfiguriert; die Callback-Verträge erlauben `ai_provider`-Werte wie `openai-vision` (Feld `ai_provider`/`ai_model` im Callback `quality-assessment`). Die genaue Modell-ID ist **konfigurationsabhängig** und hier als Annahme markiert.

---

## Baustein 6: PostgreSQL an Odoo UND n8n

Der **`db`-Container** (PostgreSQL 16) ist die gemeinsame Datenbank für **zwei** Dienste gleichzeitig:

> [!info] Eine Datenbank-Instanz, zwei Nutzer
> - **Odoo** nutzt die Haupt-Datenbank (Cluster-DB `postgres`, Verbindung über `HOST=db, PORT=5432`).
> - **n8n** nutzt im selben PostgreSQL-Cluster eine eigene Datenbank namens `n8n` (angelegt durch das Init-Skript `infrastructure/scripts/init-n8n-db.sql`).
>
> Es sind also **zwei Pfeile** im Diagramm: `Odoo → PostgreSQL` und `n8n → PostgreSQL`. Beide Dienste sprechen denselben Container `db` an, arbeiten aber auf getrennten logischen Datenbanken.

- **Pfeile:** Odoo **→** PostgreSQL und n8n **→** PostgreSQL (beide sind Aufrufer der DB).
- **Abhängigkeit (faktisch):** Sowohl `odoo` als auch `n8n` haben `depends_on: db (service_healthy)` — sie starten erst, wenn die DB ihren Healthcheck (`pg_isready`) bestanden hat.
- **Port:** `127.0.0.1:5433` — die DB ist nur lokal erreichbar, **nicht** im LAN exponiert.
- **Persistenz:** Named Volume `pg_data`.

> [!note] Warum teilen sich zwei Dienste eine DB-Instanz?
> Das spart Ressourcen (nur ein PostgreSQL-Prozess) und vereinfacht Backup/Betrieb. Durch getrennte logische Datenbanken (`postgres` für Odoo, `n8n` für n8n) bleiben die Daten sauber isoliert. Mehr zu Odoo: [[06 - Odoo]].

---

## Die restlichen Bausteine (im Diagramm am Rand)

Diese Container gehören zum Netz `picking-net`, sind aber Hilfsdienste:

| Container | Rolle | Wer ruft wen | Quelle |
|-----------|-------|--------------|--------|
| `whisper` | STT (Sprache → Text), Deutsch, Modell `small` | Backend **→** Whisper (`http://whisper:9000/asr`) | `backend/app/services/whisper_client.py` |
| `piper` | TTS (Text → Sprache), Deutsch | Backend **→** Piper (`http://piper:5500/synthesize`) | `backend/app/services/piper_client.py` |
| `tunnel` | Cloudflare Named Tunnel | exponiert `n8n` über permanente HTTPS-URL (für Telegram/externe Webhooks); `depends_on: n8n` | `docker-compose.yml` |
| `mailpit` | SMTP-Mock zum E-Mail-Testen | reine Test-Utility, keine Business-Logik (UI auf Port 8025) | `docker-compose.yml` |

> [!note] Whisper-Fallback und Piper-Fallback
> - **Whisper** liefert bei Fehler einen leeren String `""` zurück (Timeout 60 s).
> - **Piper** liefert bei Fehler `None` (Timeout 5 s) — die PWA fällt dann auf die Browser-eigene Sprachausgabe zurück.

---

## Pfeilrichtungen auf einen Blick (Lese-Regel)

> [!info] Merksatz: Pfeil = "wer ruft wen"
> Ein Pfeil von **A → B** bedeutet: **A ist der Aufrufer, B wird aufgerufen.** A hängt von B ab.

```text
                          (extern)
                          OpenAI
                            ▲
                            │ (n8n ruft OpenAI)
        ┌───────────────────────────────────────────┐
        │                  picking-net               │
        │                                            │
 außen ─┼─► Caddy ──/──────────────► PWA             │
 (443)  │      │                                     │
        │      ├──/api/*───────────► Backend ◄──────►│ n8n   (bidirektional:
        │      │                       │  ▲          │  │     Webhook raus / Callback rein)
        │      ├──/n8n/*────────────► n8n             │  │
        │      │                       │              │  │
        │      └──/odoo (Redirect)──► :8069 (Odoo)    │  │
        │                              │              │  │
        │        Backend ──► Whisper (STT)            │  │
        │        Backend ──► Piper  (TTS)             │  │
        │                              │              │  │
        │             Odoo ──► PostgreSQL ◄── n8n     │  │
        │                                             │  │
        │             n8n ──► tunnel (Cloudflare) ────┼──┘
        └─────────────────────────────────────────────┘
```

| Pfeil | Bedeutung |
|-------|-----------|
| außen → Caddy | Browser/Gerät spricht den einzigen Eingang an (HTTPS 443) |
| Caddy → PWA | `/` Catch-all liefert das Frontend |
| Caddy → Backend | `/api/*` geht an FastAPI |
| Caddy → n8n | `/n8n/*` (und Aliase) geht an n8n |
| Caddy → :8069 | `/odoo` ist ein **Redirect** auf den Odoo-Port (kein Proxy) |
| Backend ↔ n8n | **Bidirektional:** Webhook raus, Callback rein |
| Backend → Whisper / Piper | Backend ruft STT/TTS auf |
| n8n → OpenAI | n8n ruft die externe AI-API |
| Odoo → PostgreSQL | Odoo nutzt die DB (Cluster-DB) |
| n8n → PostgreSQL | n8n nutzt dieselbe DB-Instanz (eigene DB `n8n`) |
| n8n → tunnel | Cloudflare-Tunnel exponiert n8n nach außen |

---

## Faktencheck / Quellen (zitierfähig)

> [!info] Alle Aussagen sind belegt
> Die folgenden Dateien (relativ zum Projekt `Mobile Picking und Voice Assistant/`) sind die Belegquellen:

- **Container & Netzwerk `picking-net`:** `docker-compose.yml`
- **Caddy-Routing (4 Zweige + Aliase):** `infrastructure/caddy/Caddyfile`
- **PWA-Auslieferung (SPA-Fallback, SW-Header):** `infrastructure/caddy/Caddyfile.pwa`
- **Zertifikate (mkcert):** `infrastructure/scripts/setup-certs.sh`, Zertifikate in `infrastructure/certs/`
- **n8n-DB-Anlage (`n8n`-Datenbank im Postgres-Cluster):** `infrastructure/scripts/init-n8n-db.sql`
- **Webhook raus (Backend → n8n):** `backend/app/services/n8n_webhook.py` (`N8NWebhookClient`)
- **Callback rein (n8n → Backend):** `backend/app/routers/n8n_internal.py` (`/api/internal/n8n/...`)
- **Voice-Pfad / lokaler Fallback:** `backend/app/routers/voice.py`
- **Odoo-Modell der AI-Bewertung:** `quality.alert.custom` (Felder u. a. `ai_disposition`, `ai_confidence`, `ai_evaluation_status`)

> [!warning] Als Annahme markiert (nicht hart belegt)
> - Die konkrete **OpenAI-Modell-ID** (z. B. `gpt-4-vision`) ist konfigurationsabhängig im n8n-Workflow-JSON. Im Diagramm steht nur "OpenAI (extern)". Beleg ist lediglich das Callback-Feld `ai_provider`/`ai_model` mit möglichem Wert `openai-vision`.
> - Der **`pick-confirmed`**-Webhook ist im Code vorhanden, wird laut Infra-Analyse aber "möglicherweise nicht aktiv" gefeuert — die genaue Aktivierung hängt von der Workflow-Registrierung in n8n ab.

---

## Verwandte Notizen

- [[00 - Start Hier (Übersichtskarte)]] — Einstieg & Gesamtkarte
- [[01 - Was ist das Projekt & wie es anfing]] — Kontext & Motivation
- [[03 - Docker & Container]] — Container-Details, Volumes, Healthchecks, Reset
- [[04 - Dev-Workflow Code ändern]] — Hot-Reload vs. Rebuild, Makefile, Windows-Skripte
- [[05 - Backend (FastAPI)]] — Endpunkte, Services, Datenflüsse, Idempotenz
- [[06 - Odoo]] — System of Record, Modelle, Felder
- [[07 - n8n]] — Workflows, Webhook-/Callback-Verträge im Detail
- [[08 - PWA & Voice-Pfad]] — Frontend, STT/TTS, Sprach-Fallback
- [[10 - Glossar]] — Begriffe (Reverse Proxy, Container, Webhook, Idempotenz …)
