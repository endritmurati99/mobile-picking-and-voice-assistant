---
title: Phase 7 - Härtung und Evaluation
tags:
  - phase
  - evaluation
  - sus
  - nasa-tlx
  - bachelorarbeit
status: pending
---

# Phase 7 — Härtung + Evaluation

> [!todo] Wartet auf Phase 6
> Formale Evaluation mit Probanden, SUS-Fragebogen, NASA-TLX und Zeitmessungen.
> **Voraussetzung:** [[Phase 6 - Integration und Lagertest]] ✅ abgeschlossen.

Überblick: [[00 - Projekt Übersicht]] | Architektur: [[System Architektur]]

---

## Design Science Research Evaluationsplan

Die Evaluation folgt dem **Within-Subjects-Design**:

| | Bedingung A | Bedingung B |
|--|--|--|
| **Methode** | Papier-Pickliste + manuelle Qualitätsmeldung | PWA mit Voice + Scan + Foto-QA |
| **Geräte** | Papier + Stift | iPhone oder Android + BT-Scanner |
| **Reihenfolge** | Hälfte der Probanden: A→B | Andere Hälfte: B→A |

**Probanden:** 10–15 Teilnehmer (Lagermitarbeiter oder Studierende mit Lager-Erfahrung)

---

## Ergänzende technische Integrations-Evaluation

> [!info] Separate Teil-Evaluation
> Neben der Nutzerevaluation wird eine kleine technische Evaluation der Integrationsmuster durchgeführt.
> Sie ersetzt **nicht** den Vergleich Papier vs. System, sondern ergänzt ihn um die Frage, wie n8n-Ereignisse robust verarbeitet werden.

**Verglichene Muster:**
- `Webhook`: schnelle Folgeaktion nach erfolgreichem Event im Backend
- `Polling`: periodischer Reconciliation-Job als Safety Net bei verpassten Webhooks

| Metrik | Webhook | Polling |
| ------ | ------- | ------- |
| Reaktionszeit | niedrig | intervallabhängig |
| Recovery nach Ausfall | nur mit zusätzlicher Recovery-Logik | gut geeignet als Safety Net |
| Systemlast | viele kleine Requests | planbare Batch-Reads |
| Implementierungsaufwand | Error-Handling und Idempotenz nötig | einfacher Trigger, aber saubere Marker nötig |

> [!note] Wichtige Abgrenzung
> Gemessen wird die Orchestrierungsstrecke zwischen FastAPI/Odoo und n8n.
> Die direkte Nutzerreaktion in PWA oder TTS ist **nicht** Teil dieses Vergleichs.

---

## Messgrößen

### Quantitativ (System-Logs)

| Messgröße | Einheit | Erfassung |
| --------- | ------- | --------- |
| Picking-Zeit pro Zeile | Sekunden | FastAPI-Timestamps |
| Fehlerquote Scan | % | Falsche Barcodes / Gesamt |
| Voice-Erkennungsrate | % | `confidence ≥ 0.7` / Gesamt |
| Quality-Report-Zeit | Sekunden | Alert-Start bis Alert-Erstellt |
| Webhook-Latenz | Millisekunden | Event gespeichert → erste n8n-Execution |
| Recovery-Zeit Polling | Sekunden oder Minuten | verpasstes Event → Polling zieht nach |
| Duplikatquote | % | doppelt verarbeitete Events / Gesamt |
| Systemfehler | Anzahl | Error-Log |

### Quantitativ (Fragebogen)

| Instrument | Wann | Auswertung |
| ---------- | ---- | ---------- |
| **SUS** (System Usability Scale) | Nach Bedingung B | Score 0–100, ≥68 = akzeptabel |
| **NASA-TLX Raw** | Nach jeder Bedingung | 6 Subskalen, 0–100 |

### Qualitativ

- Semi-strukturiertes Interview (8 Fragen, ~15 Min.)
- Beobachtungsprotokoll (Fehler, Frustration, Kommentare)

---

## SUS-Fragebogen (10 Items)

Die Standard-Items, auf das System angepasst:

1. Ich würde den Picking-Assistenten gerne häufig benutzen.
2. Der Picking-Assistent war unnötig komplex.
3. Der Picking-Assistent war einfach zu benutzen.
4. Ich benötigte technische Unterstützung um den Assistenten zu benutzen.
5. Die Funktionen des Assistenten waren gut integriert.
6. Es gab zu viele Inkonsistenzen im Assistenten.
7. Die meisten Menschen würden den Assistenten schnell erlernen.
8. Der Assistent war sehr umständlich zu benutzen.
9. Ich fühlte mich bei der Benutzung des Assistenten sehr sicher.
10. Ich musste viel lernen bevor ich mit dem Assistenten arbeiten konnte.

