# Bestehende Spracheingabe: Docker- und Browserprüfung, 10.09.2026

Whisper Small / faster-whisper bleibt unverändert. Die Korrektur betrifft Aufnahmeende, Audioformat, Fehlerfeedback und die Verarbeitung verspäteter Ergebnisse.

## Ergebnis

| Prüfung | Vorher | Korrigierter Stand |
|---|---|---|
| Echter Chrome-Recorder, deterministisches Testsignal mit leisem Hintergrundrauschen | 10.032 ms bis zum Erkennungscallback | 1.696 ms, davon 796 ms nach Ende des Sprach-Testsignals |
| Warme HTTP-Anfragen mit synthetischem „Bestätigen“ | Median 256 ms | Median 283 ms, drei Wiederholungen: 281/283/292 ms |
| Ungültige Audio-Bytes | HTTP 200, stilles `unknown` | HTTP 422 mit verständlicher Fehlermeldung |
| Leeres STT-Ergebnis im Chrome-Test | Wurde verworfen | Callback mit `unknown` nach 1.627 ms, vorhandene Rückmeldung wird erreicht |
| Simulierter STT-Dienstfehler im Chrome-Test | Keine Rückmeldung im Hands-free-Catch | Callback mit `error` nach 1.667 ms; separate Fehlermeldung auch im echten App-Handler sichtbar |
| Service Worker nach Schließen/Öffnen des Testtabs | v39 | Nur `picking-v40`, Worker aktiviert |

Die Browsermessung nutzt tatsächliche Web-Audio- und MediaRecorder-APIs. `getUserMedia` liefert einen generierten Stream: gleichverteiltes Rauschen ±0,01, dazu von 0,3 bis 0,9 Sekunden ein 220-Hz-Signal mit Amplitude 0,12. Nur die API-Antwort und der Aktionscallback sind ersetzt; es wird kein Auftrag gebucht. Damit ist die lange Aufnahme reproduziert, aber keine menschliche Spracherkennung oder reale Lagerakustik vermessen.

Die HTTP-Messung läuft separat über authentifizierte HTTPS-Anfragen an Caddy → FastAPI → den echten Whisper-Container. Lokales Piper erzeugt die Testwörter. Piper synthetisiert die Aufnahmen für beide Läufe neu; die HTTP-Mediane sind deshalb kein exakter A/B-Benchmark desselben Audiobytestroms. Sie zeigen, dass die vorhandene Engine bereits deutlich unter einer Sekunde antwortet. Die Browser- und HTTP-Zeiten wurden nicht als gemeinsame Ende-zu-Ende-Zeit gemessen.

## Änderungen

- `voice.js` verwendet PCM-Amplituden aus `getFloatTimeDomainData` statt Energie der frequenzabhängigen FFT-Anzeige. Der PCM-Grenzwert ist 0,02; der 550-ms-Stillenachlauf bleibt erhalten. Dauergeräusch oberhalb dieses Grenzwerts bleibt eine Grenze des einfachen Detektors. Es gibt keine neue adaptive VAD oder zusätzliches Modell.
- Nicht veraltete leere Resultate und Fehler erreichen den Rückmeldepfad. Nach Abbruch/TTS werden auch verspätete Fehler ignoriert. PTT-Sitzungen sind gegen überholte Antworten und parallel anlaufenden Mikrofonzugriff geschützt; `pointercancel` und `pointerleave` brechen ab, `pointerup` beendet normal.
- Konvertierungsfehler liefern keine ursprünglichen WebM-/MP4-Bytes mehr als angebliches WAV. Whisper dekodiert das gültige WAV mit `encode=true`; der gepinnte laufende Loader wurde dazu direkt geprüft.
- Konvertierungsfehler werden als 422, Whisper-Dienstfehler als 503 beantwortet. Echte Nichterkennung bleibt `unknown`. Der bestehende No-speech-Filter wurde nicht gelockert.
- Browserkonsole meldet Aufnahmedauer, Stoppgrund, Requestzeit und asynchrone Aktionsdauer. `_timing` enthält jetzt `intent_ms`; `total_ms` umfasst auch die Intent-/Fallback-Verarbeitung.

## Verifikation

