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

### 3a. Verifikation als Standardpfad

Der Workflow enthaelt jetzt explizite Verify-Targets im Projekt-`Makefile`:

- `make install-backend-deps` fuer lokale Python-Abhaengigkeiten der Backend-Tests
- `make install-ui-deps` fuer Playwright und den Chromium-Testbrowser
- `make verify-code` fuer schnelle Backend-Tests ohne laufenden Stack
- `make verify-ui` fuer reproduzierbare PWA-Browser-Tests mit Playwright
- `make verify-stack` fuer den API-Rauchtest gegen den laufenden lokalen Stack
- `make verify` fuer Backend-, UI- und Stack-Checks hintereinander

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
- `workflow.ps1 verify`: Backend-Tests gruen, Playwright 3/3 gruen und API-Smoke-Test 7/7 gegen `https://localhost`

## Naechste sinnvolle Schritte

1. Playwright-MCP gezielt fuer visuelle Debug-Sessions und Screenshots am Live-Stack testen
2. `verify-a11y` mit `@axe-core/playwright` fuer die Kernscreens ergaenzen
3. n8n-Workflow-Validator als Skript oder Subagent ergaenzen
