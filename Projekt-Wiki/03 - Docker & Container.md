---
title: Docker & Container
tags:
  - docker
  - infrastruktur
  - container
  - docker-compose
  - poc
created: 2026-06-22
---

# Docker & Container

> [!info] Zweck dieser Notiz
> Diese Notiz erklärt, **was Docker ist**, den Unterschied zwischen **Image und Container**, **warum** das Projekt Container nutzt, und gibt einen vollständigen Überblick über **alle 10 Container** des Stacks (Name, Aufgabe, Port, Image-oder-Build, ob nötig/optional fürs PoC). Außerdem: wie die Container über das Docker-Netzwerk `picking-net` verbunden sind, welche **persistenten Volumes** existieren und die **wichtigsten Befehle**.
> Quelle aller Fakten: `docker-compose.yml`, `infrastructure/caddy/Caddyfile`, `Makefile` (Infrastruktur-Analyse).

Siehe auch: [[00 - Start Hier (Übersichtskarte)]] · [[02 - Architektur & Diagramm erklärt]] · [[04 - Dev-Workflow Code ändern]] · [[10 - Glossar]]

---

## Was ist Docker? (einfache Erklärung)

**Docker** ist ein Werkzeug, das Software zusammen mit allem, was sie zum Laufen braucht (Programmiersprache, Bibliotheken, Konfiguration, Betriebssystem-Teile), in eine abgeschlossene "Kiste" packt — einen sogenannten **Container**. Dieser Container läuft auf jedem Rechner gleich, egal ob auf dem Laptop des Autors, auf einem Server oder auf einem anderen Betriebssystem.

> [!note] Analogie: Schiffscontainer
> Man kann sich Docker wie das **Container-System in der Logistik** vorstellen (passend zum Picking-Thema dieses Projekts): Egal ob Schuhe, Maschinen oder Lebensmittel im Container sind — der Container hat immer dieselbe genormte Form und passt auf jedes Schiff, jeden LKW und jeden Kran. Genauso ist es egal, ob im Docker-Container eine Datenbank, ein Webserver oder eine KI-Anwendung steckt: Der "Hafen" (= der Rechner mit Docker) behandelt alle Container gleich und kann sie starten, stoppen und verbinden.

**Docker Compose** ist die Erweiterung, mit der man **mehrere Container gemeinsam** beschreibt und auf einmal startet. Die zentrale Datei dafür ist `docker-compose.yml`. In diesem Projekt beschreibt sie **10 Services** (Container), die zusammen das gesamte System bilden.

- Datei: `docker-compose.yml` (im Projekt-Hauptverzeichnis `Mobile Picking und Voice Assistant/`)

---

## Image vs. Container — der Unterschied

> [!note] Kurzformel
> **Image = Bauplan/Schablone** (unveränderlich, wird gebaut oder heruntergeladen).
> **Container = laufende Instanz** dieses Bauplans (lebt, hat Zustand, kann gestartet/gestoppt werden).

| Begriff | Was es ist | Analogie |
|---|---|---|
| **Image** | Eine fertige, schreibgeschützte Vorlage mit Software + Abhängigkeiten. Wird entweder aus einer `Dockerfile` **gebaut** (`build`) oder fertig aus dem Internet **geladen** (`image:`). | Der **Bauplan** eines Hauses bzw. die Gussform. |
| **Container** | Eine **laufende** Kopie eines Images. Aus einem Image kann man viele Container starten. Container sind "vergänglich": Wird ein Container gelöscht, ist sein interner Zustand weg — außer er nutzt ein **Volume** (siehe unten). | Das **fertig gebaute, bewohnte Haus**. |

Im Projekt gibt es **beide Wege**:

- **Fertiges Image laden** (kein eigener Bauschritt), z. B. `image: caddy:2-alpine`, `image: postgres:16-alpine`, `image: docker.n8n.io/n8nio/n8n:2.13.3`.
- **Selbst bauen** aus einer `Dockerfile`, z. B. `build: ./odoo/Dockerfile`, `build: ./backend/Dockerfile`, `build: ./piper/Dockerfile`.

> [!info] Warum manche Services gebaut werden müssen
> Wenn eigener Code oder eigene Abhängigkeiten hinzukommen (Odoo-Addons, FastAPI-Quellcode, Piper-TTS), reicht ein fertiges Image nicht — es wird ein **eigenes Image gebaut**. Details dazu in [[04 - Dev-Workflow Code ändern]] (z. B. `docker compose build backend`).

---

## Warum Container? (Reproduzierbarkeit & "läuft überall gleich")

