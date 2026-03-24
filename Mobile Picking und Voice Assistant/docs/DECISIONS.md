# Architecture Decision Records

## ADR-001: Odoo 18 Community statt Enterprise
- **Kontext**: Enterprise-Lizenz nicht verfügbar
- **Entscheidung**: Odoo 18 Community + Custom Quality Module
- **Konsequenz**: ~3 Tage Mehraufwand für Custom Module, volle Kontrolle über Datenmodell

## ADR-002: Whisper statt Vosk / Browser-SpeechRecognition
- **Kontext**: iOS Safari PWA Standalone hat defektes SpeechRecognition (WebKit Bug #215884). Vosk hatte ~15-20% WER für Deutsch — zu ungenau für den Lagereinsatz.
- **Entscheidung**: Server-Side STT mit Whisper (faster_whisper, small-Modell) im Docker. Migration von Vosk am 2026-03-22.
- **Konsequenz**: Bessere Erkennungsrate (~8-10% WER), REST statt WebSocket, Backend muss WebM→WAV konvertieren (Whisper-Container hat minimales ffmpeg), ~1-2s Antwortzeit auf CPU
- **Ursprüngliche Entscheidung**: Vosk im Docker (ADR-002, ersetzt am 2026-03-22)

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
- **Konsequenz**: Native xmlrpc.client, einfache Whisper-Integration, async/await

## ADR-006: Voice-Toggle statt Push-to-Talk
- **Kontext**: Push-to-Talk erfordert dauerhaftes Halten des Buttons — unpraktisch im Lagerbetrieb mit vollen Händen. Nutzer wünscht sich "Mic einmal drücken und dann freihändig sprechen".
- **Entscheidung**: Voice-Toggle-Modus mit automatischer Silence Detection (RMS-basiert, fester Schwellwert 25, 700ms Stille-Timeout)
- **Konsequenz**: Komplexere Audio-Pipeline (Mic-Muting während TTS, setInterval-Monitor, Loop), aber deutlich bessere Usability. Legacy PTT bleibt als Fallback im Code.
