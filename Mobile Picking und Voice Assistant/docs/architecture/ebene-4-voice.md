# Ebene 4: Voice mit Whisper und Piper

Voice ersetzt den verlässlichen Touch- und Scannerweg nicht. Es ergänzt ihn:
Der Mitarbeiter kann sprechen, die PWA versteht einfache Befehle und liest
Antworten vor.

## Die Erklärung in 30 Sekunden

Die PWA nimmt eine kurze Äußerung auf und sendet Audio plus den sichtbaren
Arbeitskontext an FastAPI. FastAPI wandelt das Audio über Whisper in Text um
und erkennt daraus einen erlaubten Befehl.

Unklare oder riskante Schreibbefehle müssen bestätigt werden. Eine echte
Positionsbuchung läuft danach durch denselben FastAPI- und Odoo-Pfad wie bei
Touch. Antworten spricht bevorzugt Piper; bei kurzen Texten oder Fehlern kann
der Browser selbst sprechen.

> **Merksatz:** Whisper hört, FastAPI versteht und prüft, Piper spricht – Odoo
> bleibt für Lagerbuchungen zuständig.

## Der Ablauf als Bild

![Voice-Ablauf von der Aufnahme über Whisper bis zur sicheren Odoo-Aktion und Sprachausgabe](./ebene-4-voice.svg)

Die [Excalidraw-Quelldatei](./ebene-4-voice.excalidraw) ist editierbar. Die
[SVG-Datei](./ebene-4-voice.svg) ist die Exportfassung.

## Das geprüfte LEGO-Beispiel

Die PWA zeigt im realen Auftrag `WH/INT/00360` für das Modell „Ente Henri“ die
Position „1 × Brick 2x2 pink“ am Platz `L-E1-P2`. Der Mitarbeiter sagt:

```text
„Position bestätigen“
```

Whisper liefert Text. Die Intent-Erkennung erkennt `confirm`. Weil dies eine
Lagerbuchung auslöst, fragt die PWA bei zu geringer Sicherheit noch einmal
nach. Nach „Ja“ nutzt sie denselben `confirm-line`-Endpunkt wie der Touchknopf.

## Schritt 1: Aufnahme starten

Der Voice-Knopf unterstützt zwei Bedienweisen:

- kurzer Klick: Hands-free-Modus ein- oder ausschalten,
- längerer Druck: Push-to-Talk.

Die PWA fordert ein Mono-Mikrofon mit Echo- und Rauschunterdrückung an. Sie
beendet die Aufnahme bei Stille oder spätestens nach zehn Sekunden. Sehr kurze
Geräusche werden verworfen.

## Schritt 2: Audio und Kontext senden

```text
POST /api/voice/recognize
```

Neben dem Audio sendet die PWA nur den nötigen UI-Kontext, zum Beispiel:

- aktuelle Oberfläche,
- sichtbare Auftragsposition,
- Anzahl der verbleibenden Positionen.

So kann „weiter“ auf der Detailseite anders behandelt werden als auf der
Anmeldeseite.

## Schritt 3: Audio für Whisper vorbereiten

FastAPI lehnt leere Dateien ab und wandelt Browserformate über ffmpeg in
Mono-WAV mit 16 kHz um. Danach ruft es den internen Whisper-Dienst auf:

```text
FastAPI → POST http://whisper:9000/asr
```

Whisper transkribiert auf Deutsch mit einem kurzen Lager-Domänenhinweis.
Segmente, die sehr wahrscheinlich nur Stille oder Halluzination sind, werden
verworfen.

## Schritt 4: Einen erlaubten Intent erkennen

FastAPI verwendet zuerst die deterministische Intent-Erkennung:

1. Text normalisieren,
2. bekannte genaue Formulierungen prüfen,
3. reguläre Regeln prüfen,
4. ähnliche Formulierungen vorsichtig vergleichen.

Oberflächenregeln verhindern unpassende Aktionen. Ein `confirm` ist zum
Beispiel nur bei einer aktiven Auftragsposition sinnvoll. Verneinungen wie
„nicht weiter“ dürfen nicht als Zustimmung ausgeführt werden.