1. `node --experimental-vm-modules infrastructure/scripts/test-voice-frontend.mjs`: bestanden. Führt das tatsächliche ES-Modul mit simulierten Browsergrenzen aus. Abgedeckt: Aufnahmeende nach Sprache und leiserem Hintergrund, Pause innerhalb eines Befehls, leeres Resultat, späte erfolgreiche/fehlgeschlagene Antworten, PTT-Abbruch, neuere PTT-Sitzung, laufender Mikrofonzugriff und kein Stoppen von Hands-free durch PTT-Abbruch.
2. `python infrastructure/scripts/test-voice-backend.py` in der Backend-Containerlaufzeit mit den neuen Quellen: bestanden, ohne übersprungene Route-Prüfungen. Echtes ffmpeg erzeugt/prüft WAV; ungültiges WebM erreicht den STT-Aufruf nicht und ergibt 422. Gültiges WAV mit simuliertem Ausfall nur an der STT-Grenze ergibt 503.
3. 14 HTTP-Proben mit echtem Whisper: „Bestätigen“, „Weiter“ und „Nicht bestätigen“ jeweils als WAV/WebM/MP4, drei weitere warme Bestätigungen, Stille und ungültiges Audio. Bestätigen → `confirm` 0,95, Weiter → `next` 0,95, Stille → `unknown`, kaputtes Audio → 422. Die Negation wird bei der synthetisch erkannten Form „Nicht bestütigen“ als bestehendes `problem` eingeordnet; sie ergibt keinen Buchungsbefehl. Das ist keine perfekte Transkription und wurde nicht als solche bewertet.
4. `make test-api` im Hauptcheckout gegen den aktualisierten Betrieb: bestanden für beide Lager. Liest Aufträge, ohne sie zu buchen.
5. Alle elf Dienste laufen; sämtliche definierten Healthchecks sind grün.
6. HTTPS-ausgelieferte `voice.js`, `voice-helpers.mjs`, `app.js` und `sw.js` stimmen bytegenau mit dem Test-Worktree überein; alle vorzuladenden PWA-Assets liefern HTTP 200.
7. Unabhängige Codeprüfung: zwei Abbruch-Rennen gefunden, korrigiert und bei der gezielten Nachprüfung bestätigt. `git -c core.whitespace=cr-at-eol diff --check` ist sauber; vorhandene CRLF-Konvention bleibt erhalten.

## Testbetrieb und Rückweg

Branch: `fix/voice-latency-2026-09-10`. Worktree: `/mnt/c/Users/endri/Desktop/Bachelor/.worktrees/voice-latency`.

Der Hauptcheckout bleibt auf dem bisherigen Main. Backend und PWA des **bestehenden** Compose-Projekts lesen ihre Quellen für den Feldtest aus dem Worktree. Es wurden keine zusätzlichen Datenbanken, Netzwerke oder Modelle erzeugt und keine Datenvolumes verändert. Die lokale Override-Datei liegt außerhalb des Repositorys:

`C:/Users/endri/AppData/Local/Temp/pwr-voice-20260910/compose.voice.yml`

Teststand erneut starten, aus dem Anwendungsverzeichnis des Hauptcheckouts:

```bash
docker compose -f docker-compose.yml -f /mnt/c/Users/endri/AppData/Local/Temp/pwr-voice-20260910/compose.voice.yml up -d --no-deps --wait backend pwa
```

Zum bisherigen Main zurückkehren:

```bash
docker compose -f docker-compose.yml up -d --no-deps --wait backend pwa
```

Auch ein normales `make up` im unveränderten Hauptcheckout stellt dessen Quell-Mounts wieder her. Den Worktree deshalb während dieses Testbetriebs erhalten. Es wurde nichts nach GitHub gepusht oder in Main gemergt.

## Nächster Feldtest

PWA vollständig schließen und wieder öffnen. Im üblichen Mikrofonabstand jeweils „bestätigen“, „weiter“, „nicht bestätigen“ und einen Mengenbefehl ausprobieren, zuerst in Ruhe, dann mit den üblichen Geräuschen. Dauerhaften Sprachmodus und gedrückte Mikrofontaste getrennt prüfen. Für erste echte Buchungen ausschließlich einen ausdrücklich markierten Testauftrag verwenden. Bei Verzögerungen zeigen Aufnahme-Stoppgrund und Phasenzeiten, ob Aufnahme, STT oder Buchung wartet.

Die automatische Prüfung lief im Desktop-Chrome über `https://localhost`. Das vorhandene Zertifikat enthält `localhost` und die alte IP `172.22.146.40`, nicht die derzeit konfigurierte IP `172.26.8.176`; beim direkten IP-Zugriff zeigte Chrome daher einen Zertifikatsfehler. Zertifikate, Trust Stores und LAN-Konfiguration wurden in diesem Audiofix nicht verändert. Ein Test auf dem echten Handy benötigt dessen tatsächlich verwendete, korrekt abgesicherte Adresse.

Lokale, nicht eingecheckte Nachweise: `/home/endri/audits/voice-20260910/` und `/home/endri/audits/voice-20260910-implementation.md`. Dort liegen nur synthetische Testresultate und Testskripte, keine Anmeldedaten oder Nutzeraufnahmen.
