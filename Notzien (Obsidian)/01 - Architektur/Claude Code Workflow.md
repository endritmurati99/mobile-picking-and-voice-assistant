---
title: Claude Code Workflow
tags:
  - architecture
  - workflow
  - claude-code
---

# Claude Code Workflow

## Ziel

Das Repository wurde auf einen schlankeren Claude-Code-Workflow umgestellt, damit Code-Arbeit, Kontext-Hygiene und Obsidian-Dokumentation sauber zusammenspielen.

## Umgesetzte Struktur

- Projektweite Claude-Code-Konfiguration liegt in `.claude/settings.json`
- Der Repo-Root hat eine schlanke `CLAUDE.md` als Dispatcher in das eigentliche Teilprojekt
- Die operative Projektanweisung liegt nur noch in `Mobile Picking und Voice Assistant/CLAUDE.md`
- Spezialisierte Subagents liegen in `.claude/agents/`
- Datei-Aenderungen werden ueber einen Hook nach Obsidian protokolliert

## DX-Fazit zu Leerzeichen in Pfaden

Die Leerzeichen in `Mobile Picking und Voice Assistant/` und `Notzien (Obsidian)/` sind vor allem ein Command-Line-Thema, kein Laufzeitfehler.

Bewusste Entscheidung:
- keine sofortige Umbenennung der Wurzelordner, weil das in einem bereits aktiven und lokal veraenderten Repo einen grossen Blast Radius ueber Hooks, MCP, Obsidian-Links und offene Arbeitsstaende haette
- stattdessen kurze, leerzeichenfreie Einstiegspunkte im Repo-Root: `workflow.ps1` und `workflow.cmd`

Praxisnutzen:
- `workflow verify`
- `workflow verify-ui`
- `workflow logs-backend`
- `workflow paths`

Damit verschwindet die Tipp-Reibung im Alltag, ohne dass die bestehende Struktur heute aufwendig umgezogen werden muss.

## Wichtige Entscheidungen

### 1. Keine tote `.claudecodeignore`

Statt einer rein textuellen Ignore-Datei nutzt die aktuelle Claude-Code-Version projektweite Regeln in `.claude/settings.json`.

Aktive Schutzregeln:
- blockieren `.obsidian/`
- blockieren Python-Caches und `node_modules/`
- blockieren Bilddateien und ZIP-Artefakte
- blockieren `.env` und TLS-Zertifikate

### 2. Root-Dispatcher plus kleine Projekt-`CLAUDE.md`

Die fruehere Root-`CLAUDE.md` war als Wissensspeicher zu gross und hat zu viel irrelevanten Kontext in Sessions gezogen. Die neue Struktur ist zweistufig:

- Root-`CLAUDE.md` als Einstieg und Routing-Hinweis
- kleine Projekt-`CLAUDE.md` im Produktordner fuer operative Regeln

Die Projekt-Version enthaelt nur:

- harte Architektur-Invarianten
- Arbeitszonen
- Standard-Kommandos
- Delegationsregeln fuer Subagents
- Pflicht zur Obsidian-Dokumentation

### 3. Subagents statt unscharfer Rollenbeschreibungen

Es gibt jetzt drei fokussierte Subagents:

- `frontend-vanilla-pwa`
- `odoo-backend-specialist`
- `n8n-workflow-operator`
- `code-reviewer`

Damit kann Claude Code Aufgaben gezielter delegieren, ohne die gesamte Projektoberflaeche gleichzeitig im Kontext zu halten.

Ergaenzend gibt es jetzt pfadgebundene Regeln fuer:

- `frontend.md` fuer `pwa/**`
- `backend.md` fuer `backend/**`
- `odoo.md` fuer `odoo/**`

### 3a. Verifikation als Standardpfad

Der Workflow enthaelt jetzt explizite Verify-Targets im Projekt-`Makefile`:

- `make install-backend-deps` fuer lokale Python-Abhaengigkeiten der Backend-Tests
- `make install-ui-deps` fuer Playwright und den Chromium-Testbrowser
- `make verify-code` fuer schnelle Backend-Tests ohne laufenden Stack
- `make verify-ui` fuer reproduzierbare PWA-Browser-Tests mit Playwright
- `make verify-visual` fuer visuelle PWA-Artefakte der Kernscreens unter `.claude/artifacts/`
- `make verify-visual-diff` fuer echte visuelle Baseline-Checks der Kernscreens
- `make verify-a11y` fuer automatische Accessibility-Checks der Kernscreens mit Axe + Playwright
- `make verify-workflows` fuer die Vertraege zwischen Backend-Webhooks und `n8n/workflows/*.json`
- `make verify-stack` fuer den API-Rauchtest gegen den laufenden lokalen Stack
- `make verify` fuer Backend-, UI-, Visual-, A11y-, Workflow- und Stack-Checks hintereinander

