# Voice-Kommando-Referenz

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
