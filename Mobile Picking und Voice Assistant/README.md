# Mobile Picking und Voice Assistant

Aktueller Projektstand fuer die Bachelorarbeit: mobile Picking-PWA mit FastAPI-Backend, Odoo als System of Record und n8n fuer Benachrichtigungen, Vision-Workflows und synchrone Ausnahmeassistenz.

Diese README dokumentiert den aktuellen Stand nach:

- Phase 1 "Transaktionshaertung"
- Redesign v1 "Odoo-Hybrid Dark UI"
- Kontext-Slice v1 "Menschlicher Modellname aus Odoo"

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
- n8n ist jetzt in zwei Bahnen angebunden:
  - async fuer Events wie `quality-alert-created` und `pick-confirmed`
  - sync nur fuer Ausnahmefragen ueber `POST /api/voice/assist`
- Die PWA zeigt jetzt operative Informationen zuerst: Produkt, Platz, Menge und Fortschritt statt nur technischer Odoo-Referenzen.
- Wenn auf einem Picking ein Modellkontext gepflegt ist, zeigt die PWA jetzt zusaetzlich einen menschlichen Modellnamen wie `LEGO Ente`.

## Was in Phase 1 neu umgesetzt wurde

### 1. Picker-Identitaet

- Die PWA laedt aktive Odoo-Benutzer ueber `GET /api/pickers`.
- Beim Start oder Reload muss der Nutzer zuerst ein Profil auswaehlen.
- Der aktive Picker lebt nur in der laufenden Session und wird nicht ueber Reloads wiederhergestellt.
- Zusaetzlich bekommt jedes Geraet eine persistente lokale `device_id`.
- Der Picker-Katalog wird lokal gecacht, damit die Profilauswahl auch bei schlechtem Netz sichtbar bleibt.

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

### 5. Erweiterte n8n-Envelope-Standards

- Alle ausgehenden n8n-Calls tragen jetzt einen gemeinsamen Envelope mit:
  - `event_name`
  - `schema_version`
  - `correlation_id`
  - `occurred_at`
  - `picker`
  - `device_id`
  - `picking_context`
  - `payload`
- `pick-confirmed`, `quality-alert-created` und `shortage-reported` nutzen diesen Envelope asynchron.
- `voice-exception-query` nutzt denselben Envelope synchron fuer Ausnahmefragen.

### 6. CQRS Slice fuer n8n

- Neuer Sync-Assist-Endpunkt: `POST /api/voice/assist`
- Neue interne n8n-Command-Endpunkte:
  - `POST /api/internal/n8n/quality-assessment`
  - `POST /api/internal/n8n/replenishment-action`
- n8n darf Odoo direkt lesen, aber kritische Writes nur ueber diese FastAPI-Endpunkte zurueckgeben.
- Synchrone Assist-Calls sind durch Timeout und Circuit Breaker abgesichert.
- Fehlmengen koennen jetzt ueber `shortage-reported` einen echten internen Nachschubtransfer in Odoo anlegen.
- Quality Alerts schreiben ihre AI-Bewertung kontrolliert zurueck und loggen zusaetzlich nach Obsidian.

## Was in Redesign v1 neu umgesetzt wurde

### 1. Odoo-Hybrid Dark UI mit festen Design-Tokens

- Die PWA bleibt im Dark Mode.
- Farben sind jetzt semantisch an Odoo angelehnt:
  - `primary` = Odoo Purple
  - `success` = Odoo Teal
  - `warning` = Amber
  - `danger` = Error Crimson
- Harte Einzel-Farben im Hauptlayout wurden auf zentrale CSS-Tokens umgestellt.
- Es gibt jetzt einen manuellen `High Contrast`-Modus im Header.

### 2. Neuer Header als Command Center

- Oben links: App-Titel plus offener Aufgaben-Counter
- Mitte: lokale Suche nach
  - Referenz
  - Produktname
  - SKU
  - Platz
  - Partner/Firma
- Rechts:
  - aktiver Picker
  - Online-/Sync-Status
  - High-Contrast-Toggle
- Darunter:
  - Filter-Chips fuer `Alle`
  - `Dringend`
  - `Mein Bereich`

### 3. Neuer Listenaufbau fuer Pickings

- Jede Karte zeigt jetzt:
  - Odoo-Referenz klein
  - Typ-/Prioritaets-Badges
  - Produktvorschau gross
  - Menge bzw. offene Positionen
  - naechsten Platz in einer kontrastreichen Box
  - Fortschrittsbalken
- Die Liste nutzt zusaetzliche Backend-Felder:
  - `primary_item_sku`
  - `total_line_count`
  - `completed_line_count`
  - `progress_ratio`
  - `primary_zone_key`