Dadurch wird Verifikation zu einem festen Teil des Workflows statt zu einem manuellen Nachgedanken.

Da das Projekt auf Windows bearbeitet wird und `make` lokal nicht immer verfuegbar ist, gibt es zusaetzlich einen PowerShell-Wrapper:

`Mobile Picking und Voice Assistant/infrastructure/scripts/workflow.ps1`

Damit bleiben die wichtigsten Workflow-Schritte auch ohne GNU Make direkt ausfuehrbar.

Aktueller Praxispunkt:
- `verify-code` braucht lokal die Python-Abhaengigkeiten aus `backend/requirements.txt`
- dafuer gibt es jetzt den expliziten Bootstrap-Schritt `install-backend-deps`
- die Pakete landen projektlokal in `backend/.deps/`, damit der Workflow unabhaengiger vom globalen Python-Setup bleibt
- test-spezifische Pakete wie `pytest-asyncio` liegen getrennt in `backend/requirements-dev.txt`
- die PWA hat jetzt zusaetzlich ein lokales Playwright-Projekt mit `playwright.config.js`, `package.json` und Specs unter `e2e/`
- die Browser-Tests laufen bewusst gegen eine lokale statische PWA plus gemockte `/api/*`-Antworten, damit UI-Regressionen reproduzierbar und ohne Live-Daten abpruefbar bleiben
- `e2e/capture-sight.js` erzeugt fuer `list`, `detail` und `alert` reproduzierbare Mobile-Screenshots und Metadaten unter `.claude/artifacts/`
- der Visual-Loop schreibt jetzt zusaetzlich ein kompaktes `.claude/artifacts/ui_state-index.json`, damit nicht immer erst PNGs geladen werden muessen
- `e2e/visual.spec.js` haelt zusaetzlich committed Baselines fuer `list`, `detail` und `alert`, damit echte Layout-Regressionen maschinell auffallen
- die Accessibility-Pruefung liegt separat in `e2e/a11y.spec.js` und scannt Picking-Liste, Picking-Detail und Quality-Alert-Form mit `@axe-core/playwright`
- fuer n8n gibt es jetzt ein leichtgewichtiges Validierungsskript `infrastructure/scripts/verify-workflows.py`, das `n8n.fire(...)`-Payloads im Backend gegen die tatsaechlich referenzierten `$json.*`-Felder in den Workflow-JSONs prueft
- die Webhook-Workflows `pick-confirmed.json` und `quality-alert-created.json` wurden auf die aktuell gelieferten Backend-Payloads ausgerichtet

### 4. Obsidian-Logging als fester Workflow-Baustein

Ein `PostToolUse`-Hook schreibt jede von Claude Code bearbeitete Datei nach:

`Notzien (Obsidian)/04 - Ressourcen/Claude Code Aenderungslog.md`

Zusaetzlich sollen Architektur- und Prozessentscheidungen weiterhin manuell in der Daily Note dokumentiert werden.

### 5. Completion-Hardening

Der Workflow nutzt jetzt neben `PostToolUse` auch einen `TaskCompleted`-Hook.

Wirkung:
- wenn Claude in der Session Dateien bearbeitet hat, wird vor Task-Abschluss geprueft, ob der Obsidian-Sync erfolgreich war
- fuer relevante Code-Aenderungen wird automatisch `verify-code` ausgefuehrt
- fuer relevante PWA- oder Playwright-Aenderungen wird automatisch `verify-ui` ausgefuehrt
- fuer sichtbare UI-Aenderungen an `pwa/*.css`, `pwa/*.html`, UI-relevanten `pwa/*.js` oder am Visual-Capture-Setup wird zusaetzlich `verify-visual` ausgefuehrt
- fuer sichtbare UI-Aenderungen wird jetzt zusaetzlich `verify-visual-diff` gegen die committed Baselines ausgefuehrt
- fuer relevante PWA- oder Playwright-Aenderungen wird zusaetzlich `verify-a11y` ausgefuehrt
- fuer relevante Backend-Webhook- oder `n8n/workflows/`-Aenderungen wird automatisch `verify-workflows` ausgefuehrt
- `verify-stack` wird zusaetzlich erzwungen, wenn der lokale Stack erkennbar laeuft

Damit wird "fertig" nicht mehr nur textlich behauptet, sondern technisch ueberprueft.

## MCP-Stand

Playwright ist als inline MCP innerhalb des Frontend-Subagents vorgesehen und wird nur dort geladen, wo Browser-Tests wirklich gebraucht werden.

