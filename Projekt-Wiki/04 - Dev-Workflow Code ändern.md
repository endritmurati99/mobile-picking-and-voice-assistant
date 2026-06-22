---
title: Dev-Workflow Code ändern
tags:
  - dev-workflow
  - docker
  - hot-reload
  - rebuild
  - backend
  - pwa
  - makefile
created: 2026-06-22
---

# Dev-Workflow Code ändern

> [!info] Die zentrale Frage
> **"Wenn ich Code schreibe – was passiert? Muss ich den Container neu starten?"**
>
> Kurzantwort: **Meistens nicht.** Backend-Python-Code und PWA-Frontend-Code sind als Volumes in die Container gemountet und laden automatisch nach. Ein Neustart (`restart`), Neubau (`build`) oder Neuerstellen (`recreate`) des Containers ist nur in klar abgegrenzten Fällen nötig – diese Notiz erklärt genau welche.

Diese Notiz ist die praktische Anleitung für den Tag-zu-Tag-Workflow. Wer den Aufbau der Container und das Routing dahinter verstehen will, liest [[03 - Docker & Container]]. Wer wissen will, was im Backend technisch passiert, liest [[05 - Backend (FastAPI)]]. Die Gesamtkarte ist [[00 - Start Hier (Übersichtskarte)]].

---

## Das Grundprinzip: Volume-Mount + Reload

Ein Docker-Container ist normalerweise ein "eingefrorenes" Abbild (Image): Der Code, der beim Bauen (`docker compose build`) hineinkopiert wurde, ist fest eingebacken. Würde man nur damit arbeiten, müsste man bei **jeder** Code-Änderung neu bauen – das dauert lange und nervt im Entwicklungsalltag.

Die Lösung in diesem Projekt: **Volume-Mounts** (Analogie: ein "Fenster" vom Container in einen echten Ordner auf der Festplatte). Der Container schaut nicht auf eingebackenen Code, sondern direkt auf den lebenden Projektordner. Ändert man dort eine Datei, sieht der Container sie sofort.

Damit der laufende Prozess die geänderte Datei auch **benutzt**, braucht es zusätzlich einen **Reload-Mechanismus**:

- **Backend (FastAPI):** Der Server läuft mit `uvicorn ... --reload`. Uvicorn überwacht die Quelldateien und startet den Python-Prozess bei einer Änderung automatisch neu (~1–2 Sekunden). → **Hot-Reload.**
- **PWA (Frontend):** Die Dateien werden nur statisch ausgeliefert (kein Server-Prozess, der Code "ausführt"). Der "Reload" passiert im Browser durch ein einfaches Neuladen der Seite (F5).

> [!note] Begriffsklärung: build vs. recreate vs. restart
> - **build** = Das Image neu bauen (Code wird neu eingebacken, `pip install` läuft etc.). Nötig bei Dockerfile/Abhängigkeiten.
> - **recreate** = Den Container aus dem (ggf. unveränderten) Image neu erzeugen, weil sich Konfiguration/Umgebung geändert hat. Macht `docker compose up -d` automatisch, wenn es eine Änderung erkennt.
> - **restart** = Denselben Container nur stoppen und wieder starten. Im Hot-Reload-Workflow **fast nie nötig**.

---

## Backend (FastAPI) – HOT-RELOAD, KEIN Neustart

**Quelle:** `docker-compose.yml`, Service `backend`.

Der Backend-Service ist so konfiguriert:

- **Build:** `./backend/Dockerfile`
- **Volume-Mount:** `./backend/app` → `/app/app` (read-only) — der **Python-Quellcode** lebt hier.
- **Zusätzlicher Mount:** `../Notzien` → `/obsidian` (read-only) — externes Obsidian-Vault für Kontext-Suche.
- **Command:** `uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload`

Das entscheidende Flag ist `--reload`.

> [!important] Backend-Python-Code ändern = NUR speichern
> Eine Änderung in `./backend/app/**` (z. B. an `app/routers/pickings.py`, `app/services/intent_engine.py`, `app/services/picking_service.py`) triggert **automatisch** einen Uvicorn-Neustart. **Kein `docker compose restart`, kein `build`, kein `up` nötig.**
>
> Ablauf: Datei speichern → Uvicorn erkennt Änderung → Auto-Restart (~1–2 s) → Browser-Anfrage gegen `/api/...` trifft schon den neuen Code.