**Auswertung:** Ungerade Items (positiv): Score - 1. Gerade Items (negativ): 5 - Score. Summe × 2.5 = SUS-Score (0–100).

---

## NASA-TLX Subskalen

| Subskala | Beschreibung |
| -------- | ------------ |
| Mental Demand | Wie viel mentale Anstrengung war erforderlich? |
| Physical Demand | Wie viel körperliche Anstrengung? |
| Temporal Demand | Wie viel Zeitdruck? |
| Performance | Wie erfolgreich haben Sie die Aufgabe erfüllt? |
| Effort | Wie viel Aufwand war nötig? |
| Frustration | Wie frustriert, gestresst, gereizt waren Sie? |

---

## Interview-Leitfaden (8 Fragen)

1. Beschreiben Sie Ihre bisherige Erfahrung mit Lager-Software und mobilen Picking-Systemen.
2. Was hat Ihnen am Picking-Assistenten am besten gefallen?
3. Was hat Sie am meisten gestört oder verlangsamt?
4. Wie beurteilen Sie die Sprachsteuerung im Vergleich zum Scannen?
5. Würden Sie die App in Ihrem Arbeitsalltag verwenden wollen? Warum (nicht)?
6. Welche Funktionen fehlen Ihnen, um effizienter zu arbeiten?
7. Hatten Sie Probleme mit dem Gerät oder der App? Wenn ja, welche?
8. Was sollte unbedingt verbessert werden, bevor das System im Einsatz geht?

---

## Statistik-Plan

```python
# Gepaarter t-Test (oder Wilcoxon wenn nicht normalverteilt)
from scipy import stats
import numpy as np

# Picking-Zeiten: Bedingung A vs B
times_a = [...]  # Sekunden, Papier-Methode
times_b = [...]  # Sekunden, System
t_stat, p_value = stats.ttest_rel(times_a, times_b)

# Effektstärke Cohen's d
d = (np.mean(times_a) - np.mean(times_b)) / np.std(np.array(times_a + times_b))
```

Zu berichten: t-Wert, df, p-Wert, Cohen's d, 95%-Konfidenzintervall.

Für die technische Integrations-Evaluation genügen primär deskriptive Kennzahlen:
- Median und p95 der Webhook-Latenz
- mittlere Recovery-Zeit nach n8n-Ausfall
- Anzahl verlorener oder doppelt verarbeiteter Events
- CPU/RAM-Snapshots für Backend, n8n und Odoo

---

## Härtungsmaßnahmen (vor Evaluation)

> [!info] Härtung = Robustheit für den Evaluationszeitraum (nicht Produktionssicherheit)

- [ ] Odoo-Verbindungsfehler: Retry-Logik (3 Versuche, exponential backoff)
- [ ] Whisper-Timeout: 10s Fallback mit Toast-Meldung
- [ ] PWA Offline-Indicator: Rotes Banner bei `navigator.onLine === false`
- [ ] Logging: Alle API-Requests mit Timestamp, User-Action, Response-Code
- [ ] Sync-Marker oder Outbox-Logik für Reconciliation vorbereiten
- [ ] Docker Restart-Policy: `unless-stopped` auf allen Services (bereits gesetzt)
- [ ] `.env` Backup: Vor Evaluation sichern

---

## Evaluationsprotokoll

```
Datum: ___________
Proband-ID: P___
Reihenfolge: A→B / B→A (zutreffendes einkreisen)

Bedingung A (Papier):
  Picking-Zeit gesamt: _____ min
  Fehler: _____

Bedingung B (System):
  Picking-Zeit gesamt: _____ min
  Fehler: _____
  Voice genutzt: Ja / Nein
  Scan genutzt: Ja / Nein
  Systemfehler: Ja / Nein (wenn ja: ____________)

SUS-Score Bedingung B: _____
NASA-TLX A: MD___ PD___ TD___ P___ E___ F___
NASA-TLX B: MD___ PD___ TD___ P___ E___ F___

Interview-Notizen:
```

---

## Go/No-Go Checkliste

| Kriterium | Status |
| --------- | ------ |
| SUS-Fragebogen vorbereitet (10 Items) | ☐ |
| NASA-TLX Formular vorbereitet | ☐ |
| Interview-Leitfaden erstellt | ☐ |
| 10+ Probanden rekrutiert | ☐ |
| Evaluationsumgebung getestet | ☐ |
| Logging aktiviert (alle Timestamps) | ☐ |
| Daten erhoben (alle Probanden) | ☐ |
| Statistik-Auswertung durchgeführt | ☐ |
| Setup-Doku von Dritten getestet | ☐ |

---

## Weiterführend

- [[00 - Projekt Übersicht]] — Gesamtüberblick Phasen
- [[Phase 6 - Integration und Lagertest]] — Vorhergehende Phase
- [[System Architektur]] — Technische Grundlage für Evaluation