> [!note] Die drei Hauptgründe
> 1. **Reproduzierbarkeit:** Die gesamte Umgebung steht als Code in `docker-compose.yml`. Jeder, der diese Datei hat, bekommt mit einem Befehl exakt denselben Stack.
> 2. **"Läuft überall gleich":** Der Container enthält alle Abhängigkeiten. So fällt der klassische Satz "Bei mir lief es doch" weg — die Software verhält sich auf jedem Rechner identisch.
> 3. **Isolation & einfache Verbindung:** Jeder Dienst (Datenbank, Webserver, KI-Dienste) läuft sauber getrennt, ist aber über ein gemeinsames Netzwerk leicht miteinander verbunden.

Für eine **Bachelorarbeit / ein PoC** ist das besonders wertvoll: Der Aufbau ist **dokumentiert, versionierbar und jederzeit von Grund auf neu erstellbar** (`docker compose down -v` löscht alles, `docker compose up -d` baut es neu auf).

---

## Alle 8 Container im Überblick

> [!info] Lesehilfe zur Spalte "Nötig fürs PoC"
> - **Kern** = ohne diesen Container funktioniert der zentrale Picking-/Voice-Pfad nicht.

| # | Name | Aufgabe | Port | Image oder Build | Nötig fürs PoC | Abhängig von |
|---|---|---|---|---|---|---|
| 1 | **caddy** | HTTPS-Reverse-Proxy: verteilt eingehende Anfragen an die richtigen Services (siehe [[02 - Architektur & Diagramm erklärt]]) | 443 (HTTPS), 80 (HTTP) | Image `caddy:2-alpine` | **Kern** | — |
| 2 | **db** | PostgreSQL 16 — zentrale Datenbank für Odoo **und** n8n | `127.0.0.1:5433` (nur lokal) | Image `postgres:16-alpine` | **Kern** | — |
| 3 | **odoo** | Odoo 18 Community — "System of Record" (Lager-/Picking-Daten) | 8069 (intern, via Caddy) | **Build** `./odoo/Dockerfile` | **Kern** | db (healthy) |
| 4 | **backend** | FastAPI — Intent-Engine / API (`/api/*`) | 8000 (intern, via Caddy) | **Build** `./backend/Dockerfile` | **Kern** | odoo, whisper, piper |
| 5 | **whisper** | Speech-to-Text (STT), deutsches Modell `small` | 9000 (intern) | Image `onerahmet/openai-whisper-asr-webservice:latest` | **Kern** (Voice) | — |
| 6 | **piper** | Text-to-Speech (TTS), Deutsch „thorsten-high" | 5500 (intern) | **Build** `./piper/Dockerfile` | **Kern** (Voice) | — |
| 7 | **n8n** | Workflow-Orchestrierung (`/n8n/*`, Alias `/nn/*`) | 5678 (intern, via Caddy) | Image `docker.n8n.io/n8nio/n8n:2.13.3` | **Kern** (Orchestrierung) | db (healthy) |
| 8 | **pwa** | Statischer Webserver für die PWA-Oberfläche (Frontend) | 80 (intern) | Image `caddy:2-alpine` | **Kern** (Frontend) | — |

> [!warning] Port-Hinweise
> - **`db` (PostgreSQL)** ist mit `127.0.0.1:5433` **nur lokal** erreichbar, **nicht im LAN** — bewusste Sicherheitsentscheidung. Intern (zwischen Containern) läuft PostgreSQL auf dem Standardport **5432**.
> - Die "internen" Ports (8069, 8000, 9000, 5500, 5678, 80) sind im Normalfall **nur über Caddy** erreichbar, nicht direkt von außen.

### Kurzdetails je Container (faktisch, mit Pfaden)

> [!note] caddy
> Image `caddy:2-alpine`. Volumes: `./infrastructure/caddy/Caddyfile` → `/etc/caddy/Caddyfile` (ro), `./infrastructure/certs/` → `/certs` (ro), benannte Volumes `caddy_data`, `caddy_config`. Env: `LAN_HOST` (Default `localhost`). Routing siehe [[02 - Architektur & Diagramm erklärt]].

> [!note] db
> Image `postgres:16-alpine`. Env: `POSTGRES_USER=${POSTGRES_USER:-odoo}`, `POSTGRES_PASSWORD` (erforderlich), `POSTGRES_DB=postgres` (Cluster-DB). Volumes: benanntes Volume `pg_data` + Init-Skript `./infrastructure/scripts/init-n8n-db.sql` (legt die `n8n`-Datenbank an). Healthcheck: `pg_isready` (Intervall 10s, 5 Wiederholungen).