Der Code wird unter dem Prefix `/api` ausgeliefert (siehe `app/main.py`, alle Router mit `prefix="/api"`). Im Container hängt er an Port `8000`; nach außen erreichbar wird er über Caddy als `/api/*` → `reverse_proxy backend:8000`.

**Warum funktioniert das?** Weil der echte Ordner `./backend/app` ins Container-Verzeichnis `/app/app` gespiegelt ist und Uvicorn genau dieses Verzeichnis überwacht. Der Code im Container ist also nie "alt".

> [!warning] Ausnahme: requirements.txt
> Der Volume-Mount deckt nur `./backend/app` ab – **nicht** `backend/requirements.txt`. Die Abhängigkeiten werden im `Dockerfile` per `COPY` eingebacken und mit `pip install` installiert. Ein Volume-Mount kann das **nicht** überschreiben. Neue/aktualisierte Python-Pakete erfordern daher einen **Rebuild** (siehe unten).

---

## PWA (Frontend) – Browser-Reload reicht

**Quelle:** `docker-compose.yml`, Service `pwa` + `infrastructure/caddy/Caddyfile.pwa`.

Die PWA wird **nicht kompiliert oder gebaut** – sie wird als statische Dateien ausgeliefert:

- **Image:** `caddy:2-alpine` (kein eigener Build).
- **Volume-Mount:** `./pwa` → `/srv` (read-only) — der Frontend-Quellcode.
- **Caddyfile.pwa:** Port 80, `file_server`, `try_files {path} /index.html` (SPA-Fallback, damit jede URL auf die App zeigt).
- **Header:** `Service-Worker-Allowed: /`, `Cache-Control: no-cache`.

> [!important] PWA-Code ändern = speichern + Browser F5
> Eine Änderung in `./pwa/**` ist sofort live, weil die Datei direkt vom Ordner ausgeliefert wird (statisches File-Serving, kein Build-Schritt). **Kein `docker compose`-Kommando nötig** – einfach im Browser neu laden.
>
> Hinweis: `Cache-Control: no-cache` sorgt dafür, dass der Browser nicht eine alte Version aus dem Cache zeigt. Bei hartnäckigem Caching (besonders Service Worker) ggf. Hard-Reload (Strg+Shift+R) oder das DevTools-Feature "Update on reload".

Caddy leitet im Hauptrouting alle nicht anders zugeordneten Anfragen (`/*`, Catch-all) an die PWA weiter: `reverse_proxy pwa:80`.

---

## Wann ist ein REBUILD nötig?

Ein **Rebuild** (`docker compose build <service> && docker compose up -d <service>`) ist immer dann nötig, wenn sich etwas ändert, das **ins Image eingebacken** wird – also nicht über einen Volume-Mount lebt:

- **Dockerfile** eines Services (Build-Anweisungen selbst geändert)
- **requirements.txt** (Python-Abhängigkeiten – Backend, Odoo, Piper)
- **Odoo-Addon-Code** (`odoo/addons/**` ist read-only gemountet, aber Odoo lädt Addons beim Start; Änderungen erfordern Rebuild + Up – ggf. zusätzlich Modul-Update in Odoo)

**Quelle (docker-compose.yml):** Services mit `build:`-Direktive sind `odoo` (`./odoo/Dockerfile`), `backend` (`./backend/Dockerfile`) und `piper` (`./piper/Dockerfile`). Services mit fertigem `image:` (caddy, db, whisper, n8n, pwa) werden in der Regel nicht selbst gebaut.

```bash
# Beispiel Backend nach requirements.txt-Änderung
docker compose build backend
docker compose up -d backend

# Beispiel Odoo nach Addon-/requirements.txt-Änderung
docker compose build odoo
docker compose up -d odoo

# Beispiel Piper nach Dockerfile-/requirements.txt-Änderung
docker compose build piper
docker compose up -d piper
```

> [!note] Annahme: Odoo-Addon-Workflow
> Die Quellen belegen, dass `odoo/addons` als `/mnt/extra-addons` (read-only) gemountet ist und dass Dockerfile-/`odoo/requirements.txt`-Änderungen einen Rebuild erfordern. Ob für reine Python-Logik in einem bereits installierten Addon ein Modul-Upgrade in Odoo (statt nur Rebuild) nötig ist, hängt vom konkreten Addon-Inhalt ab – das ist hier als **Annahme** markiert und sollte beim ersten echten Addon-Change verifiziert werden.

