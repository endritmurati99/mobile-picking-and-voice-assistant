# Architecture Decision Records

## ADR-001: Odoo 18 Community statt Enterprise
- **Kontext**: Enterprise-Lizenz war nicht verfuegbar.
- **Entscheidung**: Odoo 18 Community plus Custom Modules.
- **Konsequenz**: Etwas mehr Eigenbau, dafuer volle Kontrolle ueber Datenmodell und Schnittstellen.

## ADR-002: Whisper statt Browser-SpeechRecognition / Vosk
- **Kontext**: Browser-STT in iOS PWAs ist zu unzuverlaessig, Vosk war fuer Deutsch im Lagerkontext nicht treffsicher genug.
- **Entscheidung**: Server-side STT mit Whisper.
- **Konsequenz**: Bessere Erkennung, dafuer etwas mehr Latenz und Audio-Konvertierung im Backend.

## ADR-003: n8n nicht im normalen Voice-Pfad
- **Kontext**: Der Picker darf fuer `confirm`, `next`, `done` und andere Standardkommandos nie auf LLM- oder Workflow-Latenz warten.
- **Entscheidung**: Der normale Voice-Loop bleibt komplett im App-Backend. n8n ist nur fuer einen separaten Exception-Assist-Pfad erlaubt (`/api/voice/assist`) und bleibt dort read-only.
- **Konsequenz**: Hot Path bleibt deterministisch und schnell. Ausnahmefragen koennen langsamer sein, sind aber mit lokalem Zwischensatz, Timeout und Circuit Breaker abgesichert.

## ADR-004: HID-Scanner als Primaer-Scan-Methode
- **Kontext**: Kamera-Scanning war im Vergleich zu HID-Scannern weniger robust.
- **Entscheidung**: Bluetooth-HID-Scanner sind Primaerpfad, Kamera und Touch bleiben Fallbacks.
- **Konsequenz**: Hoehere Zuverlaessigkeit im Betrieb bei etwas mehr Hardware-Aufwand.

## ADR-005: FastAPI als Command Gatekeeper
- **Kontext**: n8n soll direkt aus Odoo lesen koennen, aber nicht unkontrolliert den fachlichen Zustand mutieren.
- **Entscheidung**: Operative Writes nach Odoo laufen ausschliesslich ueber FastAPI-Commands.
- **Konsequenz**: Es gibt genau einen kontrollierten Schreibpfad fuer Quality Assessments, Replenishment-Folgeaktionen und spaetere AI-Kommandos.

## ADR-006: Circuit Breaker fuer den Sync-Assist-Pfad
- **Kontext**: Ein abgestuerzter oder langsamer n8n-Container darf den Picker nicht bei jeder Ausnahmefrage erneut ausbremsen.
- **Entscheidung**: `request_reply()` oeffnet nach drei Fehlversuchen einen In-Memory-Circuit-Breaker fuer 60 Sekunden.
- **Konsequenz**: Folgeanfragen schlagen waehrend dieser Zeit sofort auf den FastAPI-Fallback um und halten den Voice-Flow stabil.
