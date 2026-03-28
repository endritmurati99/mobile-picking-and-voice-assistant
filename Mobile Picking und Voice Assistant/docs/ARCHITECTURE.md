# Architektur

## Komponentendiagramm

```text
Mobile Browser (PWA)
  <-> HTTPS (:443)
Caddy (Reverse Proxy)
  |- /api/*   -> App-Backend (FastAPI :8000)
  |- /odoo/*  -> Odoo 18 (:8069) [nur Admin]
  |- /n8n/*   -> n8n (:5678) [nur Admin]
  `- /*       -> PWA Static (:80)

App-Backend
  |- -> Odoo (JSON-RPC, intern)
  |- -> Whisper (HTTP, intern)
  `- -> n8n (Async Events + Sync Exception Assist)

Alle Services: Docker-Netzwerk `picking-net`
Datenbank: PostgreSQL 16 (shared, separate DBs)
```

## Datenfluesse

### Pick-Bestaetigung (Hot Path)
1. PWA: Barcode gescannt oder Touch-Bestaetigung.
2. PWA -> Backend: `POST /api/pickings/:id/confirm-line`
3. Backend -> Odoo: Move-Line schreiben und Picking validieren.
4. Backend -> n8n: `pick-confirmed` als async Event mit Standard-Envelope.
5. Backend -> PWA: 200 OK plus naechste Zeile.

### Voice-Picking (Normaler Voice-Pfad)
1. PWA nimmt Audio auf und sendet es an `POST /api/voice/recognize`.
2. Backend transkribiert mit Whisper und matched deterministische Intents.
3. Kommandos wie `confirm`, `next`, `previous`, `done`, `pause`, `photo` bleiben komplett in FastAPI/PWA.
4. Die PWA spricht die direkte Antwort sofort aus.

### Sync Assist fuer Ausnahmefragen
1. Die PWA erkennt `unknown`, `stock_query` oder shortage-nahe Problemfragen.
2. Die PWA spricht sofort lokal: `Ich pruefe die Datenbank.`
3. PWA -> Backend: `POST /api/voice/assist`
4. Backend -> n8n: `voice-exception-query` mit Envelope, Timeout und Circuit Breaker.
5. Backend reichert den Request vorab mit Odoo-Bestandsdaten und Obsidian-Kontext an.
6. n8n fusioniert diesen Kontext, antwortet ueber `Respond to Webhook` und kann eine read-only Empfehlung zurueckgeben.
7. Backend -> PWA: `tts_text` oder FastAPI-Fallback.

### Async Replenishment bei Fehlmenge
1. FastAPI feuert `shortage-reported` nur ausserhalb des Hot Path.
2. n8n validiert die Empfehlung und ruft `POST /api/internal/n8n/replenishment-action` auf.
3. FastAPI schreibt den Nachschubauftrag kontrolliert als internen Odoo-Transfer.
4. n8n loggt den Vorfall zusaetzlich nach Obsidian.

### Quality Alert mit Foto
1. PWA erstellt einen Alert mit Foto ueber `POST /api/quality-alerts`.
2. Backend schreibt Alert und Attachments in Odoo.
3. Backend -> n8n: `quality-alert-created` als async Event.
4. n8n bewertet den Fall ueber einen produktiven V1-Agenten, fuehrt Obsidian- und E-Mail-Benachrichtigungen aus und ruft
   `POST /api/internal/n8n/quality-assessment` auf.
5. Backend schreibt die KI-Bewertung kontrolliert nach Odoo zurueck.

## Entscheidungsbegruendungen

| Entscheidung | Begruendung |
|-------------|-------------|
| FastAPI statt Express | Native Python JSON-RPC/XML-RPC Integration fuer Odoo plus gute Async-Unterstuetzung |
| Whisper statt Browser-STT | Safari/PWA-Unterstuetzung ist zu unzuverlaessig fuer den Lagereinsatz |
| HID-Scanner statt Kamera | Deutlich hoeherer Erstscan-Erfolg im operativen Betrieb |
| n8n nicht im normalen Voice-Pfad | Hot-Path-Kommandos duerfen nicht auf LLM- oder Workflow-Latenz warten |
| Sync Assist nur fuer Exceptions | Ausnahmefragen duerfen langsamer sein, brauchen aber Timeout, lokalen Zwischensatz und Fail-Fast |
| Writes nur ueber FastAPI | n8n liest aus Odoo, aber mutiert fachlichen Zustand nur ueber explizite FastAPI-Commands |