### 4. Lokaler Bereichsfilter `Mein Bereich`

- `Mein Bereich` ist in v1 bewusst **kein** echtes Odoo-Bereichsmodell.
- Stattdessen waehlst du lokal einen bevorzugten Zonen-/Bereichsschluessel aus den aktuell geladenen Pickings.
- Die Auswahl wird lokal gespeichert.
- Danach zeigt der Filter nur Auftraege, deren naechster Halt in diesem Bereich liegt.

### 5. Detailansicht mit staerkerem Fokus

- In der Detailansicht sind jetzt visuell priorisiert:
  - Platz
  - Produkt
  - Menge
  - Fortschritt
- Die Odoo-Referenz bleibt sichtbar, ist aber nur noch sekundaer.
- Die bestehende Route-Hinweis-Logik bleibt erhalten.
- Der bestehende Guided-Flow, Claiming und Voice-Interlock bleiben fachlich unveraendert.

### 6. Additive Backend-Erweiterungen fuer die UI

- `GET /api/pickings` liefert jetzt zusaetzlich:
  - `primary_item_sku`
  - `total_line_count`
  - `completed_line_count`
  - `progress_ratio`
  - `primary_zone_key`
- `GET /api/pickings/{id}` liefert auf Move-Line-Ebene jetzt zusaetzlich:
  - `product_sku`

## Was im Kontext-Slice v1 neu umgesetzt wurde

### 1. Menschlicher Modellkontext direkt aus `Source Document`

- Das Backend nutzt jetzt das vorhandene Odoo-Feld `origin` (`Source Document`) auf `stock.picking`.
- Beispiel:
  - Odoo: `[324876] Papagei Moritz (BOM 324876)`
  - PWA-Titel: `Papagei Moritz`
- Es gibt dafuer keinen manuellen Pflege-Schritt mehr im normalen Flow.

### 2. Additive API-Felder fuer Fachkontext

- `GET /api/pickings` liefert jetzt zusaetzlich:
  - `kit_name`
  - `has_human_context`
- `GET /api/pickings/{id}` liefert jetzt zusaetzlich:
  - `kit_name`
  - `voice_intro`
  - `has_human_context`

### 3. Sichtbare PWA-Aenderungen

- In der Liste wird `kit_name` zum Primaersignal, wenn aus `Source Document` ein menschlicher Name ableitbar ist.
- Die technische Referenz bleibt sichtbar, ist aber sekundaer.
- In der Detailansicht erscheint oberhalb der operativen Pick-Infos jetzt ein Modellkontext-Block.
- Beim Oeffnen eines Pickings spricht der Assistent zuerst `voice_intro`, falls aus `Source Document` ein Kontextname abgeleitet wurde.
- Ohne brauchbaren Kontext im `Source Document` bleibt die bisherige Anzeige und der bisherige operative Voice-Prompt aktiv.

## Was du jetzt sichtbar in der PWA sehen solltest

- Vor der Liste erscheint jetzt zuerst eine verpflichtende Profilauswahl.
- Im Header gibt es danach einen kompakten Picker-Indikator.
- Im Header gibt es jetzt auch:
  - einen Aufgaben-Counter
  - eine lokale Suche
  - Filter-Chips
  - einen `High Contrast`-Schalter
- Auf Mobile zeigt der Picker-Indikator vor der Auswahl ein `+` und danach die Initialen des gewaehlten Odoo-Benutzers.
- Wenn zwei Geraete dasselbe Picking oeffnen wollen, sieht das zweite Geraet eine Claim-Konflikt-Ansicht.
- In der Liste siehst du jetzt pro Karte:
  - Modellname gross, falls gepflegt
  - sonst wie bisher die Produktvorschau gross
  - Referenz klein
  - Platzbox
  - Fortschritt
- In der Detailansicht steht der Platz jetzt visuell vor der Referenz.
- Falls ein Modellkontext gepflegt wurde, siehst du in der Detailansicht zusaetzlich den Modellnamen ueber dem operativen Pick.

Wichtig:
Der groesste Teil der Phase-1-Aenderung war absichtlich nicht "fancy UI", sondern Transaktionsschutz im Hintergrund. Das Redesign v1 baut jetzt sichtbar darauf auf, ohne den Picking-Flow fachlich zu aendern.

## Wie du den neuen Stand benutzt

### Normaler Picking-Flow

1. PWA starten.
2. Profil auswaehlen.
3. Optional im Header:
   - suchen
   - auf `Dringend` filtern
   - `Mein Bereich` setzen
   - `High Contrast` einschalten
