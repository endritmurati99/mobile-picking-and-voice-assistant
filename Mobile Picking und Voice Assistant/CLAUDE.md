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
make test
make test-api
make seed
```

Wenn nur ein Service betroffen ist:

```bash
make build-backend
make build-odoo
docker compose restart backend
docker compose restart odoo
```

## Delegation

- Nutze den Subagent `frontend-vanilla-pwa` proaktiv fuer Arbeit in `pwa/`, HTML/CSS/Vanilla-JS, mobile Browser-Probleme und UI-Regressionen.
- Nutze den Subagent `odoo-backend-specialist` proaktiv fuer Odoo-Modelle, JSON-RPC, FastAPI-Endpoints und Datenflussfragen.
- Nutze den Subagent `n8n-workflow-operator` proaktiv fuer `n8n/workflows/`, Webhook-Tests und Automatisierungsskripte.

## Kontext-Hygiene

- Oeffne nur die Verzeichnisse, die fuer die aktuelle Aufgabe relevant sind.
- Lies Obsidian-Notizen nur bei Architektur-, Entscheidungs- oder Planungsfragen.
- Ignoriere `.obsidian/`, Caches, Binaerdateien und lokale Secrets.
- Antworte kurz. Bevorzuge konkrete Aenderungen und direkte Verifikation statt langer Prosa.

## Obsidian-Pflicht

- Jede relevante Code-Aenderung muss in Obsidian nachvollziehbar sein.
- Der Projekt-Hook schreibt Datei-Aenderungen automatisch nach `Notzien (Obsidian)/04 - Ressourcen/Claude Code Aenderungslog.md`.
- Bei Architektur- oder Prozessentscheidungen zusaetzlich die Daily Note fuer den aktuellen Tag aktualisieren.

## Tiefere Referenzen

- `../Notzien (Obsidian)/01 - Architektur/System Architektur.md`
- `../Notzien (Obsidian)/01 - Architektur/Voice Intent Engine.md`
- `../Notzien (Obsidian)/01 - Architektur/PWA Implementierungshinweise.md`
- `docs/ARCHITECTURE.md`
- `docs/VOICE_COMMANDS.md`