---

## Wann ist ein RECREATE nötig?

Ein **Recreate** ist nötig, wenn sich die **Konfiguration** oder **Umgebung** eines Containers ändert – also nicht der Code, sondern *wie* der Container betrieben wird. Hier muss das Image **nicht** neu gebaut werden; es reicht, den Container neu aus dem bestehenden Image zu erzeugen.

Das passiert automatisch mit `docker compose up -d`: Compose vergleicht die Soll-Konfiguration mit den laufenden Containern und erstellt nur die betroffenen neu.

Typische Auslöser:

- **`.env`-Änderung** (z. B. `POSTGRES_PASSWORD`, `N8N_ENCRYPTION_KEY`, `LAN_HOST`, CORS-Origins) → Umgebungsvariablen werden beim Erzeugen gesetzt, daher Recreate.
- **`docker-compose.yml`-Änderung** (Ports, Volumes, Abhängigkeits-Graph, Ressourcenlimits) → Compose evaluiert den Stack neu.
- **`Caddyfile`-Änderung** (Routing) → Caddy-Container neu hochfahren, damit die neue Konfiguration greift.

```bash
# Gesamten Stack auf Soll-Zustand bringen (recreate nur, wo nötig)
docker compose up -d

# Gezielt nur Caddy nach Caddyfile-Änderung
docker compose up -d caddy
```

> [!warning] n8n-Workflows sind ein Sonderfall
> n8n-Workflows in `./n8n/workflows` werden als `/imports` (read-only) gemountet und beim Container-Start importiert/initialisiert. Eine Änderung an einer Workflow-Datei wird **nicht** hot-reloaded – der n8n-Container muss neu hochgefahren werden, damit der Import greift. Details siehe [[07 - n8n]].
>
> Achtung beim Reset: `docker compose down -v` löscht **alle** Named Volumes, inklusive `n8n_data` (enthält Workflows **und** Encryption-Keys). Das ist destruktiv.

---

## Tabelle: Was geändert → was tun

| Was geändert (Pfad) | Mechanismus | Was tun | docker-Kommando |
|---|---|---|---|
| **Backend-Python** `./backend/app/**` | Volume-Mount + `uvicorn --reload` | Datei speichern, fertig | **keins** (Auto-Reload ~1–2 s) |
| **PWA-Frontend** `./pwa/**` | Volume-Mount + statisches File-Serving | Speichern + Browser F5 | **keins** |
| **Backend-Abhängigkeiten** `backend/requirements.txt` | Im Image eingebacken (`COPY` + `pip install`) | Rebuild + Up | `docker compose build backend && docker compose up -d backend` |
| **Backend-Dockerfile** `./backend/Dockerfile` | Build-Definition | Rebuild + Up | `docker compose build backend && docker compose up -d backend` |
| **Odoo-Addon / requirements** `odoo/addons/**`, `odoo/requirements.txt` | Im Image eingebacken / Addon-Load beim Start | Rebuild + Up | `docker compose build odoo && docker compose up -d odoo` |
| **Piper** `piper/Dockerfile`, `piper/requirements.txt` | Im Image eingebacken | Rebuild + Up | `docker compose build piper && docker compose up -d piper` |
| **Caddyfile (Routing)** `infrastructure/caddy/Caddyfile` | Container-Konfiguration | Recreate Caddy | `docker compose up -d caddy` |
| **`.env`** (Secrets, Env-Vars) | Umgebung beim Container-Start | Recreate | `docker compose up -d` |
| **`docker-compose.yml`** (Ports, Volumes, Deps) | Stack-Definition | Recreate betroffene Services | `docker compose up -d` |
| **n8n-Workflows** `./n8n/workflows/**` (`/imports`) | Import beim Container-Start (kein Reload) | Container neu hochfahren | `docker compose up -d n8n` *(Annahme: Re-Import via Neustart)* |
| **Volle Zurücksetzung** (Daten weg!) | Löscht Named Volumes | Nur bewusst | `docker compose down -v` |

> [!tip] Faustregel
> - Ändere ich **Logik** (Python-Code im Backend, JS/HTML/CSS in der PWA)? → **Nichts tun** außer speichern/F5.
> - Ändere ich **Abhängigkeiten oder Dockerfile**? → **build**.
> - Ändere ich **Konfiguration** (`.env`, `docker-compose.yml`, `Caddyfile`)? → **up -d** (recreate).

