# CLAUDE.md

Operative Arbeitsanweisung fuer Claude Code im Teilprojekt `Mobile Picking und Voice Assistant/`.

## Ziel

Arbeite token-effizient, code-first und innerhalb der vorhandenen Architektur. Nutze Obsidian nur gezielt fuer Architektur, Entscheidungen und Aenderungsdokumentation.

## Nicht verhandelbare Invarianten

1. Odoo ist das System of Record. Keine Schatten-Datenbank und keine doppelten Geschaeftsdaten.
2. Die PWA spricht nur mit FastAPI. Keine direkte Kommunikation von `pwa/` mit Odoo oder n8n.
3. n8n ist Orchestrator, nicht App-Backend, und liegt nicht im Voice-Hot-Path.
4. HTTPS im LAN bleibt Pflicht fuer Kamera, Mikrofon und Service Worker.
5. Touch ist immer Fallback. Voice und Scan duerfen nie die einzige Bedienmoeglichkeit sein.
6. Keine externen Cloud-Dienste fuer den Kern-Workflow. STT bleibt lokal.

## Arbeitszonen

- `backend/`: FastAPI, JSON-RPC-Bridge zu Odoo, Intent-Engine, Business-Logik
- `odoo/`: Custom Addon `quality_alert_custom`, Odoo-Konfiguration
- `pwa/`: Mobile-first Frontend in Vanilla JS, CSS und HTML
- `n8n/workflows/`: Workflow-JSONs und Webhook-Orchestrierung
- `docs/`: technische Projektdokumentation

## Wichtige Kommandos

```bash
make build-all
make up
make down
make logs
make logs-backend
make logs-odoo
make install-backend-deps
make install-ui-deps
make test
make test-ui
make test-visual
make test-visual-diff
make test-visual-diff-update
make test-a11y
make test-api
make test-n8n-api
make verify-code
make verify-ui
make verify-visual
make verify-visual-diff
make verify-a11y
make verify-workflows
make verify-stack
make verify
make seed
```

Wenn nur ein Service betroffen ist:

```bash
make build-backend
make build-odoo
docker compose restart backend
docker compose restart odoo
```

Windows ohne `make`:

```powershell
powershell -ExecutionPolicy Bypass -File infrastructure/scripts/workflow.ps1 verify
powershell -ExecutionPolicy Bypass -File infrastructure/scripts/workflow.ps1 logs-backend
powershell -ExecutionPolicy Bypass -File infrastructure/scripts/workflow.ps1 install-backend-deps
powershell -ExecutionPolicy Bypass -File infrastructure/scripts/workflow.ps1 install-ui-deps
```

MCP:

```bash
claude mcp list
```

Die Projekt-MCPs werden ueber `.mcp.json` geladen.
- `postgres-local` nutzt den lokalen, nur auf `127.0.0.1` gebundenen PostgreSQL-Port.
- n8n MCP wird in Claude Code bewusst **nicht** ueber die geteilte `.mcp.json` konfiguriert, weil dafuer ein persoenlicher MCP-Token noetig ist.
- Fuer dieses Projekt n8n stattdessen lokal mit `claude mcp add -s local --transport http ...` anbinden, damit keine Secrets im Repo landen.
- Bei lokalem n8n ueber `https://localhost` braucht Claude Code zusaetzlich oft `SSL_CERT_FILE` und `NODE_EXTRA_CA_CERTS` auf die `mkcert`-Root-CA, sonst scheitert der HTTP-MCP-Handshake trotz korrektem Token.

Lokaler Test-Bootstrap:

- `install-backend-deps` installiert Backend-Testabhaengigkeiten projektlokal nach `backend/.deps/`
- Die Test-Abhaengigkeiten werden aus `backend/requirements-dev.txt` geladen
- `test` und `verify-code` nutzen diesen lokalen Pfad automatisch
- `install-ui-deps` installiert Playwright plus Chromium fuer den lokalen Browser-Verify-Layer
- `test-ui` und `verify-ui` starten reproduzierbare PWA-Browser-Tests ueber Playwright
- `test-visual` und `verify-visual` erzeugen semantisch validierte Mobile-Artefakte der PWA unter `.claude/artifacts/`, standardmaessig mit gemockter API und Mobile-Viewport
- lies fuer den Visual-Loop zuerst `.claude/artifacts/ui_state-index.json`, dann nur bei Bedarf die einzelnen PNG-Dateien
- `test-visual-diff` und `verify-visual-diff` pruefen 3 stabile Mobile-Baselines per Playwright-Snapshot-Test
- `test-visual-diff-update` aktualisiert bewusst die Baselines, wenn ein Layout gewollt veraendert wurde
- `test-a11y` und `verify-a11y` pruefen die Kern-Views der PWA automatisiert mit Axe + Playwright
- `verify-workflows` prueft die Vertraege zwischen `n8n/workflows/*.json` und den `n8n.fire(...)`-Payloads im Backend

