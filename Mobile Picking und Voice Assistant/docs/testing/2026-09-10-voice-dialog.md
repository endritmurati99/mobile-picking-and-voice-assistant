# Sprachdialog: Piper, Bestätigung und kurze Befehle

Der genehmigte Folgeschritt zum echten Mikrofontest ist umgesetzt. Der
bestehende Whisper-Small-Dienst bleibt erhalten.

- Jeder nichtleere Sprechtext versucht Piper, auch kurze Rückfragen und
  Quittungen. Bei einem Fehler bleibt Browser-TTS als Fallback verfügbar;
  ein späterer Prompt versucht Piper erneut.
- Abbruch beendet laufende Piper-Anfragen und Audio-Wiedergaben. Verspätete
  Abschlusscallbacks verändern keinen neueren Sprach-/Mikrofonzustand.
- Buchungsrückfragen stehen dauerhaft mit Ja/Nein-Schaltflächen außerhalb der
  wechselnden Positionsansicht. Während der Buchung zeigen sie den Fortschritt.
- Einzel- und Sammelbuchung verwenden dieselbe Ausschlusssperre. Scans und
  weitere Sprachbefehle starten währenddessen keine konkurrierende Buchung.
  Chargen-/Seriennummerdialoge bleiben bedienbar.
- Rückfragen sind an Auftrag, Position und Ansicht gebunden. Ein verspätetes
  „Ja“ nach Ablauf bucht nicht; ein neuer expliziter Einzelbefehl öffnet eine
  neue Rückfrage. Negation hat weiterhin Vorrang.
- Die App entscheidet über Buchungsbestätigungen; die vorgelagerte generische
  Sprach-Rückfrage fragt bei Schreibbefehlen nicht zusätzlich nach.
- `/voice/recognize` verwendet deterministische Regeln und Segmentprüfung.
  Unklare kurze Befehle warten nicht mehr auf den viersekündigen LLM-Fallback.
  `/voice/assist` bleibt unverändert.
- Browserdiagnostik protokolliert Piper/Browser, Vorbereitung/Wiedergabe und
  Aufnahme-/Requestphasen; das Backend protokolliert Konvertierung, STT,
  Intent und Gesamtzeit. Die neuen Browserlogs enthalten keine Sprechtexte.

## Verifikation

```bash
node --experimental-vm-modules infrastructure/scripts/test-voice-frontend.mjs
node --experimental-vm-modules infrastructure/scripts/test-voice-actions.mjs
python infrastructure/scripts/test-voice-backend.py
```

Alle bestanden. Der Backend-Test wurde zusätzlich in der Docker-Laufzeit mit
echtem ffmpeg ausgeführt, einschließlich 422/503 und schneller unbekannter,
klarer und negierter Befehle. Der neue UI-Test scheiterte vorher an der
fehlenden dauerhaften Rückfrage. Er prüft echte App-Handler mit simulierten
DOM-/API-Grenzen, nicht eine nachgebaute Buchungsimplementierung.

Authentifizierter HTTPS-Test mit synthetischem Piper-Audio:

| Fall | Ergebnis |
|---|---|
| „4 Positionen buchen?“ | WAV von Piper, TTS-Anfrage 180 ms |
| „Bestätigen“ | `confirm`, Backend 367 ms, davon STT 273 ms |
| Synthetischer unbekannter Satz | `unknown`, Backend 415 ms, Intent 17 ms |

Dies sind Einzelmessungen, keine Latenzgarantie und keine vollständige
Mikrofon-bis-Buchung-Messung. Der authentifizierte API-Smoke-Test mit der
tatsächlichen localhost-Origin bestand für beide Lager.

Echter Chrome bei 390 × 844 Pixeln: Rückfrage vollständig im Viewport,
48-Pixel-Schaltflächen, erfolgreich abgespieltes Piper-Audio, Fortschritt
1/2 → 2/2 → geschlossen. Ein zusätzlicher Sprach-/Sammelbefehl während des
ersten Requests erzeugte keinen dritten Request. Nur die Buchungsantworten
waren simuliert; es wurden im automatischen Test keine Lagerbestände geändert.
Ein isolierter Testtab wurde danach geschlossen, sodass keine Audio-/Fetch-
Overrides bestehen bleiben. Sauber neu geöffneter Tab: nur Cache `picking-v42`;
App, Voice-Modul, Helper, CSS und Service Worker stimmen bytegenau mit dem
Worktree überein. Unabhängiges Review fand keine schwerwiegenden Probleme.

## Laufender Stand und nächster Test

Backend und PWA verwenden weiterhin den Voice-Worktree über den lokalen
Compose-Override aus `2026-09-10-voice-latency.md`. Nur Backend wurde neu
erstellt; Datenbanken und Volumes blieben erhalten. Main wurde nicht integriert.

PWA schließen und neu öffnen, dann am echten Mikrofon einen Testauftrag
verwenden: Sammelbefehl, Ja/Nein, anschließend Aufnahme-/Request-/TTS-Zeiten
auswerten. Noch offen sind typische Lagergeräusche und die Endgerät-Messung.
Das bekannte separate IP-Zertifikatsproblem bleibt unverändert.
