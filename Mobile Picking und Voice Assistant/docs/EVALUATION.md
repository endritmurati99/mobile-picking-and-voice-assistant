# Evaluationsplan

## Methodik: Design Science Research (Peffers et al., 2008)

### Phasen
1. Problemidentifikation: Manuelle Picking-Prozesse sind fehleranfällig
2. Zieldefinition: Mobile, sprachgesteuerte Picking-Assistenz mit Quality-Capture
3. Design & Entwicklung: PWA + Odoo + n8n + Vosk
4. Demonstration: PoC-Durchführung
5. **Evaluation**: Nutzerstudie (Within-Subjects)
6. Kommunikation: Bachelorarbeit

### Experimentaldesign
- **Within-Subjects** mit Counterbalancing
- **Bedingung A**: Papier-Pickliste, manuelle Qualitätsmeldung
- **Bedingung B**: PWA mit Voice + Scan + Foto
- **Teilnehmer**: 10–15, Latin-Square-Counterbalancing
- **Aufgabe**: 5 Pickings × 3–5 Zeilen + 1–2 Qualitätsvorfälle

### Messgrößen
| Messgröße | Instrument | Vergleich |
|-----------|-----------|-----------|
| Picking-Zeit/Zeile | System-Timestamps | Stoppuhr (Papier) |
| Fehlerquote | Post-hoc-Prüfung | Gleiche Prüfung |
| Scan-Erfolgsrate | System-Log | N/A |
| Quality-Report-Zeit | Timestamps | Stoppuhr |
| Report-Qualität | 5-Kriterien-Rubrik (0–10) | Gleiche Rubrik |
| Usability | SUS (Benchmark: 68) | N/A |
| Kognitive Last | NASA-TLX Raw | Paarvergleich |
| Qualitativ | Semi-strukturiertes Interview | Thematische Analyse |

### Statistik
- Gepaarte t-Tests (oder Wilcoxon bei Verletzung der Normalverteilung)
- Cohen's d als Effektstärke
- 95%-Konfidenzintervalle
- Shapiro-Wilk-Test für Normalverteilungsprüfung
