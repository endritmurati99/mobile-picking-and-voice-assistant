# Voice-Kommando-Referenz

## Voice-Modus

Der Voice-Modus wird per **Mic-Button** oder **Taste M** ein-/ausgeschaltet (Toggle).

| Aktion | Effekt |
|--------|--------|
| Mic-Button / Taste M | Voice-Modus ein/aus |
| Sprechen + Pause (~550ms) | Audio wird automatisch erkannt und verarbeitet |
| TTS spricht | Mikrofon stumm (kein Feedback-Loop) |
| TTS fertig | Nächster Aufnahme-Zyklus startet automatisch |

**STT-Engine:** Whisper (faster_whisper, small-Modell, lokal im Docker)
**TTS-Engine:** Piper (lokal), mit Browser SpeechSynthesis (de-DE) als Rückfall

## Allgemeine Kommandos
| Kommando | Varianten | Aktion |
|----------|----------|--------|
| Bestätigt | bestätige, ja, korrekt, ok | Aktuelle Aktion bestätigen |
| Nächster | nächste, weiter, skip | Zum nächsten Schritt |
| Zurück | vorheriger | Zum vorherigen Schritt |
| Problem | fehler, defekt, beschädigt, fehlt | Quality Alert starten |
| Foto | bild, kamera | Kamera öffnen |
| Wiederholen | nochmal, wie bitte | Letzte Ansage wiederholen |
| Pause | stopp, halt | Voice-Modus pausieren |
| Fertig | abgeschlossen, ende | Picking abschließen |
| Hilfe | help | Verfügbare Kommandos ansagen |

## Zahlen-Eingabe
| Sprechen | Erkannt als |
|----------|------------|
| "fünf" | 5 |
| "vier sieben" | 4, dann 7 |
| "12" oder "zwölf" | 12 |

## Kontext-abhängiges Verhalten
- **Standort-Check**: System erwartet Prüfziffer → Zahleneingabe validiert Standort
- **Mengen-Bestätigung**: System erwartet Menge → "bestätigt" oder Korrektur-Zahl
- **Allgemein**: Alle Kommandos verfügbar

## Technische Parameter
| Parameter | Wert | Beschreibung |
|-----------|------|-------------|
| Sprach-Schwelle | RMS > 18 | Unterscheidung Sprache/Rauschen |
| Stille-Timeout | 550ms | Stille nach Sprache → senden |
| Kein-Sprache-Timeout | 6s | Neustart bei Stille |
| Min. Sprechdauer | 100ms | Verhindert Artefakte |
| Max. Aufnahme | 10s | Sicherheits-Timeout |
