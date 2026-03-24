---
title: Phase 4 - Voice Picking
tags:
  - phase
  - voice
  - stt
  - whisper
status: in-progress
---

# Phase 4 — Voice Picking (Whisper STT)

> [!success] Migration: Vosk → Whisper abgeschlossen (2026-03-22)
> STT wurde von Vosk (WebSocket, Kaldi) auf Whisper (REST, faster_whisper small) umgestellt.
> Voice-Modus wurde von Push-to-Talk auf Voice-Toggle umgestellt.
> **Voraussetzung:** [[Phase 3 - Barcode Scanning]] ✅ abgeschlossen.

Überblick: [[00 - Projekt Übersicht]] | Voice-Architektur: [[Voice Intent Engine]] | PWA-Details: [[PWA Implementierungshinweise]] | Nächste Phase: [[Phase 5 - n8n Orchestrierung]]

---

## Ziel dieser Phase

Voice-Picking als vollständiger Workflow mit kontinuierlichem Voice-Toggle-Modus:
```
Mic-Button/Taste M → Voice-Modus aktiv → Sprache → Stille → Whisper → Intent → TTS → Loop
```

Touch bleibt immer Fallback — Voice ist Enhancement, nicht Pflicht.

---

## Was implementiert ist

| Komponente | Datei | Status |
| ---------- | ----- | ------ |
| ~~Vosk STT Client~~ | ~~`backend/app/services/vosk_client.py`~~ | ❌ Ersetzt durch Whisper |
| Whisper STT Client | `backend/app/services/whisper_client.py` | ✅ Implementiert |
| Audio-Konvertierung (WebM→WAV) | `backend/app/utils/audio.py` | ✅ Implementiert |
| Intent Engine | `backend/app/services/intent_engine.py` | ✅ Implementiert |
| Voice Router | `backend/app/routers/voice.py` | ✅ Aktualisiert für Whisper |
| TTS (Browser) | `pwa/js/voice.js:speak()` | ✅ Mit Mic-Muting |
| Voice Toggle Mode | `pwa/js/voice.js:toggleVoiceMode()` | ✅ Implementiert |
| Silence Detection | `pwa/js/voice.js:startListeningCycle()` | ✅ RMS-basiert |
| TTS Feedback-Loop-Schutz | `pwa/js/voice.js:muteMic()` | ✅ Implementiert |
| Keyboard-Shortcut (M) | `pwa/js/app.js` | ✅ Mit repeat-Guard |
| Legacy PTT | `pwa/js/voice.js:startRecording/stopRecording` | ✅ Noch vorhanden als Fallback |

---

## Whisper Setup

**Docker-Compose:**
```yaml
whisper:
  image: onerahmet/openai-whisper-asr-webservice:latest
  restart: unless-stopped
  environment:
    ASR_MODEL: small
    ASR_ENGINE: faster_whisper
  networks:
    - picking-net
```

**Backend-Config:**
```python
whisper_url: str = "http://whisper:9000"
```

> [!warning] Whisper Startup-Zeit
> Whisper braucht beim ersten Start Zeit um das Modell herunterzuladen und zu laden.
> Voice-Tests erst starten nach:
> ```bash
> docker compose logs whisper | grep "Application startup complete"
> ```

### Setup-Checkliste

- [x] `docker compose logs whisper` — Container läuft
- [x] Whisper REST-API erreichbar: `http://whisper:9000/asr`
- [x] Backend kann Whisper erreichen (intern über Docker-Network)
- [x] WebM→WAV-Konvertierung funktioniert (ffmpeg im Backend-Container)

---

## Vosk → Whisper Migration (2026-03-22)

### Was geändert wurde

| Datei | Änderung |
| ----- | -------- |
| `docker-compose.yml` | `vosk` Service ersetzt durch `whisper` Service |
| `backend/app/config.py` | `vosk_url` → `whisper_url` |
| `backend/app/services/whisper_client.py` | Neu: REST-Client für Whisper API |
| `backend/app/routers/voice.py` | Import von `vosk_client` → `whisper_client`, WAV-Konvertierung hinzugefügt |
| `pwa/js/voice.js` | Komplett überarbeitet: PTT → Voice Toggle mit Silence Detection |
| `pwa/js/app.js` | PTT-Callbacks → Voice Toggle, M-Taste, Intent-Handler |

### Warum Whisper statt Vosk

| Aspekt | Vosk | Whisper (faster_whisper small) |
| ------ | ---- | ------------------------------ |
| WER (Deutsch) | ~15-20% | ~8-10% |
| Protokoll | WebSocket | REST API |
| Antwortzeit (CPU) | ~0.5-1s | ~1-2s |
| Natürlichkeit | Nur Keyword-Matching | Versteht freiere Sprache |
| Docker RAM | ~2 GB | ~1-2 GB |

