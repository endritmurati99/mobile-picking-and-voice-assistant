# Block 1 Report

## Ziel

Arbeitsstand fuer den heutigen E2E-Nachweis einfrieren, Recovery-Points anlegen, Trust Boundaries verifizieren und einen konkreten Testfall festziehen, bevor Block 2 oder Block 3 starten.

## Recovery Point

- Branch eingefroren auf `wip/staff-hardening-2026-03-22`
- Tagesziel fixiert: `E2E Quality-Alert bis completed; Fehlerpfad spaeter bis failed`
- Neue `.env`-Sicherung: `env-backup-20260328-171135.env`
- Neuer Workflow-Backup-Ordner: `n8n/backups/block1-20260328-171135`
- Live-Workflow-Exporte liegen vor fuer:
  - `Error Trigger`
  - `Quality Alert Created`
  - `Voice Exception Query`
  - `Shortage Reported`

## Secret- und Runtime-Befunde

- `ODOO_API_KEY`: in `.env` gesetzt, im Backend geladen und operativ bestaetigt, weil Odoo-backed Endpoints erfolgreich antworten.
- `ODOO_API_KEY`: Wert wirkt weiterhin wie der bekannte `admin`-Fallback und nicht wie ein dedizierter technischer API-Key.
- `N8N_CALLBACK_SECRET`: `.env`, Backend und n8n-Runtime stimmen ueberein.
- `N8N_WEBHOOK_SECRET`: `.env` und Backend stimmen ueberein.
- `N8N_ENCRYPTION_KEY`: `.env` und n8n-Runtime stimmen ueberein; der Wert bleibt unberuehrt.

## Externe Abhaengigkeiten

- OpenAI: fuer den heutigen Quality-Alert-E2E bewusst aus Scope genommen.
- Begruendung: der aktuelle `Quality Alert Created`-Workflow nutzt heuristische Funktionsknoten und keinen OpenAI-Node.
- SMTP: nicht betriebsbereit.
- Befund:
  - `QUALITY_ALERT_EMAIL_FROM` fehlt in `.env`
  - `QUALITY_ALERT_EMAIL_TO` fehlt in `.env`
  - n8n-Runtime hat fuer Mail-Absender, Mail-Empfaenger und SMTP-Transport nur leere Werte
  - `credentials_entity` in der n8n-Datenbank ist leer
  - `settings` in der n8n-Datenbank enthalten keine SMTP-/Mail-Konfiguration

## Konkreter Testfall fuer spaeter

- Basisobjekt:
  - Picker: `Max Picker` (`X-Picker-User-Id: 7`)
  - Device: `block1-e2e-20260328`
  - Picking: `WH/INT/00337`
  - Kit: `LKW`
  - Produkt: `Brick 2x2 blau` (`product_id=144`)
  - Lagerplatz: `L-E5-P1` (`location_id=301`)

- Happy Path fuer Block 4:
  - `POST /api/quality-alerts`
  - `Idempotency-Key: block4-quality-337-happy`
  - Beschreibung: `Auffaelligkeit am Artikel, Sichtpruefung erbeten.`
  - Erwartung: `pending -> completed`, erfolgreicher `Quality Alert Created`-Run, Obsidian-Log sichtbar

- Error Path fuer Block 5:
  - `POST /api/quality-alerts`
  - `Idempotency-Key: block5-quality-337-fail`
  - Beschreibung: `Intentional callback contract test`
  - Vor dem Lauf wird die Callback-Strecke gezielt gebrochen
  - Erwartung: `pending -> failed`, kein falscher Write-Back, Incident-Log sichtbar

## Relevanter Kontext vor Block 2

- In `quality_alert_custom` liegen bereits historische Alerts mit gemischten Stati:
  - mehrere alte `pending`
  - mindestens ein `failed`
  - mehrere `completed`
- Folge: spaetere Verifikation darf nicht allgemein auf "irgendein pending/completed" schauen, sondern muss den frisch erzeugten Alert exakt per neuer `alert_id` verfolgen.

## Block-1-Abnahme

Block 1 ist noch **nicht gruen**.

Offene Blocker:

- SMTP-Transport ist nicht konfiguriert
- `QUALITY_ALERT_EMAIL_FROM` und `QUALITY_ALERT_EMAIL_TO` sind in `.env` weiterhin leer bzw. fehlen

Nicht blockierend fuer den heutigen Quality-Alert-Pfad:

- `OPENAI_API_KEY` fehlt, ist fuer den aktuellen heuristischen Quality-Alert-Workflow aber bewusst aus Scope genommen