> [!note] odoo
> Build `./odoo/Dockerfile`. `depends_on: db (service_healthy)`. Env: DB-Verbindung (`HOST=db`, `PORT=5432`, `USER`, `PASSWORD`). Volumes: `./odoo/odoo.conf` → `/etc/odoo/odoo.conf` (ro), `./odoo/addons` → `/mnt/extra-addons` (ro, Custom-Addons), benanntes Volume `odoo_data`. Mehr in [[06 - Odoo]].

> [!note] backend (FastAPI)
> Build `./backend/Dockerfile`. `depends_on: odoo, whisper, piper`. Volumes: `./backend/app` → `/app/app` (ro, Python-Quellcode), `./docs` → `/obsidian` (ro, optionale Projektkontext-Dateien). Start-Command: `uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload`.
> **Wichtig:** `--reload` aktiviert Hot-Reload — Änderungen in `./backend/app` starten den Dienst automatisch neu, **kein** `docker compose restart` nötig. Details in [[04 - Dev-Workflow Code ändern]] und [[05 - Backend (FastAPI)]].

> [!note] whisper
> Image `onerahmet/openai-whisper-asr-webservice:latest`. Env: `ASR_MODEL=small`, `ASR_ENGINE=faster_whisper`. Port 9000 (intern). Kein eigener Build nötig (Upstream-Image).

> [!note] piper
> Build `./piper/Dockerfile`. Port 5500 (intern). Deutsche Stimme „thorsten-high". Bei Abhängigkeits-/Dockerfile-Änderung: `docker compose build piper && docker compose up -d`.

> [!note] n8n
> Image `docker.n8n.io/n8nio/n8n:2.13.3`. `depends_on: db (service_healthy)`. Ressourcen-Limits: 2 GB RAM, 1.5 CPUs, 256 PIDs. Nutzt die PostgreSQL-Datenbank `n8n` (im selben Cluster wie Odoo). Wichtige Env: `N8N_ENCRYPTION_KEY` (erforderlich), `N8N_CALLBACK_SECRET` (erforderlich), `N8N_SSRF_ALLOWED_HOSTNAMES=backend`, `N8N_RESTRICT_FILE_ACCESS_TO=/home/node/.n8n-files`, `N8N_CONCURRENCY_PRODUCTION_LIMIT=3`, Execution-Retention max. 168h (nur Fehler + manuelle/Progress-Läufe). Volumes: `n8n_data` (Workflows + Encryption-Keys), `./n8n/workflows` → `/imports` (ro), `./n8n/tmp` → `/home/node/.n8n-files`. Healthcheck: `wget -qO- http://localhost:5678/healthz`. Mehr in [[07 - n8n]].

> [!note] pwa
> Image `caddy:2-alpine` (zweite Caddy-Instanz, getrennt vom Reverse-Proxy). Volumes: `./pwa` → `/srv` (ro), `./infrastructure/caddy/Caddyfile.pwa` → `/etc/caddy/Caddyfile`. Konfiguration (`Caddyfile.pwa`): Port 80, `file_server`, `try_files {path} /index.html` (SPA-Fallback), Header `Service-Worker-Allowed: /` und `Cache-Control: no-cache`. Bei Änderung in `./pwa` reicht ein Browser-Refresh. Mehr in [[08 - PWA & Voice-Pfad]].

---

## Wie die Container verbunden sind

> [!info] Ein gemeinsames Netzwerk: `picking-net`
> Alle Services hängen am Docker-Netzwerk **`picking-net`** (Treiber: `bridge`). Innerhalb dieses Netzwerks finden sich die Container **über ihren Service-Namen** (DNS-Auflösung durch Docker), nicht über IP-Adressen.

Das bedeutet konkret:

- Der **backend**-Container erreicht Odoo unter dem Hostnamen `odoo`, die KI-Dienste unter `whisper` bzw. `piper`.
- **Caddy** leitet Anfragen intern an `backend:8000`, `n8n:5678` und `pwa:80` weiter — jeweils über den Service-Namen + internen Port.
- **odoo** und **n8n** sprechen die Datenbank über den Hostnamen `db` (Port `5432`) an.

> [!note] Warum Service-Namen statt IPs?
> IP-Adressen von Containern können sich bei jedem Neustart ändern. Service-Namen bleiben stabil. Docker betreibt im Netzwerk `picking-net` einen internen DNS, der z. B. `db` automatisch auf die aktuelle Container-IP auflöst. So bleiben Konfigurationen wie `HOST=db` dauerhaft gültig.

Beispielhafte Verbindungen (alle innerhalb `picking-net`):

