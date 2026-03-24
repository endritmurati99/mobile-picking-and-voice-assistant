# Mobile Picking und Voice Assistant

Aktueller Projektstand fuer die Bachelorarbeit: mobile Picking-PWA mit FastAPI-Backend, Odoo als System of Record und n8n fuer Benachrichtigungen.

Diese README dokumentiert den aktuellen Stand nach Phase 1 "Transaktionshaertung".

## Aktueller Hinweis aus dem Live-Setup

Der Fehler "Auftrag kann nicht geoeffnet werden" trat in deinem aktuellen Setup auf, weil das Odoo-Addon `picking_assistant_core` noch nicht in der aktiven Odoo-Datenbank installiert war.

Das konkrete Fehlersignal im Backend war:

- `Object picking.assistant.idempotency doesn't exist`

Dadurch schlug schon der erste Claim-Request fehl und die PWA konnte das Picking nicht oeffnen.

Das Addon wurde inzwischen in der aktiven Datenbank installiert und der Odoo-Service neu gestartet.

## Was das Projekt aktuell macht

- Picker sehen offene Pickings in der PWA.
- Ein Picking wird gefuehrt Position fuer Position bearbeitet.
- Scan, Touch-Bestaetigung, TTS und Quality Alerts sind vorhanden.
- Odoo bleibt die fachliche Quelle fuer Lager- und Picking-Daten.
- n8n wird weiter nur fire-and-forget fuer Folgeaktionen genutzt.

## Was in Phase 1 neu umgesetzt wurde

### 1. Picker-Identitaet

- Die PWA laedt aktive Odoo-Benutzer ueber `GET /api/pickers`.
- Beim ersten Start waehlt der Nutzer einen Picker aus.
- Die Auswahl wird lokal gespeichert.
- Zusaetzlich bekommt jedes Geraet eine lokale `device_id`.

### Was ist ein "Odoo Picker"?

Mit "Odoo Picker" ist kein neuer Spezial-Datensatz gemeint.

Gemeint ist einfach:

- ein aktiver interner Odoo-Benutzer
- der gerade fuer die aktuelle Picking-Session ausgewaehlt wurde
- damit Odoo, Backend und n8n wissen, wer gerade pickt

Beispiel:

- Wenn du links oben `Administrator` siehst, dann ist genau dieser Odoo-Benutzer aktuell als Picker fuer die Session ausgewaehlt.

Also ja:
Der Name links oben bedeutet praktisch "Wer pickt gerade auf diesem Geraet?".

### 2. Soft Claiming fuer Pickings

- Beim Oeffnen eines Pickings wird automatisch ein Claim gesetzt.
- Solange die Detailansicht offen ist, sendet die PWA Heartbeats.
- Beim Verlassen oder nach Abschluss wird der Claim freigegeben.
- Wenn ein anderes Geraet dasselbe Picking aktiv bearbeitet, bekommt der zweite Nutzer einen klaren Konflikt statt stiller Ueberschreibung.

### 3. Idempotency fuer Write-Requests

- Mutierende Requests senden jetzt Idempotency Keys:
  - `POST /api/pickings/{id}/claim`
  - `POST /api/pickings/{id}/heartbeat`
  - `POST /api/pickings/{id}/release`
  - `POST /api/pickings/{id}/confirm-line`
  - `POST /api/quality-alerts`
- Gleicher Key plus gleicher Request gibt dieselbe Antwort zurueck.
- Gleicher Key plus anderer Payload liefert `409 Conflict`.
- Damit werden Doppelbuchungen bei Retries, Funkloch oder Doppelklicks verhindert.

### 4. Odoo-seitige Absicherung

- Neues Addon: `odoo/addons/picking_assistant_core`
- Neue Claim-Felder auf `stock.picking`
- Neues Odoo-Modell fuer Idempotency-Logs
- Claim-, Heartbeat-, Release- und Idempotency-Methoden laufen direkt in Odoo, nicht nur im FastAPI-Backend

### 5. Erweiterte Webhook-Payloads

- `pick-confirmed` sendet jetzt zusaetzlich:
  - `completed_by_user_id`
  - `completed_by_device_id`
- `quality-alert-created` sendet jetzt zusaetzlich:
  - `reported_by`
  - `reported_by_user_id`
  - `reported_by_device_id`

## Was du jetzt sichtbar in der PWA sehen solltest

- Im Header gibt es jetzt einen Picker-Indikator.
- Beim ersten Start wird ein Picker ausgewaehlt. Wenn nur ein aktiver Picker existiert, wird dieser automatisch genommen.
- Wenn zwei Geraete dasselbe Picking oeffnen wollen, sieht das zweite Geraet eine Claim-Konflikt-Ansicht.

Wichtig:
Der groesste Teil der Aenderung ist absichtlich nicht "fancy UI", sondern Transaktionsschutz im Hintergrund. Deshalb sieht die App auf den ersten Blick fast gleich aus, arbeitet aber robuster.

## Wie du den neuen Stand benutzt

### Normaler Picking-Flow

