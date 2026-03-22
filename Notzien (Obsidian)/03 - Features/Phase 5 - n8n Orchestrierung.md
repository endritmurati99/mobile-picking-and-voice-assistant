---
title: Phase 5 - n8n Orchestrierung
tags:
  - phase
  - n8n
  - workflows
  - orchestration
status: pending
---

# Phase 5 — n8n Orchestrierung

> [!todo] Wartet auf Phase 4
> n8n-Webhooks aktivieren und Workflows für Pick-Events + Quality-Alerts einrichten.
> **Voraussetzung:** [[Phase 4 - Voice Picking]] ✅ abgeschlossen.

Überblick: [[00 - Projekt Übersicht]] | Architektur: [[System Architektur]] | Nächste Phase: [[Phase 6 - Integration und Lagertest]]

---

## Architektur-Prinzip

> [!warning] n8n ist Orchestrator, NICHT App-Backend
> - n8n empfängt nur **fire-and-forget Webhooks** — kein Echtzeit-State
> - n8n liegt **NICHT im Voice-Pfad** (zu langsam)
> - Binärdaten (Fotos) werden **NICHT** durch n8n geleitet
> - n8n macht Folgeaktionen: Benachrichtigungen, Reports, Eskalationen

---

## Existierende Workflows

Alle drei Workflow-Dateien sind in `n8n/workflows/` als JSON-Export vorhanden und können direkt importiert werden.

| Workflow | Datei | Trigger |
| -------- | ----- | ------- |
| Pick Confirmed | `pick-confirmed.json` | `POST /webhook/pick-confirmed` |
| Quality Alert Created | `quality-alert-created.json` | `POST /webhook/quality-alert-created` |
| Daily Report | `daily-report.json` | Cron: Mo-Fr 08:00 |

---

## Setup-Schritte

### 1. n8n erreichbar

```bash
# n8n läuft unter:
https://<LAN-IP>/n8n/
# → Setup-Wizard beim ersten Start (E-Mail + Passwort setzen)
```

> [!caution] WEBHOOK_URL muss gesetzt sein
> In `.env`: `WEBHOOK_URL=https://<LAN-IP>/n8n/`
> Ohne diese Variable enthalten Webhook-URLs `http://localhost:5678` statt der externen URL.
> Backend kann dann keine Webhooks zustellen.

### 2. Workflows importieren

```
n8n → Settings → Import from File → n8n/workflows/pick-confirmed.json
n8n → Settings → Import from File → n8n/workflows/quality-alert-created.json
n8n → Settings → Import from File → n8n/workflows/daily-report.json
```

### 3. Webhooks aktivieren

Nach dem Import: Jeden Workflow öffnen → **"Activate"** schalten.

### 4. Webhook-URLs verifizieren

In n8n nach Aktivierung die Webhook-URLs kopieren:
- `POST https://<LAN-IP>/n8n/webhook/pick-confirmed`
- `POST https://<LAN-IP>/n8n/webhook/quality-alert-created`

> [!info] Backend-Konfiguration
> Das Backend (`n8n_webhook.py`) nutzt `N8N_WEBHOOK_BASE = http://n8n:5678/webhook` (intern).
> n8n empfängt den Call über Docker-internes Netzwerk — kein Umweg über Caddy.

---

## Workflow-Details

### `pick-confirmed.json` — Picking abgeschlossen

**Trigger:** `POST /webhook/pick-confirmed`

**Payload vom Backend:**
```json
{
    "picking_id": 1,
    "completed_by": "mobile-picking-assistant"
}
```

**Aktueller Flow:**
1. Webhook empfangen
2. Prüfen ob `picking_complete == true`
3. Log-Eintrag erstellen

**Erweiterungsmöglichkeiten:**
- Odoo HTTP Request: Picking-Name + Produkte abfragen
- E-Mail-Benachrichtigung an Lagerleiter
- Slack/Teams-Nachricht
- Odoo-Aktivität für nächsten Schritt erstellen