```text
caddy   ──/api/*──▶ backend:8000
caddy   ──/n8n/*──▶ n8n:5678
caddy   ──/*──────▶ pwa:80
backend ─────────▶ odoo (Odoo-API)
backend ─────────▶ whisper:9000 (STT)
backend ─────────▶ piper:5500   (TTS)
odoo    ─────────▶ db:5432  (PostgreSQL, DB "postgres"/Odoo-DB)
n8n     ─────────▶ db:5432  (PostgreSQL, DB "n8n")
```

> [!info] Caddy-Routing-Details
> Die genauen Routing-Regeln (`/api/*`, `/n8n/*`, `/nn/*`, Host-basierte Regeln, Catch-all → PWA, TLS-Zertifikate) sind in der `infrastructure/caddy/Caddyfile` definiert und werden in [[02 - Architektur & Diagramm erklärt]] ausführlich erklärt.

---

## Persistente Volumes (Daten überleben Neustarts)

> [!warning] Wichtig zu verstehen
> Container sind "vergänglich": Löscht man einen Container, sind seine internen Daten weg. Damit z. B. die Datenbank oder n8n-Workflows **erhalten bleiben**, werden sie in **benannten Volumes** (named volumes) außerhalb des Containers gespeichert.

| Volume | Inhalt | Genutzt von | Kritikalität |
|---|---|---|---|
| **pg_data** | Komplette PostgreSQL-Datenbank (Odoo- und n8n-Daten) | db | Sehr hoch — Verlust = alle Daten weg |
| **odoo_data** | Odoo-Session/Filestore | odoo | Hoch |
| **n8n_data** | n8n-Workflows **und Encryption-Keys** | n8n | **Kritisch** — ohne Encryption-Key sind verschlüsselte Credentials unbrauchbar |
| **caddy_data** / **caddy_config** | Caddy-Laufzeitdaten/-konfiguration | caddy | Niedrig (regenerierbar) |

> [!warning] Reset löscht ALLES
> Der Befehl `docker compose down -v` entfernt die Container **und alle Volumes** (`-v` = volumes). Damit sind Datenbank, Odoo-Filestore und n8n-Workflows/Keys **unwiderruflich gelöscht**. Nur verwenden, wenn ein kompletter Neuanfang gewollt ist.

---

## Wichtige Befehle

> [!info] Tägliche Befehle (Docker Compose)
> Diese Befehle im Projekt-Hauptverzeichnis (`Mobile Picking und Voice Assistant/`) ausführen.

```bash
# Gesamten Stack im Hintergrund starten (alle 10 Container)
docker compose up -d

# Status / laufende Container anzeigen
docker compose ps

# Logs ansehen (alle Services, fortlaufend)
docker compose logs -f

# Logs eines einzelnen Services (z. B. Backend)
docker compose logs -f backend

# Stack stoppen (Container entfernen, Volumes BLEIBEN erhalten)
docker compose down

# Stack zurücksetzen (Container UND Volumes löschen) – Achtung: Datenverlust!
docker compose down -v
```

Einen einzelnen Service neu bauen (nach Code-/Abhängigkeitsänderung) und neu starten:

```bash
docker compose build backend
docker compose up -d backend
```

> [!note] Bequemer über das Makefile
> Im Projekt gibt es ein `Makefile` mit Kurzbefehlen, die dieselben `docker compose`-Kommandos kapseln:
> - `make up` → `docker compose up -d`
> - `make down` → `docker compose down`
> - `make logs` → alle Logs
> - `make logs-backend` → nur Backend-Logs
> - `make build-all` / `make build-backend` / `make build-odoo` → Images bauen
>
> **Auf Windows ohne `make`** geht es über PowerShell:
> ```powershell
> powershell -ExecutionPolicy Bypass -File infrastructure/scripts/workflow.ps1 logs-backend
> ```
> Wann man bauen (rebuild) muss und wann Hot-Reload reicht, steht in [[04 - Dev-Workflow Code ändern]].

---

## Zusammenfassung in einem Satz

> [!info] Merksatz
> Eine einzige Datei (`docker-compose.yml`) beschreibt **10 Container**, die über das Netzwerk **`picking-net`** per Service-Name miteinander reden; **Caddy** ist die HTTPS-Eingangstür, **persistente Volumes** (`pg_data`, `odoo_data`, `n8n_data`, `caddy_data`/`caddy_config`) bewahren die Daten, und mit `docker compose up -d` steht der ganze Stack reproduzierbar bereit.

**Weiterführend:** [[02 - Architektur & Diagramm erklärt]] · [[04 - Dev-Workflow Code ändern]] · [[05 - Backend (FastAPI)]] · [[06 - Odoo]] · [[07 - n8n]] · [[08 - PWA & Voice-Pfad]] · [[10 - Glossar]]
