# Architektur

## Systemrollen

- `PWA`
  - mobile Bedienoberflaeche fuer Picking, Voice, Scan und Quality Alerts
- `FastAPI`
  - App-API, Odoo-Adapter, Idempotency- und Claim-Schicht
- `Odoo`
  - fachliche Datenquelle fuer Pickings, Quality Alerts, Nutzer und Lagerplaetze
- `n8n`
  - Orchestrator fuer async Events und synchrone Ausnahmeassistenz
- `Whisper`
  - lokaler ASR-Service fuer `POST /api/voice/recognize`

## Architekturregeln

1. Odoo bleibt System of Record.
2. FastAPI ist die einzige API-Schicht fuer die PWA.
3. n8n liegt nicht im normalen Voice-Hot-Path.
4. Fachliche Writes aus n8n laufen nur ueber interne FastAPI-Callbacks.
5. Touch bleibt Fallback, Voice ist Enhancement.

## Hauptfluesse

### Pick-Bestaetigung
1. PWA -> `POST /api/pickings/{id}/confirm-line`
2. FastAPI validiert Identitaet, Claim und Idempotency
3. FastAPI schreibt nach Odoo
4. FastAPI feuert `pick-confirmed` asynchron an n8n
5. Wenn die n8n-Uebergabe fehlschlaegt, bleibt das Picking fachlich abgeschlossen, aber die Antwort wird als degradierter Folgeprozess markiert

### Voice-Hot-Path
1. PWA -> `POST /api/voice/recognize`
2. FastAPI -> Whisper
3. lokale Intent-Logik entscheidet ueber den naechsten Schritt
4. PWA reagiert sofort

### Sync Ausnahmeassistenz
1. PWA -> `POST /api/voice/assist`
2. FastAPI reichert Odoo- und Obsidian-Kontext an
3. FastAPI -> n8n `voice-exception-query`
4. n8n antwortet synchron oder FastAPI faellt lokal zurueck

### Quality Alert mit Welle A
1. PWA -> `POST /api/quality-alerts`
2. FastAPI erstellt `quality.alert.custom` in Odoo
3. FastAPI -> n8n `quality-alert-created`
4. Nur bei erfolgreicher Uebergabe setzt FastAPI `ai_evaluation_status = pending`
5. Wenn die Uebergabe scheitert, markiert FastAPI den Alert als `failed` und schreibt den Grund in den Chatter
6. n8n bewertet heuristisch und ruft `POST /api/internal/n8n/quality-assessment` auf
7. FastAPI schreibt strukturierte KI-Felder kontrolliert nach Odoo zurueck

## Quality-Alert-Felder nach Welle A

- `description`
  - Originalbeschreibung des Pickers
- `ai_enhanced_description`
  - sprachlich bereinigte KI-Fassung ohne neue Fakten
- `ai_photo_analysis`
  - separater visueller Bildbefund
- `ai_summary`
  - Management-Zusammenfassung
- `ai_recommended_action`
  - operative Empfehlung
- `ai_evaluation_status`
  - technischer Verarbeitungsstatus

## Odoo-Sichtbarkeit

Der sichtbare Hauptblock fuer Quality Alerts heisst `Systembewertung` und zeigt nur:

- Analyse-Status
- Einstufung
- Empfohlene Aktion
- Analysiert am

Zusatzregel:

- KI-Chatter fuer Quality Alerts wird als Klartext geschrieben, nicht mehr als HTML-Fragment.
- Ausfuehrliche Begruendung und technische Fehler gehoeren in den Chatter, nicht in den Hauptblock.

## Runtime-Hinweis

Der Repo-Stand bildet Welle A bereits ab.
Fuer den sichtbaren Live-Effekt fehlen aber weiterhin:

- Odoo-Addon-Upgrade in der aktiven Datenbank
- kontrollierter Import bzw. Aktivierungsabgleich des aktualisierten `quality-alert-created`-Workflows