### Probleme bei der Migration

1. **Whisper `medium` auf CPU: Timeout >2min** → Lösung: `ASR_ENGINE: faster_whisper` + `ASR_MODEL: small`
2. **Whisper-Container kann WebM nicht dekodieren** (ffmpeg `--disable-autodetect`) → Lösung: Backend konvertiert WebM→WAV vor dem Senden
3. **requestAnimationFrame unzuverlässig** für Audio-Monitoring → Lösung: `setInterval(30ms)`
4. **Silence Detection Threshold zu niedrig** (15, Rauschen bei 17-33) → Lösung: Fester Schwellwert 25
5. **Kalibrierung durch TTS korrumpiert** (TTS-Audio als Noise Floor gemessen) → Lösung: Kalibrierung entfernt, fester Schwellwert
6. **Wortanfänge verloren** (Recording erst nach Speech-Detection) → Lösung: Recording sofort starten, Monitor parallel
7. **TTS Feedback-Loop** (Mikrofon nahm TTS-Output auf) → Lösung: `track.enabled = false` während TTS
8. **M-Taste Repeat** (Gedrückthalten toggled an/aus/an/aus) → Lösung: `e.repeat` Guard

---

## Voice-Toggle-Modus

### Bedienung

| Aktion | Effekt |
| ------ | ------ |
| Mic-Button klicken | Voice-Modus ein/aus (Toggle) |
| Taste **M** drücken | Voice-Modus ein/aus (Toggle) |
| Sprechen + Pause | Audio wird automatisch an Whisper gesendet |
| TTS spricht | Mikrofon automatisch stumm → kein Feedback-Loop |
| TTS fertig | Mikrofon wieder aktiv → nächster Aufnahme-Zyklus |

### Technische Parameter

| Parameter | Wert | Zweck |
| --------- | ---- | ----- |
| `SPEECH_RMS` | 25 | Sprach-Schwellwert (Rauschen: 5-15) |
| `SILENCE_AFTER_SPEECH` | 700ms | Stille nach Sprache → senden |
| `NO_SPEECH_TIMEOUT` | 6000ms | Keine Sprache → Zyklus neu starten |
| `MIN_SPEECH_MS` | 150ms | Mindest-Sprechdauer |
| `MAX_RECORDING_MS` | 10000ms | Sicherheits-Timeout |
| `CHECK_MS` | 30ms | Monitor-Intervall |

---

## Test-Szenarien

### Whisper-Verbindungstest

```bash
# Direkt über Backend testen:
curl -k -X POST https://localhost/api/voice/recognize \
  -F "audio=@test.wav" \
  -F "context=awaiting_command"
# → {"text": "...", "intent": "...", "value": null, "confidence": 0.9}
```

### Intent-Engine Unit Tests

```bash
cd backend
python -m pytest tests/test_intent_engine.py -v
```

Getestete Intents:

| Sprachbefehl | Kontext | Erwarteter Intent |
| ------------ | ------- | ----------------- |
| "bestätigt" | `awaiting_command` | `confirm` |
| "nächster" | `awaiting_command` | `next` |
| "problem" | `awaiting_command` | `problem` |
| "vier sieben" | `awaiting_location_check` | `check_digit` (value=4) |
| "fünf" | `awaiting_quantity_confirm` | `quantity` (value=5) |
| "5" | `awaiting_quantity_confirm` | `quantity` (value=5) |
| "wiederholen" | `awaiting_command` | `repeat` |
| "fertig" | `awaiting_command` | `done` |

### Voice-Toggle End-to-End

```
1. Mic-Button klicken oder Taste M drücken
2. Voice-Modus ist aktiv (Mic-Icon wechselt)
3. Sprechen: "bestätigt"
4. ~700ms Stille → Audio wird gesendet
5. Backend: WebM → WAV → Whisper → "bestätigt"
6. Intent: {action: "confirm", confidence: 0.9}
7. PWA: Pick-Zeile wird bestätigt
8. TTS: "Bestätigt. Nächster Artikel: ..." (Mikrofon stumm)
9. TTS fertig → Mikrofon wieder aktiv → nächster Zyklus
```

---

## Sprachbefehle (Referenz)

| Kontext | Befehl | Intent | Aktion |
| ------- | ------ | ------ | ------ |
| Standort-Check | Prüfziffer (z.B. "vier sieben") | `check_digit` | Standort bestätigen |
| Standort-Check | "Wiederholen" | `repeat` | Standort nochmal ansagen |
| Menge | "Bestätigt" | `confirm` | Bedarfsmenge übernehmen |
| Menge | Zahl (z.B. "fünf") | `quantity` | Abweichende Menge setzen |
| Allgemein | "Nächster" | `next` | Nächster Pick-Schritt |
| Allgemein | "Zurück" | `previous` | Vorheriger Schritt |
| Allgemein | "Problem" | `problem` | Quality Alert starten |
| Allgemein | "Foto" | `photo` | Kamera öffnen |
| Allgemein | "Fertig" | `done` | Picking abschließen |
| Allgemein | "Hilfe" | `help` | Befehle ansagen |