4. Ein Picking aus der Liste oeffnen.
5. Das Picking wird automatisch geclaimt.
6. Positionen wie bisher bestaetigen.
7. Beim Abschluss oder beim Zurueckgehen wird der Claim freigegeben.

### Lokale Suche

- Suche im Header filtert direkt die bereits geladenen Pickings.
- Es wird **keine** neue serverseitige Such-API verwendet.
- Treffer funktionieren aktuell ueber:
  - Referenz
  - Produkt
  - SKU
  - Platz
  - Partner

### Filter `Mein Bereich`

1. In der Liste auf `Mein Bereich` tippen.
2. Einen vorgeschlagenen Bereich aus den aktuellen Pickings waehlen.
3. Die Auswahl wird lokal gespeichert.
4. Danach zeigt die Liste nur noch Pickings fuer diesen Bereich.

### High Contrast

- Der Schalter `Kontrast` im Header aktiviert den helleren Kontrastmodus.
- Die Einstellung wird lokal gespeichert.

### Picker wechseln

1. Auf den Picker-Indikator im Header tippen.
2. Die laufende Session wird lokal hart zurueckgesetzt.
3. Danach erscheint wieder die Profilauswahl.

### Offline-Profilauswahl

- `GET /api/pickers` wird lokal gecacht.
- Bei schlechtem oder fehlendem Netz rendert die PWA zuerst den letzten bekannten Picker-Katalog aus dem Cache.
- Nur wenn kein Cache vorhanden ist und das Netz fehlt, erscheint eine dedizierte Offline-/Retry-Ansicht.

### Device-ID und Session

- `device_id` liegt dauerhaft im `localStorage` und ueberlebt Reloads.
- Der aktive Picker wird **nicht** persistent gespeichert.
- Deshalb startet die App nach Reload oder Browser-Neustart immer wieder in der Profilauswahl.

### Claim-Konflikt

Wenn ein Picking bereits aktiv von jemand anderem bearbeitet wird:

- du kannst es nicht parallel bearbeiten
- die PWA zeigt, wer es gerade blockiert
- du kannst spaeter erneut pruefen oder zur Liste zurueckgehen

## Backend- und Header-Verhalten

Die PWA sendet bei Picking-Reads jetzt:

- `X-Picker-User-Id`

Die PWA sendet bei Write-Requests automatisch:

- `Idempotency-Key`
- `X-Picker-User-Id`
- `X-Device-Id`

Damit funktionieren Claiming, Replay-Schutz und echte Picker-Zuordnung.

Serverseitig gilt jetzt:

- `GET /api/pickers` bleibt ohne Picker-Header erlaubt.
- Picking-Reads ohne gueltige `X-Picker-User-Id` liefern hart `400` oder `403`.
- Mutierende Picking-/Quality-Endpunkte ohne vollstaendige `X-Picker-User-Id` und `X-Device-Id` liefern hart `400`.
- Es gibt keinen stillen Fallback auf `Administrator`.

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

## Was bewusst noch nicht umgesetzt wurde

Diese Punkte wurden absichtlich nicht in Phase 1 gebaut:

- Partial Pick / Split Move
- Smart Skip mit fachlicher Recalculation
- Offline Retry Queue fuer Pick-Buchungen
- Telemetrie-DB und KPI-Auswertung
- RuFlo als Pflichtbestandteil
- echte Odoo-Produktbilder
- serverseitige Suche
- Batterie-/Sensor-getriebener Theme-Switch
- Motion-/Feedback-v2:
  - Zoom-Transition
  - Voice-Wellenanzeige
  - Fullscreen-Green-Flash
  - Ping-Sound

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
- `pwa/js/scanner.js`
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

- Backend-Tests: `58 passed`
- Playwright-Tests: `11 passed`
- Voice-Helper-Tests: `9 passed`

## Offene Hinweise

- Die Datei `n8n/workflows/n8n_quality_alert_workflow.json` ist weiterhin als Legacy im Projekt, aber nicht der massgebliche aktive Backend-Vertrag.
- Die aktiven Webhook-Workflows sind:
  - `n8n/workflows/pick-confirmed.json`
  - `n8n/workflows/quality-alert-created.json`
  - `n8n/workflows/voice-exception-query.json`
  - `n8n/workflows/shortage-reported.json`

## Naechste sinnvolle Schritte

- Odoo-Addon wirklich installieren und einmal End-to-End gegen echtes Odoo pruefen.
- Danach erst `Grace Mode` spaeter schrittweise abschalten.
- Phase 2 nur starten, wenn Claiming und Idempotency im Lagerbetrieb stabil laufen.