1. PWA starten.
2. Picker auswaehlen.
3. Ein Picking aus der Liste oeffnen.
4. Das Picking wird automatisch geclaimt.
5. Positionen wie bisher bestaetigen.
6. Beim Abschluss oder beim Zurueckgehen wird der Claim freigegeben.

### Picker wechseln

1. Auf den Picker-Namen im Header tippen.
2. Die gespeicherte Auswahl wird geloescht.
3. Danach wird die Picker-Auswahl erneut angezeigt.

### Claim-Konflikt

Wenn ein Picking bereits aktiv von jemand anderem bearbeitet wird:

- du kannst es nicht parallel bearbeiten
- die PWA zeigt, wer es gerade blockiert
- du kannst spaeter erneut pruefen oder zur Liste zurueckgehen

## Backend- und Header-Verhalten

Die PWA sendet bei Write-Requests automatisch:

- `Idempotency-Key`
- `X-Picker-User-Id`
- `X-Device-Id`

Damit funktionieren Claiming, Replay-Schutz und echte Picker-Zuordnung.

Aktuell ist noch `Grace Mode` aktiv:

- Falls ein alter PWA-Client ohne diese Header sendet, blockiert das Backend nicht sofort hart.
- Stattdessen wird gewarnt und der alte Client darf vorerst weiterlaufen.
- Das ist ein Rollout-Schutz fuer Service-Worker-/Cache-Mischstaende.

## Was du fuer den Live-Betrieb noch machen musst

### Odoo-Addon installieren

Das neue Addon muss in Odoo installiert oder aktualisiert werden:

- `odoo/addons/picking_assistant_core`

Ohne dieses Addon fehlen:

- Claim-Methoden
- Idempotency-Methoden
- Claim-Felder auf `stock.picking`

### Installation im Docker-Setup

Wenn Odoo bereits laeuft, kannst du das Addon so installieren:

```powershell
docker compose -f "Mobile Picking und Voice Assistant/docker-compose.yml" exec odoo `
  odoo -c /etc/odoo/odoo.conf `
  -d <DEINE_ODOO_DB> `
  --db_password=<DEIN_POSTGRES_PASSWORT> `
  --http-port=8070 `
  -i picking_assistant_core `
  --stop-after-init
```

Danach Odoo neu starten:

```powershell
docker compose -f "Mobile Picking und Voice Assistant/docker-compose.yml" restart odoo
```

In deinem aktuellen lokalen Setup war die aktive Odoo-Datenbank:

- `masterfischer`

Deshalb wurde dort installiert.

### Konfiguration

Neue optionale Umgebungswerte in `.env`:

- `MOBILE_CLAIM_TTL_SECONDS=120`
- `MOBILE_CLAIM_HEARTBEAT_SECONDS=30`
- `MOBILE_IDEMPOTENCY_TTL_SECONDS=86400`
- `MOBILE_HEADER_GRACE_MODE=true`

## Was bewusst noch nicht umgesetzt wurde

Diese Punkte wurden absichtlich nicht in Phase 1 gebaut:

- Partial Pick / Split Move
- Smart Skip mit fachlicher Recalculation
- Offline Retry Queue fuer Pick-Buchungen
- Telemetrie-DB und KPI-Auswertung
- RuFlo als Pflichtbestandteil

Der Grund ist einfach:
Diese Funktionen sind fachlich deutlich riskanter und haetten den bestehenden Picking-Flow eher instabiler gemacht.

## Wichtige Dateien der Phase-1-Aenderung

### Backend

- `backend/app/services/mobile_workflow.py`
- `backend/app/routers/pickings.py`
- `backend/app/routers/quality.py`
- `backend/app/services/picking_service.py`
- `backend/app/dependencies.py`
- `backend/app/config.py`

### PWA

- `pwa/js/api.js`
- `pwa/js/app.js`
- `pwa/js/ui.js`
- `pwa/index.html`
- `pwa/css/app.css`
- `pwa/sw.js`

### Odoo

- `odoo/addons/picking_assistant_core/`

### Tests

- `backend/tests/test_mobile_workflow_service.py`
- `backend/tests/test_mobile_routes.py`
- `backend/tests/test_picking_service.py`
- `e2e/helpers/pwa-api.js`

## Verifikation

Der Stand wurde erfolgreich geprueft mit:

- Backend-Tests: `68 passed`
- Playwright-Tests: `9 passed`
- Workflow-Contract-Check: bestanden

## Offene Hinweise

- Die Datei `n8n/workflows/n8n_quality_alert_workflow.json` ist weiterhin als Legacy im Projekt, aber nicht der massgebliche aktive Backend-Vertrag.
- Die aktiven Webhook-Workflows sind:
  - `n8n/workflows/pick-confirmed.json`
  - `n8n/workflows/quality-alert-created.json`

## Naechste sinnvolle Schritte

- Odoo-Addon wirklich installieren und einmal End-to-End gegen echtes Odoo pruefen.
- Danach erst `Grace Mode` spaeter schrittweise abschalten.
- Phase 2 nur starten, wenn Claiming und Idempotency im Lagerbetrieb stabil laufen.
