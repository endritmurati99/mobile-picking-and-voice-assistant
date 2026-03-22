# Architecture Decision Records

## ADR-001: Odoo 18 Community statt Enterprise
- **Kontext**: Enterprise-Lizenz nicht verfügbar
- **Entscheidung**: Odoo 18 Community + Custom Quality Module
- **Konsequenz**: ~3 Tage Mehraufwand für Custom Module, volle Kontrolle über Datenmodell

## ADR-002: Vosk statt Browser-SpeechRecognition
- **Kontext**: iOS Safari PWA Standalone hat defektes SpeechRecognition (WebKit Bug #215884)
- **Entscheidung**: Server-Side STT mit Vosk im Docker
- **Konsequenz**: Zusätzlicher Container (~2 GB RAM), plattformunabhängig, offline-fähig

## ADR-003: n8n nicht im Voice-Pfad
- **Kontext**: n8n-Webhook-Latenz ~40ms Baseline + sequentielle Ausführung
- **Entscheidung**: Voice-Loop direkt über App-Backend, n8n nur für Folgeaktionen
- **Konsequenz**: Einhaltung <1s Latenz-Budget, n8n bleibt Orchestrator

## ADR-004: HID-Scanner als Primär-Scan-Methode
- **Kontext**: Kamera-Scanning: ~90% Erstversuch, HID: >99.5%
- **Entscheidung**: Bluetooth-HID-Scanner primär, Touch-Fallback sekundär
- **Konsequenz**: Hardware-Kosten ~80€, deutlich höhere Zuverlässigkeit

## ADR-005: FastAPI statt Express
- **Kontext**: Odoo-Integration benötigt XML-RPC, Audio-Processing benötigt ffmpeg
- **Entscheidung**: Python/FastAPI
- **Konsequenz**: Native xmlrpc.client, einfache Vosk-Integration, async/await