### `quality-alert-created.json` — Quality Alert erstellt

**Trigger:** `POST /webhook/quality-alert-created`

**Payload vom Backend:**
```json
{
    "alert_id": 1,
    "name": "QA/0001",
    "picking_id": 5,
    "priority": "2"
}
```

**Aktueller Flow:**
1. Webhook empfangen
2. Alert-Daten formatieren (Log-Eintrag)
3. Respond-Node

**Erweiterungsmöglichkeiten (nach PoC):**
- Hohe Priorität (≥2): Sofort-Benachrichtigung an QM
- Odoo: Alert-Stage auf "In Bearbeitung" setzen
- Foto-URL aus Odoo abfragen

### `daily-report.json` — Täglicher Report

**Trigger:** Cron `0 8 * * 1-5` (Mo-Fr 08:00)

**Aktueller Flow:**
1. Report-Text generieren
2. Log-Eintrag

**Erweiterungsmöglichkeiten:**
- Odoo HTTP Request: Offene Pickings abfragen
- Odoo HTTP Request: Abgeschlossene Pickings gestern
- Odoo HTTP Request: Offene Quality Alerts
- E-Mail-Report generieren

---

## Test-Szenarien

### Webhook manuell testen

```bash
# n8n von außen über Caddy
curl -k -X POST https://localhost/n8n/webhook/pick-confirmed \
  -H "Content-Type: application/json" \
  -d '{"picking_id": 1, "completed_by": "test"}'
# → {"status": "received"}

# Oder direkt (wenn n8n-Port intern erreichbar)
curl -X POST http://localhost:5678/webhook/pick-confirmed \
  -H "Content-Type: application/json" \
  -d '{"picking_id": 1}'
```

### End-to-End Webhook-Test

```bash
# 1. Picking im Backend abschließen (bestätigt alle Zeilen)
curl -k -X POST "https://localhost/api/pickings/1/confirm-line?move_line_id=1&scanned_barcode=4006381333931&quantity=10"
# → picking_complete: true → Backend feuert Webhook → n8n empfängt

# 2. n8n Execution in UI prüfen:
# https://<LAN-IP>/n8n/ → Workflows → Pick Confirmed → Executions
```

---

## Bekannte Fallstricke

> [!warning] n8n hinter Caddy: Webhook-URLs
> n8n hinter `/n8n/`-Prefix: Im Workflow muss der Path ohne `/n8n/` angegeben werden.
> Korrekt: `path: "pick-confirmed"` (ohne `/n8n/webhook/` Prefix — das fügt n8n selbst hinzu).

> [!warning] n8n Execution-Logs bei Fehler
> Bei Webhook-Fehlern: n8n → Workflows → Execution List → Failed Executions prüfen.

> [!warning] n8n Datenbank (PostgreSQL)
> n8n nutzt die gemeinsame PostgreSQL-Instanz (Datenbank `n8n`).
> Wird durch `infrastructure/scripts/init-n8n-db.sql` beim ersten DB-Start erstellt.

---

## Go/No-Go Checkliste

| Kriterium | Status |
| --------- | ------ |
| n8n Setup-Wizard abgeschlossen | ☐ |
| Alle 3 Workflows importiert + aktiviert | ☐ |
| Webhook `pick-confirmed` empfängt POST | ☐ |
| Webhook `quality-alert-created` empfängt POST | ☐ |
| Backend feuert Webhook nach Picking-Abschluss | ☐ |
| Backend feuert Webhook nach Quality Alert | ☐ |
| Kein Fehler im n8n Execution Log | ☐ |

---

## Weiterführend

- [[System Architektur]] — n8n Rolle im Gesamtsystem (fire-and-forget)
- [[API Dokumentation]] — Webhook-Payloads
- [[Phase 4 - Voice Picking]] — Vorhergehende Phase
- [[Phase 6 - Integration und Lagertest]] — Nächste Phase
