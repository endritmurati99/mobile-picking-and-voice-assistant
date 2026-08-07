# Ebene 1 Systemlandkarte Review Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ebene 1 gegen den aktuellen Repository-Stand präzisieren und mit einer nachvollziehbaren Scorecard bewerten.

**Architecture:** Die vorhandene Systemlandkarte bleibt die Übersichtsebene. SVG und Excalidraw werden synchron um belegte Randbedingungen ergänzt; Markdown erklärt dieselben Aussagen und dokumentiert die Bewertung.

**Tech Stack:** Markdown, SVG/XML, Excalidraw JSON, Docker Compose, Caddy, FastAPI

## Global Constraints

- Nur `docs/architecture/ebene-1-systemlandkarte.{md,svg,excalidraw}` ändern.
- Keine Netzwerkdetails aus Ebene 6 und keine Endpunktlisten aus Ebene 2 bis 5 duplizieren.
- Deklarierte Architektur und blockierter Live-Migrationsstand müssen getrennt bleiben.
- Keine bestehenden uncommitteten Codeänderungen aufnehmen.

---

### Task 1: SVG und Excalidraw synchron präzisieren

**Files:**
- Modify: `docs/architecture/ebene-1-systemlandkarte.svg`
- Modify: `docs/architecture/ebene-1-systemlandkarte.excalidraw`

**Interfaces:**
- Consumes: `docker-compose.yml`, `infrastructure/caddy/Caddyfile`, `backend/app/main.py`, `backend/app/services/outbox_dispatcher.py`
- Produces: Zwei editier- und exportierbare Diagrammfassungen mit denselben Ebene-1-Aussagen.

- [ ] **Step 1: Baseline-Prüfung ausführen**

Run:

```bash
rg -n 'einziger öffentlicher Eingang|Outbox-Zustellung|signierter Callback|Quality Alerts.*Outbox.*Cluster-Batches|Profil: zweite Odoo-Instanz' docs/architecture/ebene-1-systemlandkarte.{svg,excalidraw}
```

Expected: Kein vollständiger Treffer in beiden Dateien; die Ergänzungen fehlen noch.

- [ ] **Step 2: Die bestehenden Diagramme minimal ergänzen**

In beiden Fassungen dieselben Aussagen eintragen:

```text
Caddy
einziger öffentlicher Eingang
Web oder /api/*
blockiert interne Routen

Odoo 19
fachliche Wahrheit
Aufträge · Bestand · Benutzer
Quality Alerts · Outbox · Cluster-Batches

Outbox-Zustellung
signierter Callback

Profil: zweite Odoo-Instanz optional
```

Den bisherigen orangefarbenen bidirektionalen Quality-Pfeil durch zwei
gerichtete, orange gestrichelte Pfeile zwischen FastAPI und n8n ersetzen.
Der Hinweg trägt `Outbox-Zustellung`, der Rückweg `signierter Callback`.
Der Browser-Caddy-Pfeil wird mit `HTTPS · einziger öffentlicher Zugang`
beschriftet. Die bestehende direkte FastAPI-Ollama-Verbindung bleibt erhalten;
es wird keine n8n-Ollama- oder FastAPI-PostgreSQL-Kante ergänzt.

- [ ] **Step 3: Struktur und Aussagegleichheit prüfen**

Run:

```bash
jq empty docs/architecture/ebene-1-systemlandkarte.excalidraw
xmllint --noout docs/architecture/ebene-1-systemlandkarte.svg
for term in 'einziger öffentlicher' 'Outbox-Zustellung' 'signierter Callback' 'Quality Alerts' 'zweite Odoo-Instanz'; do
  rg -q "$term" docs/architecture/ebene-1-systemlandkarte.svg
  rg -q "$term" docs/architecture/ebene-1-systemlandkarte.excalidraw
done
```

Expected: Exit 0.

- [ ] **Step 4: SVG rendern und visuell prüfen**

Run:

```bash
google-chrome --headless --disable-gpu --no-sandbox --hide-scrollbars \
  --window-size=1800,1300 --screenshot=/tmp/ebene-1-reviewed.png \
  'file:///mnt/c/Users/endri/Desktop/Bachelor/Mobile%20Picking%20und%20Voice%20Assistant/docs/architecture/ebene-1-systemlandkarte.svg'
```