Bleibt der Intent unbekannt oder unsicher, darf optional ein lokaler Ollama-
Classifier helfen. Bei Timeout oder Fehler bleibt das deterministische
Ergebnis bestehen. Ein vom Modell vorgeschlagener Schreibintent kann nie
allein eine Buchung freigeben.

## Schritt 5: Aktion sicher ausführen

Navigation, Wiederholen, Status und Kamera kann die PWA lokal ausführen. Für
eine echte Positionsbestätigung verwendet sie dagegen:

```text
POST /api/pickings/{id}/confirm-line
```

Damit gelten dieselben Schutzmechanismen wie in Ebene 2:

- gültige Sitzung und CSRF-Schutz,
- gültiger Claim für Mitarbeiter und Gerät,
- Idempotenzschlüssel,
- Barcode-, Bestands- und gegebenenfalls Serien-/Losprüfung,
- Abschlussentscheidung durch Odoo.

`confirm_all` verlangt immer eine Rückfrage. Ein einzelnes `confirm` verlangt
sie ebenfalls, wenn die Erkennung nicht sicher genug ist.

## Der getrennte Assist-Pfad

Explizite Bestandsfragen laufen über:

```text
POST /api/voice/assist
```

FastAPI liest dafür Picking- und Bestandskontext aus Odoo und erzeugt eine
lokale Antwort. Der aktuelle Assist-Pfad ruft weder n8n noch ein LLM auf und
führt keine Buchung oder automatische Nachschubanforderung aus. Er ist
absichtlich lesend.

## Schritt 6: Antwort sprechen

Kurze Texte kann die Browserfunktion `speechSynthesis` direkt ausgeben.
Längere Texte sendet die PWA bevorzugt an:

```text
POST /api/voice/tts → FastAPI → Piper
```

Piper erzeugt intern eine WAV-Datei mit der deutschen Stimme
`de_DE-thorsten-medium`. Bei Timeout oder Fehler fällt die PWA auf Browser-TTS
zurück.

Während die Anwendung spricht, ist das Mikrofon stumm. Ein kurzer Cooldown und
eine Echo-Prüfung verhindern, dass die Anwendung ihre eigene Antwort wieder
als neuen Befehl versteht.

## Fehler und sichere Rückfälle

- Kein Mikrofon oder keine Berechtigung: Touch, Scanner und Kamera bleiben da.
- Leere oder verrauschte Aufnahme: keine Aktion.
- Whisper nicht erreichbar: verständliche Fehlermeldung, keine Buchung.
- Unbekannter Intent: Rückfrage oder Abbruch.
- Ollama nicht erreichbar: deterministische Erkennung bleibt maßgeblich.
- Piper nicht erreichbar: Browser-TTS übernimmt.
- Odoo lehnt eine Buchung ab: kein falscher Erfolgszustand.

## Wo der Ablauf im Projekt steckt

- `pwa/js/voice.js`: Aufnahme, Wiedergabe und Echo-Schutz
- `pwa/js/voice-runtime.mjs`: UI-Kontext und Rückfrage-Regeln
- `pwa/js/app.js`: Intent-Dispatcher und fachliche Aktionen
- `pwa/js/api.js`: Voice- und Picking-Aufrufe
- `backend/app/routers/voice.py`: Recognize, Assist und TTS
- `backend/app/services/intent_engine.py`: deterministische Intent-Erkennung
- `backend/app/services/whisper_client.py`: Whisper-Zugriff
- `backend/app/services/piper_client.py`: Piper-Zugriff
- `backend/app/services/voice_intent_classifier.py`: optionaler Ollama-Fallback

## Kurz zusammengefasst

1. Die PWA nimmt kurz Audio auf.
2. Whisper liefert deutschen Text.
3. FastAPI erkennt nur kontextuell erlaubte Intents.
4. Schreibaktionen erhalten Rückfragen und normale Backend-Prüfungen.
5. Piper oder der Browser spricht die Antwort.
6. Touch und Scanner bleiben jederzeit verfügbar.