---

## Befehle: Makefile und workflow.ps1

**Quelle:** `Makefile` sowie `infrastructure/scripts/workflow.ps1` (Windows-Pendant ohne `make`).

### Häufige Befehle (Makefile)

```bash
make up                    # docker compose up -d  (Stack starten / auf Soll-Zustand bringen)
make down                  # docker compose down   (Stack stoppen)
make logs                  # alle Logs
make logs-backend          # nur Backend-Logs
make build-all             # docker compose build  (alle baubaren Services)
make build-backend         # docker compose build backend
make build-odoo            # docker compose build odoo
```

### Lokal (ohne Docker, für isolierte Tests)

```bash
make install-backend-deps  # pip install -> backend/.deps (lokaler Python-Test)
make install-ui-deps       # npm install + playwright install chromium
```

### Windows (kein make verfügbar)

```powershell
# Gleiche Logik wie make, über das PowerShell-Skript
powershell -ExecutionPolicy Bypass -File infrastructure/scripts/workflow.ps1 verify
powershell -ExecutionPolicy Bypass -File infrastructure/scripts/workflow.ps1 logs-backend
```

> [!note] Annahme: Befehlsnamen in workflow.ps1
> Belegt sind die Aufrufe `verify` und `logs-backend` über `workflow.ps1`. Es ist plausibel, dass das Skript dieselben Target-Namen wie das Makefile spiegelt (`up`, `down`, `build-backend`, …). Die exakte Liste der unterstützten `workflow.ps1`-Targets ist als **Annahme** zu behandeln, bis im Skript selbst verifiziert.

---

## Verify-Targets (Tests vor dem Commit)

**Quelle:** `Makefile`, Abschnitt Testing/Verify.

Diese Targets prüfen, dass eine Code-Änderung nichts kaputt gemacht hat. Sie sind der "Sicherheitsgurt" des Dev-Workflows.

| Target | Was es prüft |
|---|---|
| `make test` | Backend-Tests (pytest) |
| `make test-ui` | Playwright-Browser-Tests gegen die PWA |
| `make test-visual` | Erzeugt Mobile-Artefakt (Screenshot/Render) |
| `make test-visual-diff` | Snapshot-Tests gegen Baselines (visuelle Regression) |
| `make test-a11y` | Accessibility-Prüfung (Axe + Playwright) |
| `make verify-workflows` | n8n-Webhooks ↔ Backend-Verträge (Envelope-/Callback-Konsistenz) |
| `make verify-stack` | API-Rauchtest gegen den **laufenden** Stack |
| `make verify` | Volllauf: code + ui + visual + a11y + workflows + stack |

> [!tip] Empfohlener Mini-Workflow
> 1. Code in `./backend/app` oder `./pwa` ändern → speichern (Hot-Reload greift).
> 2. Im Browser gegen den laufenden Stack manuell prüfen.
> 3. Vor dem Commit `make verify` (bzw. `workflow.ps1 verify` auf Windows) laufen lassen.
> 4. `verify-stack` setzt voraus, dass der Stack läuft (`make up`), weil es echte HTTP-Anfragen sendet.

---

## Zusammenfassung in einem Satz

> [!info] Essenz
> **Python-Code (Backend) und Frontend-Code (PWA) sind live-gemountet – speichern reicht (Backend: Uvicorn lädt neu; PWA: Browser F5).** Nur Änderungen an **Abhängigkeiten/Dockerfile** brauchen `build`, und Änderungen an **`.env`/`docker-compose.yml`/`Caddyfile`** brauchen `up -d` (recreate). n8n-Workflows werden beim Container-Start importiert und brauchen ein Neuhochfahren.

---

## Verwandte Notizen

- [[00 - Start Hier (Übersichtskarte)]] – Einstieg und Navigation
- [[02 - Architektur & Diagramm erklärt]] – wie die Teile zusammenspielen
- [[03 - Docker & Container]] – Services, Volumes, Routing im Detail
- [[05 - Backend (FastAPI)]] – Router, Services, Endpunkte
- [[06 - Odoo]] – Addons, Modelle, System of Record
- [[07 - n8n]] – Workflows und Import-Mechanik
- [[08 - PWA & Voice-Pfad]] – Frontend und Sprachsteuerung
- [[10 - Glossar]] – Begriffe (build/recreate/restart, Volume-Mount, Hot-Reload)
