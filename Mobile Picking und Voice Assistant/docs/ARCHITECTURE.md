# Architektur

## Komponentendiagramm

```
Mobile Browser (PWA)
  ↕ HTTPS (:443)
Caddy (Reverse Proxy)
  ├── /api/*    → App-Backend (FastAPI :8000)
  ├── /odoo/*   → Odoo 18 (:8069) [nur Admin]
  ├── /n8n/*    → n8n (:5678) [nur Admin]
  └── /*        → PWA Static (:80)

App-Backend
  ├── → Odoo (JSON-RPC, intern)
  ├── → Vosk (WebSocket :2700, intern)
  └── → n8n (Webhook, Fire-and-Forget)

Alle Services: Docker-Netzwerk `picking-net`
Datenbank: PostgreSQL 16 (shared, separate DBs)
```

## Datenflüsse

### Pick-Bestätigung (Scan)
1. PWA: Barcode gescannt (HID-Scanner → keydown Event)
2. PWA → Backend: `POST /api/pickings/:id/confirm-line`
3. Backend → Odoo: `execute_kw("stock.move.line", "write", ...)`
4. Backend → n8n: Webhook "pick-confirmed" (async)
5. Backend → PWA: 200 OK + nächste Zeile

### Voice-Picking
1. PWA: TTS spricht Anweisung (`SpeechSynthesis`)
2. Nutzer: Drückt PTT-Button, spricht
3. PWA: `MediaRecorder` → Audio-Blob
4. PWA → Backend: `POST /api/voice/recognize`
5. Backend → Vosk: WebSocket → Transkript
6. Backend: Intent-Engine → Aktion bestimmen
7. Backend → PWA: Intent + TTS-Text
8. PWA: TTS spricht Antwort

### Quality Alert mit Foto
1. PWA: `getUserMedia` → Kamera-Preview
2. Nutzer: Foto aufnehmen, Beschreibung eingeben
3. PWA → Backend: `POST /api/quality-alerts` (FormData mit Foto)
4. Backend → Odoo: `create` quality.alert.custom + ir.attachment
5. Backend → n8n: Webhook "quality-alert-created"
6. n8n: Benachrichtigung senden

## Entscheidungsbegründungen

| Entscheidung | Begründung |
|-------------|-----------|
| FastAPI statt Express | Native Python XML-RPC Libs für Odoo; async/await |
| Vosk statt Browser STT | iOS Safari SpeechRecognition in PWA defekt |
| HID-Scanner statt Kamera | >99.5% Leserate vs ~90% Kamera |
| n8n nicht im Voice-Pfad | Latenz: n8n ~40ms+, Voice-Budget <1000ms gesamt |
| Caddy statt Nginx | Auto-HTTPS, minimale Config, WebSocket nativ |
| Custom Module statt OCA | Weniger Abhängigkeiten, exakt zugeschnitten |
