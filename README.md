# Mobile Picking und Voice Assistant

Bachelorarbeit-PoC fuer einen hybriden, sprachgestuetzten mobilen Picking-Assistenten auf Basis von Odoo 18 Community, FastAPI, n8n und einer PWA.

## Aktueller Stand

- Odoo bleibt System of Record
- FastAPI bleibt die einzige App-API fuer die PWA
- n8n bleibt Orchestrator fuer async Events und synchrone Ausnahmeassistenz
- Whisper laeuft lokal als ASR-Service; der normale Voice-Pfad bleibt ohne n8n
- Welle A fuer die Quality-Alert-KI-Bewertung ist im Repo umgesetzt
- Phase A-C fuer kontrollierte Inbetriebnahme, neutrales Integrations-Logging und Telemetrie-Export ist im Repo vorbereitet

## Welle A: Quality Alert KI-Bewertung

Diese Welle war bewusst klein und technisch risikoarm.

Umgesetzt:

- Odoo-UI der Tab `KI-Bewertung` bereinigt
- Odoo-Datenmodell minimal erweitert um:
  - `ai_enhanced_description`
  - `ai_photo_analysis`
- internen Writeback-Vertrag fuer `quality-assessment` erweitert
- Klartext-Chatter fuer KI-Writebacks eingefuehrt
- `n8n/workflows/quality-alert-created.json` minimal erweitert
- Heuristik-Fallback beibehalten

Nicht Teil von Welle A:

- keine mobile Diktierfunktion
- kein `draft-enhancement`
- keine echte Vision-Pipeline
- kein OpenAI-Zwang
- keine neue Quality-Alert-Bedienlogik in der PWA

## Kernfunktionen

### Picking
- offene Pickings in der PWA
- Soft Claiming mit Heartbeats
- Idempotency fuer mutierende Requests
- Barcode-, Touch- und Voice-Bestaetigung
- Route-Plan fuer offene Pick-Positionen

### Voice
- `POST /api/voice/recognize` fuer lokalen Voice-Hot-Path
- `POST /api/voice/assist` fuer synchrone Ausnahmeassistenz
- Odoo- und Obsidian-Kontext koennen in Ausnahmefaellen angereichert werden

### Quality Alerts
- `POST /api/quality-alerts` akzeptiert Beschreibung, Kontext und optional mehrere Fotos
- Alerts werden zuerst in Odoo erstellt; `ai_evaluation_status = pending` wird nur gesetzt, wenn `quality-alert-created` erfolgreich an n8n uebergeben wurde
- wenn die n8n-Uebergabe scheitert, bleibt der Alert sichtbar, wird aber auf `failed` markiert und im Chatter begruendet
- n8n bewertet den Alert asynchron und schreibt kontrolliert ueber FastAPI zurueck
- Odoo zeigt im Hauptblock `Systembewertung` nur:
  - Analyse-Status
  - Einstufung
  - Empfohlene Aktion
  - Analysiert am

## Architektur in Kurzform

```text
PWA -> Caddy -> FastAPI -> Odoo
                |-> Whisper
                `-> n8n
n8n -> interne FastAPI-Callbacks -> Odoo
```

## Wichtige Endpunkte

| Methode | Pfad | Zweck |
| ------- | ---- | ----- |
| `GET` | `/api/pickers` | aktive Odoo-Picker |
| `GET` | `/api/pickings` | offene Pickings |
| `POST` | `/api/pickings/{id}/confirm-line` | Pick bestaetigen |
| `POST` | `/api/quality-alerts` | Quality Alert anlegen |
| `POST` | `/api/voice/recognize` | Transkript + Intent |
| `POST` | `/api/voice/assist` | synchrone Ausnahmeassistenz |
| `POST` | `/api/internal/n8n/quality-assessment` | Quality-Writeback |
| `POST` | `/api/internal/n8n/replenishment-action` | Replenishment-Writeback |
| `POST` | `/api/integration/log` | neutrales Integrations-/Audit-Logging fuer n8n |

## Wichtige Dokumente

- `docs/ARCHITECTURE.md`
- `docs/QUALITY_ALERT_AI_FIELDS.md`
- `docs/N8N_CONTRACT_FREEZE_V1.md`
- `../Notzien/03 - Features/Welle A - Quality Alert KI Bewertung.md`

## Setup in Kurzform

```powershell
docker compose up -d
```

Danach typischerweise:

1. Odoo-Addons installieren oder upgraden
2. `.env` sauber setzen und `ODOO_API_KEY` auf einen dedizierten Service-User legen
3. n8n-Backup erzeugen: `bash infrastructure/scripts/import-workflows.sh backup`
4. n8n-Workflows kontrolliert importieren: `bash infrastructure/scripts/import-workflows.sh import <backup-dir>`
5. Workflows gezielt aktivieren: `bash infrastructure/scripts/import-workflows.sh activate <backup-dir> <workflow-file>`
6. API und PWA pruefen

## Verifikation des Welle-A-Stands

Lokal erfolgreich geprueft:

- `python -m pytest backend/tests/test_n8n_internal_routes.py -q`
- Python-Syntaxcheck der geaenderten Backend-Dateien
- XML-Parse der Odoo-View
- JSON-Parse des n8n-Workflows

Noch offen fuer den Live-Stand:

- Odoo-Addon-Upgrade in der aktiven Datenbank
- gestuften n8n-Importpfad gegen die Live-Runtime durchlaufen
- Smoke-Tests fuer Voice, Quality und Replenishment live ausfuehren
- Telemetrie-Export fuer das Live-Testfenster erzeugen

## Naechste sinnvolle Schritte

1. gestuften n8n-Rollout mit `backup -> import -> activate` live durchlaufen
2. Erfolgspfad und Fehlerpfad fuer Quality/Voice/Replenishment manuell pruefen
3. Telemetrie mit `python infrastructure/scripts/export_telemetry_stats.py --since ...` auswertbar exportieren