## Delegation

- Nutze den Subagent `frontend-vanilla-pwa` proaktiv fuer Arbeit in `pwa/`, HTML/CSS/Vanilla-JS, mobile Browser-Probleme und UI-Regressionen.
- Nutze den Subagent `odoo-backend-specialist` proaktiv fuer Odoo-Modelle, JSON-RPC, FastAPI-Endpoints und Datenflussfragen.
- Nutze den Subagent `n8n-workflow-operator` proaktiv fuer `n8n/workflows/`, Webhook-Tests und Automatisierungsskripte.
- Nutze den Subagent `code-reviewer` proaktiv nach groesseren Aenderungen fuer Bug-Risiken, Regressionen und fehlende Tests.

## Kontext-Hygiene

- Oeffne nur die Verzeichnisse, die fuer die aktuelle Aufgabe relevant sind.
- Lies Obsidian-Notizen nur bei Architektur-, Entscheidungs- oder Planungsfragen.
- Ignoriere `.obsidian/`, Caches, Binaerdateien und lokale Secrets.
- Antworte kurz. Bevorzuge konkrete Aenderungen und direkte Verifikation statt langer Prosa.

## Obsidian-Pflicht

- Jede relevante Code-Aenderung muss in Obsidian nachvollziehbar sein.
- Der Projekt-Hook schreibt Datei-Aenderungen automatisch nach `Notzien/04 - Ressourcen/Claude Code Aenderungslog.md`.
- Der Hook legt den Session-Nachweis zusaetzlich in `.claude/state/last_obsidian_sync.json` ab; darauf stuetzt sich der Completion-Check.
- Fuer schnellen Note-Zugriff zuerst `../Notzien/00 - Projekt Übersicht.md` lesen und dann nur die direkt relevanten Architektur-, Phasen- oder Daily-Notes oeffnen.
- Obsidian wird in diesem Repo mit normalen Markdown-Dateien, Wikilinks und gezielter Volltextsuche genutzt; es gibt keine separate Obsidian-API oder eigene Metadatenbank.
- Fuer Code-Arbeit werden Notizen gezielt gelesen und mit `rg` durchsucht, nicht als kompletter Vault in den Kontext gezogen.
- Bei Architektur- oder Prozessentscheidungen zusaetzlich die Daily Note fuer den aktuellen Tag aktualisieren.
- Fuer n8n-Integrationen keine Tokens ins Repo schreiben; Public API und MCP laufen bewusst ueber lokale Umgebungsvariablen.
- Fuer Claude-Code-MCP ist bei n8n der direkte HTTP-Transport der richtige Weg; ein stdio/supergateway-Wrapper ist hier nicht der bevorzugte Projektpfad.

## Completion Criteria

- Wenn Claude in der aktuellen Session Dateien editiert hat, darf der Task erst abgeschlossen werden, wenn der Obsidian-Sync-Hook erfolgreich gelaufen ist.
- Bei Aenderungen an `backend/`, `odoo/`, `pwa/` oder relevanten Infrastruktur-Skripten muss `verify-code` erfolgreich sein.
- Bei Aenderungen an `pwa/`, den Playwright-Specs oder der UI-Testkonfiguration muss `verify-ui` erfolgreich sein.
- Bei sichtbaren UI-Aenderungen an `pwa/` oder den visuellen Testskripten muss zusaetzlich `verify-visual` erfolgreich sein; reine Backend-Aenderungen sollen diesen Schritt nicht unnoetig triggern.
- Bei sichtbaren UI-Aenderungen an `pwa/` oder den visuellen Testskripten muss zusaetzlich `verify-visual-diff` gegen die Baselines erfolgreich sein.
- Bei Aenderungen an `pwa/` oder den UI-Specs muss zusaetzlich `verify-a11y` erfolgreich sein.
- Bei Aenderungen an `n8n/workflows/` oder Backend-Webhook-Vertraegen muss `verify-workflows` erfolgreich sein.
- Wenn der lokale Stack laeuft, wird zusaetzlich `verify-stack` erwartet.
- Diese Kriterien werden technisch ueber den `TaskCompleted`-Hook in `.claude/settings.json` durchgesetzt.

## Tiefere Referenzen

- `../Notzien/01 - Architektur/System Architektur.md`
- `../Notzien/01 - Architektur/Voice Intent Engine.md`
- `../Notzien/01 - Architektur/PWA Implementierungshinweise.md`
- `docs/ARCHITECTURE.md`
- `docs/VOICE_COMMANDS.md`