---

## Audio-Format-Kompatibilität

| Plattform | Browser-Format | Backend-Konvertierung | An Whisper |
| --------- | -------------- | -------------------- | ---------- |
| iOS Safari | `audio/mp4` (AAC) | mp4 → WAV (ffmpeg) | WAV |
| Chrome Android | `audio/webm;codecs=opus` | WebM → WAV (ffmpeg) | WAV |
| Chrome Desktop | `audio/webm;codecs=opus` | WebM → WAV (ffmpeg) | WAV |

> [!info] Warum immer WAV-Konvertierung?
> Der Whisper-Container (`onerahmet/openai-whisper-asr-webservice`) hat ein minimales ffmpeg
> das mit `--disable-autodetect` gebaut wurde und WebM/Opus nicht dekodieren kann.
> Deshalb konvertiert das Backend **immer** zu WAV bevor es an Whisper gesendet wird.

---

## PWA-Tests auf Mobile

### iOS Safari

- [ ] Mikrofon-Permission erscheint beim ersten Mic-Button-Klick
- [ ] Voice-Toggle aktiviert/deaktiviert korrekt
- [ ] Audio-Upload zu Backend → Whisper → Intent
- [ ] TTS spricht auf Deutsch (`utterance.lang = 'de-DE'`)
- [ ] TTS funktioniert in PWA-Standalone-Modus
- [ ] Mikrofon stumm während TTS (kein Feedback-Loop)
- [ ] Touch-Fallback erscheint wenn Whisper nicht antwortet

### Android Chrome

- [ ] Mikrofon-Permission erscheint
- [ ] `audio/webm;codecs=opus` wird als Format erkannt
- [ ] Intent-Erkennung für deutsche Befehle
- [ ] TTS Deutsch funktioniert
- [ ] Voice-Toggle-Loop funktioniert kontinuierlich

---

## Bekannte Probleme

> [!warning] Performance: Round-Trip könnte schneller sein
> Gesamtzeit von Sprach-Ende bis Intent-Ausführung: ~2-4s
> (700ms Stille-Erkennung + ~1-2s Whisper + Netzwerk-Overhead)
> Funktioniert, aber Nutzer wünscht sich schnellere Reaktion.
> Mögliche Optimierungen: kürzere Stille-Schwelle, Whisper `tiny`, Audio-Streaming.

> [!bug] M-Taste: Voice-Modus bleibt aktiv bei versteckten Buttons
> Wenn der Voice-Modus per M-Taste aktiviert wird, bleibt er aktiv auch wenn
> der Mic-Button bei einem Seitenwechsel nicht mehr sichtbar ist.
> → Lösung nötig: Voice-Modus an Navigation koppeln oder permanenten Indikator zeigen.

> [!bug] iOS TTS + Mikrofon Interferenz
> TTS und Mikrofon können auf iOS interferieren.
> Aktuell: Mikrofon wird via `track.enabled = false` stummgeschaltet während TTS.
> Muss auf iOS getestet werden.

---

## Go/No-Go Checkliste

| Kriterium | Status |
| --------- | ------ |
| Whisper antwortet auf REST-API | ✅ |
| `POST /api/voice/recognize` → Transkription | ✅ |
| Intent "bestätigt" → Pick-Zeile bestätigt | ✅ |
| Voice-Toggle-Modus aktiviert/deaktiviert | ✅ |
| Automatische Silence Detection | ✅ |
| TTS-Feedback-Loop verhindert | ✅ |
| M-Taste Toggle mit repeat-Guard | ✅ |
| Intent "problem" → Quality Alert öffnet | ☐ |
| TTS spricht Pick-Anweisung (iOS + Android) | ☐ |
| Vollständiger Voice-Loop ohne Touch | ✅ (Desktop) |
| Mobile Test (iOS + Android) | ☐ |

---

## Weiterführend

- [[Voice Intent Engine]] — Detaillierter Datenfluss, Intent-Patterns, PickingContext-Zustände
- [[PWA Implementierungshinweise]] — iOS Safari Einschränkungen für Audio/Mikrofon
- [[API Dokumentation]] — `/api/voice/recognize` Endpoint-Spezifikation
- [[Phase 3 - Barcode Scanning]] — Voice als Enhancement zu Barcode-Scanning
- [[Phase 5 - n8n Orchestrierung]] — n8n-Webhooks nach Voice-Events
