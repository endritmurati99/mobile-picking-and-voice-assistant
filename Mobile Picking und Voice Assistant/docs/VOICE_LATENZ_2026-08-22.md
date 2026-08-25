# Latenzmessung Sprachassistent — 22.08.2026

Alle Werte wurden am laufenden Docker-Stack (11 Container, Branch
`integration/foundation-remediation`) erhoben. Es handelt sich um Messwerte, nicht um
Schätzungen oder Simulationen. Wo mehrere Zahlen genannt sind, stehen sie für die
Einzelmessungen derselben Eingabe.

## Anlass

Die Vermutung lautete, die Spracherkennung (Whisper) und die Sprachausgabe (Piper) seien
die Ursache der als langsam empfundenen Bedienung. Diese Vermutung ist durch die Messung
widerlegt. Beide Dienste sind seit den Eingriffen vom 02.08.2026 unauffällig; die
wahrgenommene Langsamkeit entsteht an anderen Stellen der Kette.

## Der schnelle Pfad

Die Äußerung „bestätigen" bis zur hörbaren Quittung „Gebucht." dauert vollständig
1,2 bis 1,7 Sekunden.

| Stufe | Zeit |
| --- | --- |
| Endpointing im Browser | 670–800 ms |
| Upload (11,5 kB Opus) | 15–45 ms |
| ffmpeg-Umwandlung und Whisper | 260–290 ms |
| Intent-Erkennung | 0,2 ms |
| Odoo-Buchung | 120–250 ms |
| Piper bis zum ersten Ton | 130–230 ms |

Der exakte Treffer „bestätigen" bucht direkt, ohne Rückfrage. Dieser Pfad ist bereits
optimal und bietet keinen nennenswerten Spielraum mehr.

## Einzelmessungen der Dienste

**Whisper** (`/asr?language=de&output=json`, Modell `small` int8, adaptives Fenster):

| Eingabe | Messungen | Ergebnis |
| --- | --- | --- |
| „bestätigen" | 142 / 283 / 532 ms | „bestätigen." |
| „weiter" | 104 / 112 / 124 ms | korrekt |
| „alles bestätigen" | 146 / 147 / 148 ms | korrekt |
| „Problem" | 112 / 114 / 117 ms | **„Proplin"** |

Der Fensterpatch aus `whisper/sitecustomize.py` wirkt: statt der früheren 1418 ms werden
257 ms erreicht. Die Fehlerkennung bei „Problem" ist ein Erkennungs-, kein Zeitproblem;
die Intent-Engine antwortet darauf korrekt mit `unknown` bei Konfidenz 0,000.

**Piper** (`/synthesize`, Stimme `de_DE-thorsten-medium`): 338 / 177 / 218 ms für eine
Ansage von rund vier Sekunden Länge. Die Rückgabe erfolgt als unkomprimiertes WAV mit
176.684 / 174.636 / 188.460 Byte. Der Stimmenwechsel von `thorsten-high` auf
`thorsten-medium` vom 02.08.2026 wirkt (vorher 1857 ms).

**Intent-Engine** (`recognize_intent`, Kontext `PickingContext.IDLE`):

| Eingabe | Ergebnis | Konfidenz | Zeit |
| --- | --- | --- | --- |
| `bestätigen` | `confirm` | 0,950 | 0,22 ms |
| `festätigen` | `confirm` | **0,900** | 3,81 ms |
| `niemals bestätigen` | `confirm` | **0,950** | 0,36 ms |
| `Proplin` | `unknown` | 0,000 | 5,21 ms |

Die beiden fett gesetzten Zeilen sind Fehlverhalten. `festätigen` trifft mit 0,900 exakt
die Schwelle zur Direktbuchung. `niemals bestätigen` bucht, weil die Negationsliste in
`backend/app/services/intent_engine.py:62` das Wort „nie" enthält, aber nicht „niemals".

**LLM-Rückfall** (`qwen2.5:1.5b`): 826 / 632 / 948 ms, in allen drei Messungen mit
`ok=False`. Direkt aufgerufen liefert das Modell gültiges JSON in 616–1813 ms; die
Integrationsschicht verwirft das Ergebnis. Der Zweig verbrennt also rund 800 ms und
liefert nichts. `ollama ps` zeigt das Modell geladen, aber zu 100 % auf der CPU.

## Die eigentlichen Zeitfresser

**Rückfrage bei `confirm_all` — 10 Sekunden, im Live-Protokoll gemessen.** Die Rückfrage
erfolgt bedingungslos, auch bei perfekter Erkennung mit Konfidenz 0,95. Mit
`READBACK_MAX_RETRIES=2` summiert sich der ungünstige Fall auf bis zu 30 Sekunden für
eine einzige Buchung.

**Die Zeilenansage selbst — 3820 bis 6120 ms Wiedergabe, Mikrofon währenddessen stumm.**
Dies ist der größte zusammenhängende Block und übersteigt die gesamte Erkennungskette.
Ursache sind ausgeschriebene Regalcodes und vollständige Produktnamen. Eine Normalisierung
der Ansagetexte spart 960 bis 3520 ms je Ansage.

**„ja bitte" wird als `repeat` klassifiziert.** Statt zu bestätigen, liest das System die
vollständige Anweisung erneut vor (bis 7,6 s) und verlangt anschließend eine weitere
Äußerung. Rund 9000 ms ohne Fortschritt.

