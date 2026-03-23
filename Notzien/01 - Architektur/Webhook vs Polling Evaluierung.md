---
title: Webhook vs Polling Evaluierung
tags:
  - architecture
  - evaluation
  - n8n
  - odoo
---

# Webhook vs. Polling (Evaluierung & Testplan)

Dieser Plan dient als Grundlage für das Kapitel „Forschungsdesign und Methodik“ bzw. „Systemarchitektur“ der Bachelorarbeit.

## 1. Ergänzung für die Projektbeschreibung (Abstract/Konzept)
**Fokus:** Vergleich von Integrationsmustern für die ereignisgesteuerte Logistik-Orchestration.

> „Ein zentraler Bestandteil der Arbeit ist die Untersuchung und Evaluierung zweier gegensätzlicher Kommunikationsmuster zwischen Odoo (System of Record) und n8n (Orchestrator): **periodisches Polling** vs. **ereignisbasierte Webhooks**. Während Webhooks eine minimale Latenz für die Nutzerinteraktion (Picking-Feedback) versprechen, dient das Polling als Resilienz-Mechanismus (Safety Net), um Datenkonsistenz bei Netzwerkfehlern oder Systemausfällen sicherzustellen. Ziel ist die Implementierung eines hybriden Ansatzes, der die Vorteile beider Muster vereint.“

---

## 2. Technischer Implementierungsplan (Das „Wie & Wo“)

### A. Der Webhook-Pfad (Echtzeit-Interaktion)
* **Wo:** Odoo „Automated Actions“ oder App-Backend.
* **Was:** Sobald der Picker einen Scan bestätigt oder ein Problem meldet, sendet das System sofort einen HTTP-POST an n8n.
* **Ziel:** n8n löst sofort Folgeaktionen aus (z. B. Sprachausgabe „Richtig!“ oder Benachrichtigung des Teamleiters).

### B. Der Polling-Pfad (Resilienz-Sicherung)
* **Wo:** n8n Workflow mit einem `Schedule-Trigger`.
* **Was:** n8n fragt alle 5–10 Minuten über die Odoo-API (`search_read`) alle Datensätze ab, die im Status „Erledigt“ oder „Fehlerhaft“ sind.
* **Ziel:** n8n identifiziert Datensätze, die aufgrund eines fehlgeschlagenen Webhooks (z. B. WLAN-Abbruch) noch nicht verarbeitet wurden.

---

## 3. Test-Szenarien für die Evaluation (Webhook vs. Polling)

Um wissenschaftlich belastbare Daten für die Bachelorarbeit zu erhalten, führen wir drei spezifische Tests durch:

### Szenario 1: Der „Speed-Test“ (Latenzmessung)
* **Ablauf:** Picker bestätigt 20 Scans nacheinander.
* **Messung:** Zeitdifferenz zwischen dem Klick/Scan am Handy und der ersten Reaktion im n8n-Workflow.
* **Erwartung:** Webhook reagiert in < 500ms; Polling reagiert im Durchschnitt erst nach der Hälfte des Intervalls (z. B. 2,5 Min).

### Szenario 2: Der „Crash-Test“ (Resilienz-Prüfung)
* **Ablauf:** Wir deaktivieren n8n kurzzeitig (Container Stop), während der Picker eine Qualitätsmeldung in Odoo speichert. Der Webhook schlägt fehl.
* **Aktion:** Wir starten n8n wieder.
* **Messung:** Wie lange dauert es, bis n8n die „verlorene“ Meldung über das Polling automatisch findet und verarbeitet?
* **Ergebnis:** Beweis für die Notwendigkeit des Pollings als Sicherheitsnetz.

### Szenario 3: Der „Last-Test“ (Systemeffizienz)
* **Ablauf:** Wir simulieren 100 Scans in einer Minute.
* **Messung:** CPU- und RAM-Last auf dem Odoo-Server.
* **Vergleich:** Verursachen 100 einzelne Webhooks mehr Stress als ein einziger Polling-Job, der 100 Zeilen im Batch abholt?

---

## 4. Wissenschaftliche KPIs für die Thesis

| Metrik | Webhook (Ereignis) | Polling (Intervall) |
| :--- | :--- | :--- |
| **Reaktionszeit (Latenz)** | Minimal (Real-Time) | Hoch (Intervall-abhängig) |
| **Datenintegrität** | Risiko von Datenverlust bei Offline-Zeit | Sehr hoch (Self-Healing) |
| **Systemlast** | Spitzenlast bei vielen Events | Planbare, konstante Last |
| **Implementierungsaufwand** | Komplex (Error-Handling nötig) | Einfach (Standard API-Read) |
