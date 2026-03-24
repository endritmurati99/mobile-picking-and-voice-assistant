---
title: Phase 6 - Integration und Lagertest
tags:
  - phase
  - testing
  - integration
  - warehouse
status: pending
---

# Phase 6 — Integration + Lagertest

> [!todo] Wartet auf Phase 5
> Vollständigen End-to-End-Test im realen Lagerumfeld durchführen.
> **Voraussetzung:** [[Phase 5 - n8n Orchestrierung]] ✅ abgeschlossen.

Überblick: [[00 - Projekt Übersicht]] | Architektur: [[System Architektur]] | Nächste Phase: [[Phase 7 - Härtung und Evaluation]]

---

## Ziel dieser Phase

Das System unter realistischen Bedingungen testen:
- **20 Picks ohne Systemfehler** durchführen
- Voice-Erkennungsrate messen
- Quality Alert im Live-Szenario testen
- System-Resilienz testen (Odoo-Restart, Netzwerkausfall, n8n-Ausfall)

---

## Voraussetzungen (Checkliste)

Alle vorherigen Phasen müssen bestanden sein:

- [ ] Phase 0: Stack läuft, HTTPS, Grünes Schloss
- [ ] Phase 1: Odoo DB, Custom Module, Seed-Daten
- [ ] Phase 2: Alle Endpoints 200/422, PWA auf Mobile
- [ ] Phase 3: Barcode-Scan funktioniert zuverlässig
- [ ] Phase 4: Voice-Picking mit >80% Erkennungsrate
- [ ] Phase 5: n8n-Webhooks empfangen und verarbeiten

---

## Test-Szenarien Phase 6

### Szenario 1: Normaler Picking-Durchlauf (Voice)

```
1. Picking-Liste laden → 1 offenes Picking wählen
2. TTS: "Geh zu Regal A-01. Prüfziffer: Eins."
3. Prüfziffer ansagen: "Eins"
4. TTS: "Nimm 10 Schrauben M8."
5. Voice: "Bestätigt"
6. → Nächster Pick-Schritt
7. Alle Zeilen → TTS: "Auftrag abgeschlossen"
```

### Szenario 2: Normaler Picking-Durchlauf (Scan)

```
1. Picking-Liste laden → Picking wählen
2. Barcode der Schraube M8 scannen
3. → Bestätigung
4. Alle Zeilen scannen
5. → Picking komplett
```

### Szenario 3: Quality Alert mit Foto

```
1. Während Picking: Problem-Button drücken
2. Foto aufnehmen (Kamera)
3. Beschreibung eingeben
4. Absenden → Alert in Odoo sichtbar
5. n8n-Execution zeigt Quality-Alert-Webhook
```

### Szenario 4: Falscher Artikel

```
1. Pick-Zeile für Schraube M8
2. Falschen Barcode scannen
3. → Fehlermeldung + TTS "Falscher Artikel"
4. Richtigen Barcode scannen → Bestätigung
```

### Szenario 5: Resilienz-Test

```
1. Picking läuft
2. Odoo-Container neu starten: docker compose restart odoo
3. System nach ~30s wieder verfügbar
4. Picking weiterführen → funktioniert
```

### Szenario 6: Technischer Integrationsvergleich (Webhook vs. Polling)

> [!info] Ergänzt den Lagertest, ersetzt ihn nicht
> Dieses Szenario misst die Orchestrierung zwischen FastAPI, Odoo und n8n.
> Der eigentliche Picking- und Quality-Flow bleibt dafür unverändert.

**Teil A: Speed-Test**
```
1. 20 Picks oder 20 Quality-Alerts nacheinander auslösen
2. Timestamp beim erfolgreichen Backend-Write notieren
3. Erste n8n-Execution-Zeit notieren
4. Differenz als Webhook-Latenz auswerten
```

**Teil B: Crash-Test**
```
1. n8n-Container stoppen
2. Quality Alert oder Picking-Abschluss normal in der PWA auslösen
3. Webhook fällt aus
4. n8n wieder starten
5. Reconciliation-Workflow per Polling suchen lassen
6. Recovery-Zeit bis zur nachgezogenen Verarbeitung messen
```

**Teil C: Last-Test**
```
1. 100 Events in 1 Minute simulieren
2. Einmal mit direkter Webhook-Verarbeitung messen
3. Einmal mit zusätzlichem Polling-Abgleich messen
4. CPU/RAM auf Backend, n8n und Odoo vergleichen
```

---

## Messgrößen

Diese Daten werden für die Bachelorarbeit benötigt:

| Messgröße | Einheit | Wie messen |
| --------- | ------- | ---------- |
| Picking-Zeit pro Zeile | Sekunden | System-Timestamps in FastAPI-Logs |
| Fehlerquote | % | Anzahl falscher Scans / Gesamtscans |
| Voice-Erkennungsrate | % | `confidence >= 0.7` / Gesamt-Requests |
| Quality-Report-Zeit | Sekunden | Timestamp Alert-Start → Alert-Erstellt |
| Webhook-Latenz | Millisekunden | Odoo/Backend-Event → erste n8n-Execution |
| Recovery-Zeit nach n8n-Ausfall | Sekunden oder Minuten | fehlgeschlagenes Event → Polling findet Event |
| Integrationslast | CPU/RAM/API-Calls | Backend, n8n und Odoo parallel beobachten |
| Systemverfügbarkeit | % | Uptime-Log |

```bash
# Logs für Auswertung
docker compose logs backend > backend-log.txt
docker compose logs --since 2h backend | grep "STT:"
```

---

## Bekannte Risiken

> [!warning] WiFi-Interferenz im Lager
> Bluetooth-HID-Scanner und WiFi können auf 2.4GHz interferieren.
> Lösung: Dual-Band Router, 5GHz für mobile Geräte.

> [!warning] Lärm und Voice-Erkennung
> Lagerlärm (Gabelstapler, Lüftung) kann die Whisper-Erkennungsrate senken.
> Lösung: Headset mit Geräuschunterdrückung oder Touch-Fallback.

> [!warning] iOS Mikrofon-Permission nach App-Suspend
> Nach längerem Suspend kann iOS die Mikrofon-Permission zurückziehen.
> Lösung: Vor jedem Start der Sprachaufnahme Permission prüfen.

---

## Kill-Kriterium

> [!danger] Kill-Kriterium: Voice im Lager unbrauchbar
> Falls Voice im Lagerumfeld unzuverlässig (<60% Erkennungsrate mit Headset):
> → Voice als "optional/experimentell" dokumentieren
> → Evaluation-Design anpassen: Fokus auf Scan + Touch als primäre Interaktion
> → Voice-Ergebnis als separate Beobachtung in Bachelorarbeit aufnehmen

---

## Go/No-Go Checkliste

| Kriterium | Status |
| --------- | ------ |
| 20 Picks ohne Systemfehler | ☐ |
| Voice-Erkennungsrate >80% mit Headset | ☐ |
| Quality Alert mit Foto aus Live-Szenario | ☐ |
| Alert in Odoo sichtbar (Kanban-View) | ☐ |
| System erholt sich von Odoo-Restart | ☐ |
| n8n-Execution-Log ohne Fehler | ☐ |
| iOS + Android beide funktionsfähig | ☐ |

---

## Weiterführend

- [[System Architektur]] — Gesamtarchitektur für Kontext
- [[Phase 5 - n8n Orchestrierung]] — Vorhergehende Phase
- [[Phase 7 - Härtung und Evaluation]] — Nächste Phase: SUS, NASA-TLX, Messung