**Endpointing — 670 bis 800 ms reine Wartezeit,** bevor das erste Byte gesendet wird.
Davon entfallen 570–600 ms auf `SILENCE_AFTER_SPEECH = 550` und 120–180 ms darauf, dass
`analyser.smoothingTimeConstant` in `pwa/js/voice.js:493-494` nicht gesetzt wird und auf
den Web-Audio-Vorgabewert 0,8 fällt. Der Pegel fällt dadurch nur 1,94 dB je Prüfschritt,
was die Stille-Erkennung um vier bis sechs Schritte verzögert, bevor das 550-ms-Fenster
überhaupt anläuft. Der Kommentar in `pwa/js/voice.js:32-39` hält bereits fest, dass die
Stille-Nachlaufzeit keinen messbaren Erkennungsvorteil bringt.

**Verworfene Sprachausgabe bei jeder Sprachbuchung.** `speak('Gebucht.')` beginnt mit
`stopSpeaking()` (`pwa/js/voice.js:402`) und würgt damit die unmittelbar zuvor
angeforderte Ansage der Folgeposition ab. Je Buchung werden so 109 bis 149 ms
Backend-Arbeit und rund 170 kB WLAN-Verkehr erzeugt und sofort verworfen.

**Modellverdrängung.** `docker-compose.yml:305-306` setzt `OLLAMA_MAX_LOADED_MODELS: "2"`.
Nach jeder Bildbewertung ist `qwen2.5:1.5b` verdrängt und muss neu geladen werden, was
4000 ms kostet.

**Feste Pegelschwelle ohne Kalibrierung.** `SPEECH_RMS = 18` (`pwa/js/voice.js:31`) ist ein
absoluter Wert ohne Bezug zum Rauschboden. Im Hallenlärm läuft die Aufnahme bis zum
Zeitlimit `MAX_RECORDING_MS = 10000`, was 8000 bis 9000 ms Verlust bedeutet.

**Kein Audio-Zwischenspeicher.** Die Auswertung der Produktivdaten ergibt eine
Wiederholungsrate von 69 %: 114 Zeilen verteilen sich auf nur 35 verschiedene Ansagetexte.
Vorrendern und Vorabladen über den Service Worker spart rund 280 ms je Ansage, bei
auftragsweisem Vorabladen nahezu die volle Synthesezeit.

**Unkomprimierte Übertragung.** Opus statt WAV spart 60 bis 100 ms im normalen WLAN und
260 bis 410 ms bei schwacher Verbindung. `PIPER_MIN_TEXT_LENGTH = 24` leitet bereits 22
der 33 festen Sätze an die Browserstimme weiter, sodass die Ersparnis vor allem die langen
Zeilenansagen betrifft.

**Mehrbenutzerbetrieb.** Bei fünf gleichzeitigen Kommissionierern steigt der Median der
Piper-Synthese von 235 auf 606 ms (plus 158 %).

**Kleinere Posten.** `ffmpeg` schreibt zwei temporäre Dateien statt zu pipen (53 ms
gesamt, 40 bis 50 ms holbar). Vor der Browserstimme steht ein `setTimeout(80)` ohne
dokumentierte Begründung. Die Vorlaufstille in der Aufnahme verlängert die
Whisper-Verarbeitung um 60 bis 160 ms. Der Upload selbst ist mit 11,5 kB und 15 bis 45 ms
unkritisch.

## Rangfolge nach Nutzen

| Maßnahme | Ersparnis | Aufwand |
| --- | --- | --- |
| `confirm_all` ab Konfidenz 0,90 direkt buchen | 10.000 ms je Auftrag | Minuten |
| Rauschboden kalibrieren statt fester Schwelle 18 | 8.000–9.000 ms im Störfall | Stunden |
| „ja bitte", „fertig", „erledigt" als `confirm` führen | ~9.000 ms je Fall | Stunden |
| Ansagetexte normalisieren | 960–3.520 ms je Ansage | Stunden |
| `OLLAMA_MAX_LOADED_MODELS` auf 3 | 4.000 ms nach jeder Bildbewertung | Stunden |
| Zeitlimit im `unknown`-Zweig | bis 4.000 ms | Stunden |
| Piper-Ansagen vorrendern und vorabladen | 280 ms je Ansage | Tage |
| Opus statt WAV zum Endgerät | 60–100 ms, schwaches WLAN 260–410 ms | Stunden |
| `analyser.smoothingTimeConstant = 0` | 120–180 ms je Äußerung | Minuten |
| Verworfene Ansage bei Sprachbuchung vermeiden | 109–149 ms und 170 kB je Buchung | Minuten |
| `setTimeout(80)` vor der Browserstimme streichen | 80 ms | Minuten |
| `ffmpeg` über Pipe statt Temp-Dateien | 40–50 ms | Stunden |

Die drei mit Minutenaufwand ausgewiesenen Maßnahmen ergeben zusammen rund zehn Sekunden je
Auftrag und etwa 200 ms je Äußerung.

## Nicht die Ursache

Zur Vermeidung erneuter Fehlspuren wird festgehalten, was geprüft und ausgeschlossen wurde:
die Whisper-Verarbeitungszeit, die Piper-Synthesezeit, die Intent-Erkennung
(unter 6 ms in allen Messungen), die Odoo-Schreiblatenz und die Uploadgröße.
