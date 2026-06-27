---
title: "Funktionsdokumentation (Übersicht)"
tags:
  - moc
  - funktionsdoku
  - bachelorarbeit
  - mobile-picking
status: dokumentiert
stand: 2026-06-26
---

# Funktionsdokumentation — Map of Content

> [!abstract] Zweck dieses Ordners
> Dieser Ordner dokumentiert **jede umgesetzte Funktion** des Mobile Picking & Voice Assistant so präzise und zitierfähig, dass sie direkt in die **Bachelorarbeit** übernommen werden kann. Jede Seite ist nach demselben Schema aufgebaut und mit **`Datei:Zeile`-Belegen** im Quellcode hinterlegt (Nachvollziehbarkeit vor Geschwindigkeit). Diese Notiz ist das Inhaltsverzeichnis des Ordners.

## Das Drei-Linsen-Schema

Jede Funktionsseite betrachtet die Funktion durch dieselben drei Linsen — genau die Fragen, die in der Thesis pro Feature beantwortet werden müssen:

1. **Wie es funktioniert** — der fachliche Ablauf aus Sicht des Pickers und der Schichten (PWA → FastAPI → Odoo → n8n).
2. **Wie es mit Odoo kommuniziert** — welche JSON-RPC-Aufrufe das Backend absetzt, mit welcher Auth, welchen Kontext-Flags und welchem Fehler-/Telemetrieverhalten.
3. **Was genau zugegriffen wird** — die konkreten Odoo-**Modelle, Felder (gelesen/geschrieben), Methoden und Domain-Filter**, jeweils als Tabelle und mit `Datei:Zeile`-Beleg.

Zusätzlich enthält jede Seite (soweit relevant) die betroffenen **FastAPI-Endpunkte**, die **PWA-Seite**, **Telemetrie & Fehlerverhalten** und am Ende eine Liste **„Quellen im Code"**.

## Inhalt

| Nr. | Seite | Worum geht es? |
|-----|-------|----------------|
| 00 | [[00 - Überblick & Datenfluss]] | Die Schichten (PWA → Caddy → FastAPI → Odoo → n8n), der Request-Lebenszyklus eines Writes und die nicht verhandelbaren Architektur-Invarianten. |
| 01 | [[01 - Odoo-Kommunikation & Zugriffskatalog]] | Der JSON-RPC-Adapter (`OdooClient`: Auth, Timeout, Fehler) **plus** der konsolidierte Zugriffskatalog über alle Features (Modelle/Felder/Methoden/Domains an einem Ort). |
| 02 | [[02 - Einzel-Kommissionierung (Picking)]] | Offene Aufträge laden, Claim/Heartbeat/Release, Scan-Bestätigung pro Move-Line, Mengen-/Barcode-Prüfung und Routenführung. |
| 03 | [[03 - Cluster- & Batch-Picking]] | Mehrere Aufträge in einem Rundgang über `stock.picking.batch`, je Auftrag eine Ziel-Verpackung (`result_package_id`), gesammelter Abschluss via `action_done`. |
| 04 | [[04 - Empfängerkarton-Bestätigung (Put-to-Box)]] | Scan-oder-Tippen des richtigen Ziel-Kartons pro Position, serverseitige Prüfung gegen `result_package_id`, Verwechslungsschutz (falscher Karton → kein Write). |
| 05 | [[05 - Seriennummer-Bestätigung]] | Erfassung/Validierung der Seriennummer (Lot) beim Pick, Schreiben von `lot_name`, Telemetrie `serial_confirm`. |
| 06 | [[06 - Sprachassistent (STT, Intent, TTS)]] | Voice-Pfad: Whisper (STT) → Intent-Engine (Keyword-Matching) → Piper (TTS), mit Touch als Pflicht-Fallback und lokalem STT (kein Cloud-Hot-Path). |
| 07 | [[07 - Qualitätsmeldungen & n8n-Orchestrierung]] | Quality Alert + Foto anlegen, asynchrone KI-Bewertung über n8n, Circuit Breaker, Shadow-Evaluation und kontrollierte Rückschreibung der `ai_*`-Felder. |

## Empfohlene Lesereihenfolge

1. **[[00 - Überblick & Datenfluss]]** — zuerst das große Bild und die Invarianten.
2. **[[01 - Odoo-Kommunikation & Zugriffskatalog]]** — das gemeinsame Fundament aller Features (der eine Odoo-Adapter + Gesamt­katalog).
3. **[[02 - Einzel-Kommissionierung (Picking)]]** — der Kern-Workflow, auf dem die übrigen Features aufsetzen.
4. **[[03 - Cluster- & Batch-Picking]]** und **[[04 - Empfängerkarton-Bestätigung (Put-to-Box)]]** — die Mehr-Auftrags-Erweiterung samt Verwechslungsschutz.
5. **[[05 - Seriennummer-Bestätigung]]** — die Exemplar-genaue Erfassung.
6. **[[06 - Sprachassistent (STT, Intent, TTS)]]** — die Sprachbedienung.
7. **[[07 - Qualitätsmeldungen & n8n-Orchestrierung]]** — die asynchrone KI-/Ausnahmeschicht.

> [!info] Verhältnis zum übrigen Wiki
> Diese Seiten sind die **tiefe, code-belegte Funktionsdokumentation**. Die übergeordnete Architektur steht in [[02 - Architektur & Diagramm erklärt]], die Komponenten in [[05 - Backend (FastAPI)]], [[06 - Odoo]], [[07 - n8n]] und [[08 - PWA & Voice-Pfad]]. Geplante Erweiterungen liegen im Ordner **„05 - Future Functions"**.

## Verwandt

- [[00 - Start Hier (Übersichtskarte)]]
- [[02 - Architektur & Diagramm erklärt]]
- [[11 - Kommunikation & Datenaktualitaet (Pull vs Push)]]
