---
tags:
  - future
  - backlog
---

# Future Functions & Verbesserungen

> Ideen und bekannte Schwächen die nach dem MVP angegangen werden.
> Werden hier gesammelt damit nichts vergessen geht.

---

## Voice Assistant

### Barcode-Nummern nicht vorlesen
- **Problem:** TTS liest 9-stellige Barcode-Nummern vor (z.B. "6-1-0-1-1-2-1") — unbrauchbar im Lager
- **Lösung:** Barcodes aus dem TTS-Text herausfiltern, stattdessen nur Produktname + Lagerort vorlesen
- **Priorität:** Hoch

### Intelligenterer Voice Agent (ElevenLabs / KI-Stimme)
- **Idee:** Aktuellen Vosk STT + Browser TTS ersetzen durch ElevenLabs Voice Agent oder ähnliches
- **Vorteil:** Natürlichere Stimme, kontextbewusstes Gespräch, bessere Fehlerkorrektur
- **Constraint:** Muss lokal oder datenschutzkonform laufen (kein Cloud-Zwang laut Architektur)
- **Priorität:** Niedrig (erst nach stabilem MVP)

---

## Quality Alerts

### Bessere Struktur & Workflow
- **Problem:** Aktuell minimales Datenmodell — kein klarer Eskalationspfad
- **Idee:** Mehrstufiger Workflow mit Benachrichtigungen, Verantwortlichkeiten, SLA
- **Priorität:** Mittel

---

## PWA / UI Design

### Scanner-UI überarbeiten
- **Problem:** Aktuelles Design ist funktional aber nicht optimal für Lagerumgebung (Handschuhe, Licht)
- **Idee:** Größere Touch-Targets, höherer Kontrast, One-Hand-Bedienung
- **Priorität:** Niedrig (erst nach vollständigem Feature-Set)

---

## Allgemein

### MQTT-Barcode-Scanner Integration
- **Hintergrund:** `MQTT_Barcode` + `mqtt_listener` + `logilab` in masterfischer installiert
- **Idee:** Physische Scanner im Lager über MQTT anbinden
- **Offen:** Quellcode beim Professor anfragen (E-Mail Todo)
- **Priorität:** Optional

---

*Zuletzt aktualisiert: 2026-03-22*