Der PostgreSQL-MCP ist jetzt projektweit ueber `.mcp.json` vorbereitet.

Wichtige Sicherheitsentscheidung:
- PostgreSQL wird nur lokal auf `127.0.0.1:${POSTGRES_HOST_PORT:-5433}` gebunden
- die MCP-Startlogik liest Zugangsdaten aus `Mobile Picking und Voice Assistant/.env`
- es wird kein Datenbank-Passwort in ein geteiltes Repo-Configfile geschrieben

Aktueller Verifikationsstand:
- `workflow.ps1 verify-code`: 25/25 Backend-Tests gruen
- `workflow.ps1 verify-ui`: 3/3 Playwright-Browser-Tests gruen
- `workflow.ps1 verify-visual`: visuelle Artefakte fuer `list`, `detail` und `alert` werden erfolgreich erzeugt
- `workflow.ps1 verify-visual-diff`: 3/3 visuelle Snapshot-Checks gruen
- `workflow.ps1 verify-a11y`: 3/3 Axe-Checks gegen die Kern-Views gruen
- `workflow.ps1 verify-workflows`: Workflow-Vertragspruefung gruen
- `workflow.ps1 verify-stack`: API-Smoke-Test 7/7 gruen
- `workflow.ps1 verify`: Backend-Tests gruen, Playwright 6/6 inkl. A11y gruen, visuelle Artefakte gruen, Workflow-Vertragspruefung gruen und API-Smoke-Test 7/7 gruen

Visual-Sight-Fazit:
- der Loop arbeitet standardmaessig gegen die lokale statische PWA auf `http://127.0.0.1:4173`
- die API wird dabei standardmaessig gemockt, damit visuelle Regressionen nicht vom Live-Stack abhaengen
- bei Bedarf kann der Capture-Lauf ueber Umgebungsvariablen auf einen Live-Stack mit HTTPS umgebogen werden
- der Live-Capture gegen `https://localhost` wurde erfolgreich mit `ignoreHTTPSErrors` verifiziert
- der Screenshot gilt nicht mehr schon dann als "gut", wenn nur `#app` sichtbar ist; pro View werden jetzt semantische Ready-Checks geprueft, z. B. Picking-Karte, Confirm-Button oder Alert-Form-Felder
- die Artefakte laufen jetzt im kleineren Viewport-Capture mit CSS-Scale statt Full-Page-Shots, um Dateigroesse und spaeteren Analyseaufwand zu senken
- `verify-ui` ist wieder strikt funktional getrennt; A11y und visuelle Diffs laufen in eigenen, klar benannten Schritten
- der Playwright-HTML-Reporter ist nicht mehr standardmaessig aktiv, damit der Windows-Verify-Loop keine `EBUSY`-Locks auf `playwright-report/` erzeugt

Bewusste Nicht-Uebernahmen aus der Review-Idee:
- kein Umzug des Capture-Skripts nach `infrastructure/scripts/`, weil es absichtlich die bestehenden `e2e`-Helper und Mock-API wiederverwendet
- keine neue zweite PWA-Rule-Datei, weil die vorhandene `.claude/rules/frontend.md` bereits der richtige path-spezifische Einstiegspunkt ist
- keine automatische Obsidian-Sonderzeile aus `log_obsidian_change.py` fuer jeden Visual-Check, damit der Hook weiter klar fuer Dateimutationen und nicht fuer beliebige Kommandos zustaendig bleibt

Praktische A11y-Fixes aus der ersten Einfuehrung:
- Kontrast der Positions-/Badge-Texte in der Picking-UI angehoben
- explizite Labels fuer Beschreibung und Prioritaet im Quality-Alert-Formular
- zugaengliche `aria-label`s fuer Foto-Hinzufuegen und Foto-Entfernen

Debugging-Erkenntnis:
- der Proxy musste nicht umgebaut werden
- rohe Requests gegen `https://localhost/api/*` und Direktaufrufe gegen `http://127.0.0.1:8000/api/*` lieferten identische JSON-/422-Antworten
- die zuvor roten `verify-stack`-Laeufe waren damit kein belastbarer Beleg fuer einen Prefix- oder `handle_path`-Fehler in Caddy

## Naechste sinnvolle Schritte

1. spaeter die visuellen Baselines auf weitere kritische States ausdehnen, wenn die UI stabil genug dafuer ist
2. spaeter den Smoke-Test weiter haerten, falls die transienten Stack-Effekte erneut auftauchen
3. mittelfristig einen sauberen Contract-First-Pfad zwischen Backend und PWA definieren
