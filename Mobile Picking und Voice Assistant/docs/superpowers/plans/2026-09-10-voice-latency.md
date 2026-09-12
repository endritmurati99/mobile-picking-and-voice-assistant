# Bestehende Whisper-Spracheingabe reparieren – Implementation Plan

> **For agentic workers:** Use superpowers:subagent-driven-development to execute this plan. Follow test-driven-development and verification-before-completion.

**Goal:** Kurze deutsche Befehle im bestehenden Whisper-Small-Pfad zuverlässig verarbeiten, Fehler sichtbar machen und Aufnahme-/STT-/Aktionslatenz unterscheiden; anschließend im vorhandenen Docker-Stack testen.

**Architecture:** PWA → vorhandenes FastAPI → vorhandener Whisper-Dienst bleibt erhalten. Aufnahmeende, gültiges Audioformat und Ergebnisbehandlung werden in ihren bestehenden Modulen korrigiert. Kein neues STT-Modell, kein Cloud-Audio und kein paralleler Erkenner.

**Tech Stack:** Browser MediaRecorder/Web Audio, ES modules, Python/FastAPI/httpx/ffmpeg, Docker Compose. Für gezielte neue Regressionen Node-Standardbibliothek und Python unittest verwenden.

**Spec:** Vom Nutzer am 10.09.2026 genehmigter Vorschlag aus `/home/endri/reports/2026-09-10-deutsche-spracherkennung-mobile-picking.md`: mit dem bestehenden System anfangen, erste Korrekturen umsetzen, Docker starten und testen.

## Global Constraints

- Bestehende Echo-/TTS-/Generation- und Bestätigungsschutzregeln erhalten. Keine Aktion bei Stille, Fehlern, Negation oder veraltetem Ergebnis.
- Die maximale Aufnahmedauer von 10 Sekunden schützt Ressourcen; keine verkürzte Grenze, die normale Sätze abschneidet. Der historische 550-ms-Nachlauf ist die Ausgangsbasis.
- Keine geheimen Werte, Sitzungen oder echten Nutzeraufnahmen in Repository, Berichten oder Chat. Testaufnahmen sind ausdrücklich synthetisch.
- Keine Migration, kein Entfernen von Datenvolumes, kein Docker-Prune. Nur Backend/PWA werden für die Korrektur neu geladen.
- Keine alten Testarchive nach main zurückbringen. Kleine neue Regressionen liegen unter `infrastructure/scripts/`.
- Im isolierten Worktree arbeiten. Keine ungefragten Pushes. Der Hauptcheckout enthält fremde untracked Korrekturdateien.

## Task 1: Audiovertrag und Fehlerpfad

**Files:** Modify `backend/app/utils/audio.py`, `backend/app/services/whisper_client.py`, `backend/app/routers/voice.py`; create `infrastructure/scripts/test-voice-backend.py`.

**Interfaces:** `convert_to_wav(bytes, source_mime)` liefert echte 16-kHz-Mono-WAV-Bytes oder einen expliziten Konvertierungsfehler. `transcribe_audio(bytes, mime_type)` liefert Text/legitime Nichterkennung oder einen expliziten Dienstfehler. `/voice/recognize` übersetzt beide Fehler in verständliche Antworten und weist vollständige Phasenzeiten aus.

- [x] RED: Konvertierung ungültiger Bytes muss fehlschlagen statt dieselben Bytes zurückzugeben. Ein gültiger Browser-Container wird mit echtem ffmpeg in WAV umgewandelt; Header, Rate und Kanäle prüfen. Fehler darf keinen Whisper-Aufruf auslösen.
- [x] RED: HTTP-Fehler beim STT darf nicht zu einer scheinbar erfolgreichen stillen Nichterkennung werden. WAV-/PCM-Vertrag mit dem tatsächlich laufenden gepinnten Whisper-Loader prüfen.
- [x] GREEN: Konvertierungsfehler explizit behandeln. Gültiges WAV korrekt dekodieren lassen oder aus validiertem WAV explizit PCM16 senden; die Wahl mit dem laufenden Loader begründen. Keine rohe WebM-/MP4-Datei als WAV weitergeben.
- [x] GREEN: Fehler in `/voice/recognize` knapp und ohne interne Geheimnisse zurückgeben. Leere echte Nichterkennung bleibt `intent=unknown`. Vorhandenen No-speech-Schutz ohne Korpusbeleg nicht lockern.
- [x] GREEN: `_timing.total_ms` erst nach Intent-/Fallback-Verarbeitung setzen, deren Dauer gesondert ausweisen.
- [x] VERIFY: `python infrastructure/scripts/test-voice-backend.py` in der Backend-Laufzeit; tatsächliche WAV-/Browser-Bytes statt nur Mock-Parameter prüfen.