Expected: `/tmp/ebene-1-reviewed.png` wird erzeugt; Texte überlappen nicht und
beide Quality-Richtungen sind unterscheidbar.

- [ ] **Step 5: Diagrammänderung committen**

```bash
git add docs/architecture/ebene-1-systemlandkarte.svg \
  docs/architecture/ebene-1-systemlandkarte.excalidraw
git commit -m "docs: align level 1 system map"
```

### Task 2: Begleittext und Scorecard aktualisieren

**Files:**
- Modify: `docs/architecture/ebene-1-systemlandkarte.md`

**Interfaces:**
- Consumes: Die geprüften Aussagen aus Task 1 und die bestätigte Review-Spezifikation.
- Produces: Erklärtext und reproduzierbare Bewertung für Ebene 1.

- [ ] **Step 1: Fehlende Review-Sektion nachweisen**

Run:

```bash
rg -n '^## Review-Scorecard|Deklarierter Stand|Live-Migrationsstand' docs/architecture/ebene-1-systemlandkarte.md
```

Expected: Kein vollständiger Treffer.

- [ ] **Step 2: Erklärtext und Scorecard ergänzen**

Nach der Bildlegende erklären:

```markdown
Der Browser erreicht beide Ziele technisch über Caddy: Webseitenaufrufe gehen
zum PWA-Dateiserver, `/api/*` geht zu FastAPI. „Die PWA spricht mit FastAPI“
beschreibt die fachliche Beziehung, nicht eine Umgehung von Caddy.

Der orange Quality-Weg besteht aus zwei getrennten Aufrufen: FastAPI stellt ein
Outbox-Ereignis an n8n zu; n8n sendet den signierten Status an eine interne
FastAPI-Route zurück. n8n schreibt nicht direkt nach Odoo.
```

Vor „Drei Regeln zum Mitnehmen“ ergänzen:

```markdown
## Review-Scorecard

Stand: 7. August 2026. Bewertet wurde die Darstellung gegen Compose, Caddy,
FastAPI-Runtime und die beteiligten Clients.

| Kriterium | Punkte |
| --- | ---: |
| Komponentenabdeckung | 20/20 |
| Verbindungsgenauigkeit | 20/20 |
| Übereinstimmung mit Code und Compose | 19/20 |
| Verständlichkeit | 19/20 |
| Angemessene Detailtiefe | 19/20 |
| **Gesamt** | **97/100** |

Der deklarierte Aufbau verwendet Odoo 19. Der zuletzt geprüfte Live-Stand ist
noch kein grüner End-to-End-Nachweis: Server und Datenbankschema befinden sich
bis zum abgeschlossenen Modul-/Schema-Upgrade nicht auf demselben Stand.
```

Den erfundenen normalen Auftrag in Ebene 1 durch einen kurzen Verweis auf den
in Ebene 2 geprüften Auftrag `WH/INT/00360` „Ente Henri“ ersetzen. Ebene 1
nennt nur den Hauptweg; Positionen und Barcodes bleiben Ebene 2 vorbehalten.

- [ ] **Step 3: Dokumentkonsistenz prüfen**

Run:

```bash
rg -n 'WH/OUT/0042|zwei Kabel|eine Maus' docs/architecture/ebene-1-systemlandkarte.md && exit 1 || true
rg -n 'WH/INT/00360|Ente Henri|Review-Scorecard|97/100|Live-Stand' docs/architecture/ebene-1-systemlandkarte.md
git diff --check -- docs/architecture/ebene-1-systemlandkarte.md
```

Expected: Keine erfundenen Altbeispiele, alle fünf neuen Begriffe vorhanden,
`git diff --check` Exit 0.

- [ ] **Step 4: Gesamten Ebene-1-Scope verifizieren**

Run:

```bash
jq empty docs/architecture/ebene-1-systemlandkarte.excalidraw
xmllint --noout docs/architecture/ebene-1-systemlandkarte.svg
git diff --check -- docs/architecture/ebene-1-systemlandkarte.*
git status --short -- docs/architecture/ebene-1-systemlandkarte.*
```

Expected: JSON/XML gültig, kein Whitespacefehler und nur die drei freigegebenen
Ebene-1-Dateien im Scope.

- [ ] **Step 5: Begleittext committen**

```bash
git add docs/architecture/ebene-1-systemlandkarte.md
git commit -m "docs: score level 1 architecture map"
```