## Task 2: Aufnahmeende, Rückmeldung und Browserzeiten

**Files:** Modify `pwa/js/voice.js`, bei Bedarf vorhandenes `pwa/js/voice-helpers.mjs`, `pwa/js/app.js`, `pwa/sw.js`; create `infrastructure/scripts/test-voice-frontend.mjs`.

**Interfaces:** Nicht veraltete abgeschlossene Ergebnisse erreichen `_handleIntentWithRecovery`, auch bei leerem Text/Fehler. Aufnahmeberichte enthalten Modus, Aufnahmedauer und Stoppgrund; Browserberichte unterscheiden Request und Aktionsverarbeitung. Keine dauerhafte Audiospeicherung.

- [x] RED: Den vorhandenen Modulablauf in einem kleinen Node-VM-Harness mit Browser-/Audio-Grenzen ausführen. Leeres STT und Netzwerkfehler müssen die vorhandene Rückmeldung auslösen; veraltete Antworten dürfen keine Aktion auslösen.
- [x] RED: Aufnahmen mit kurzer Sprache und gleichmäßigem leiserem Hintergrund müssen nach Sprachende schließen, nicht am 10-Sekunden-Limit; Stille darf keine Bestätigung auslösen. Pause innerhalb eines Satzes unter 550 ms darf nicht abschneiden.
- [x] GREEN: Aktuell ist `getRMS` Energie aus FFT-Bins statt zeitlicher PCM-Energie. Den kleinsten nachweisbaren Detektor-Fix wählen; gegebenenfalls eine begrenzte, nachvollziehbar getestete Hintergrundanpassung im bestehenden Helper. Keine neue VAD-Bibliothek und keine Wartephase, die das erste Wort verliert. Eine nicht belegte neue Heuristik nicht als bewiesene Latenzlösung ausgeben.
- [x] GREEN: Leere Resultate und Fehler an die vorhandene Rückmeldung weiterleiten; klare Dienstfehler dürfen eine eigene kurze Meldung bekommen. TTS-Echo, Generationwechsel und Bestätigungszustand weiter berücksichtigen.
- [x] GREEN: Aufnahmezeit/Stoppgrund, Requestzeit und asynchrone Aktionsdauer im Browser messen. Kein sensibles Payload-Dump. Service-Worker-Cache von v39 auf v40 erhöhen.
- [x] VERIFY: `node infrastructure/scripts/test-voice-frontend.mjs`, Browser-Import/Syntax prüfen, beide Bedienmodi und Echo-/Abbruchschutz abdecken.

## Task 3: Docker-Vergleich und Betriebsprüfung

**Files:** Create `docs/testing/2026-09-10-voice-latency.md`; temporäre synthetische WAV/WebM/MP4-Dateien nur in einem begrenzten lokalen Audit-Verzeichnis.

- [x] BASELINE: Docker Desktop starten, alle vorhandenen Dienste/Healthchecks prüfen. Loader und Engine-Konfiguration des laufenden Whisper-Dienstes ohne Umgebungsgeheimnisse lesen.
- [x] BASELINE: Über vorhandenes lokales Piper synthetische deutsche Befehle herstellen. Mit echtem Backend-zu-Whisper-Pfad „bestätigen“, Negation und Stille prüfen; keine Aufträge buchen. Kalten und warmen Aufruf getrennt ausweisen.
- [x] REVIEW: Gesamtdiff und Regressionsergebnisse unabhängig prüfen; relevante Befunde beheben und betroffene Checks wiederholen.
- [x] DEPLOY: Geprüfte Backend-/PWA-Quellen mit einer lokalen, expliziten Compose-Override-Datei aus dem Worktree in das bestehende Projekt einbinden. Keine doppelten Datenbanken oder zusätzlichen Stacks erzeugen. Rückweg ist die unveränderte Basis-Compose-Datei.
- [x] VERIFY: Beide neuen Regressionen, vorhandener authentifizierter API-Smoke für beide Lager, echte STT-Anfragen mit WAV/WebM/MP4 und ungültigem Audio sowie PWA-Assets/Cache prüfen.
- [x] REPORT: Ergebnisse und Grenzen dokumentieren. Synthetische Audios belegen keinen echten Handy-/Lager-Feldtest. Falls dieser ohne Nutzeraufnahme nicht möglich ist, die App funktionsbereit hinterlassen und die konkrete kurze Testanleitung geben.
