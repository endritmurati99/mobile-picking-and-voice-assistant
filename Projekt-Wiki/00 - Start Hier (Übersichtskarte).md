---
title: Start Hier (Übersichtskarte)
tags:
  - moc
  - übersicht
  - bachelorarbeit
  - mobile-picking
  - voice-assistant
created: 2026-06-22
---

# Start Hier (Übersichtskarte)

> [!info] Was ist dieses Wiki?
> Dies ist die **faktische Projektdokumentation** für den **Mobile Picking & Voice Assistant** — einen Bachelorarbeit-Proof-of-Concept (PoC) auf Basis von **Odoo 18 Community, einer getrennten Odoo-19-Trial-Instanz, FastAPI, n8n, PWA und lokalen KI-Diensten** (Entwicklungszeitraum März–Juli 2026).
> Das Wiki dient zwei Zwecken zugleich: **(a)** als exakte, zitierfähige Quelle für einen KI-Agenten, der daraus die Bachelorarbeit schreibt, und **(b)** als verständliche Einstiegshilfe für den Autor selbst. Jede Notiz beschreibt einen klar abgegrenzten Teil des Systems. Es wird nichts erfunden: Alle Angaben stammen aus der rekonstruierten Projekt-Historie (Commits, ADRs, Dokumentationsdateien).

Diese Notiz ist die **Map of Content (MoC)** — also das zentrale Inhaltsverzeichnis. Von hier aus erreichst du alle anderen Notizen über die verlinkte Liste unten.

> [!note] Analogie für Nicht-Experten
> Stell dir dieses Wiki wie das Inhaltsverzeichnis eines Buches vor: Diese Seite (00) ist die Einstiegsseite, und jeder weitere Eintrag (01–10) ist ein Kapitel zu einem bestimmten Thema. Du musst nicht alles auf einmal lesen — folge einfach der empfohlenen Lesereihenfolge weiter unten.

---

## Inhaltsverzeichnis — alle Notizen auf einen Blick

Jeder Eintrag verlinkt direkt auf die jeweilige Notiz und sagt in **einem Satz**, was darin steht.

| Nr. | Notiz | Was steht drin? |
|-----|-------|-----------------|
| 00 | [[00 - Start Hier (Übersichtskarte)]] | Diese Seite — die Übersichtskarte (Map of Content) mit Einstieg, verlinkter Notizliste und empfohlener Lesereihenfolge. |
| 01 | [[01 - Was ist das Projekt & wie es anfing]] | Erklärt, was der Mobile Picking & Voice Assistant ist, warum er als Bachelor-PoC entstand und wie der Projektstart am 22.03.2026 aussah. |
| 02 | [[02 - Architektur & Diagramm erklärt]] | Beschreibt die Gesamtarchitektur und die Architektur-Invarianten (z. B. Odoo als System of Record, FastAPI als einzige PWA-API, n8n nur asynchron). |
| 03 | [[03 - Docker & Container]] | Erklärt die Container-Landschaft (Docker Compose, Caddy als Reverse Proxy mit HTTPS, Whisper, Piper, Ollama) und die Ressourcen-Caps für n8n. |
| 04 | [[04 - Dev-Workflow Code ändern]] | Zeigt den Entwicklungs-Workflow: wie Code geändert wird, der gestufte n8n-Rollout (backup → import → activate) und die Verifikation per Tests. |
| 05 | [[05 - Backend (FastAPI)]] | Beschreibt das FastAPI-Backend: Picking-Service, Voice-Intent-Engine, Idempotency-/Claiming-Layer und den n8n-Callback-Vertrag. |
| 06 | [[06 - Odoo]] | Erklärt Odoo 18 als System of Record, die Custom-Addons (`picking_assistant_core`, `quality_alert_custom`) und die Quality-Alert-Felder. |
| 07 | [[07 - n8n]] | Beschreibt die n8n-Workflow-Engine: produktive Workflows, lokale LLM-Erweiterung, Circuit Breaker, HMAC-Callback-Secret und den eingefrorenen Vertrag (N8N_CONTRACT_FREEZE_V1). |
| 08 | [[08 - PWA & Voice-Pfad]] | Erklärt die Mobile-PWA (Vanilla JS, offline-first, Service Worker) und den kompletten Voice-Pfad von STT (Whisper) bis TTS (Piper). |
| 09 | [[09 - Projekt-Historie]] | Liefert die vollständige Chronologie von Phase 0 bis zum Juli-Stand, inklusive Wellen, Hotfixes, Odoo-19-Trial und lokaler LLM-Erweiterung. |
| 10 | [[10 - Glossar]] | Sammelt und erklärt alle Fachbegriffe (z. B. Soft Claiming, Idempotency-Key, Circuit Breaker, Intent-Engine, ADR). |
| 11 | [[11 - Kommunikation & Datenaktualitaet (Pull vs Push)]] | Erklärt, wann Daten per Pull (Reads über FastAPI→Odoo) und wann per Push (async Events an n8n) fließen, inkl. Datenaktualität. |
| 12 | [[12 - Funktionsdokumentation]] | **Ordner** — die tiefe, code-belegte Funktionsdokumentation jeder umgesetzten Funktion (Drei-Linsen-Schema: *Wie es funktioniert / Wie es mit Odoo kommuniziert / Was genau zugegriffen wird*), als zitierfähige Vorlage für die Thesis. |

---

## Empfohlene Lesereihenfolge für Einsteiger

> [!note] Für den ersten Durchgang
> Lies die Notizen in dieser Reihenfolge — sie baut Wissen schrittweise auf, vom Großen zum Detail:

1. **[[01 - Was ist das Projekt & wie es anfing]]** — verstehe zuerst das *Warum* und *Was*.
2. **[[02 - Architektur & Diagramm erklärt]]** — verstehe das große Bild und die Grundregeln (Invarianten).
3. **[[03 - Docker & Container]]** — verstehe, *wo* die Teile laufen (Infrastruktur).
4. **[[05 - Backend (FastAPI)]]** — das Herzstück: die API und Intent-Engine.
5. **[[06 - Odoo]]** — die Datenbasis / das System of Record.
6. **[[07 - n8n]]** — die asynchrone Workflow-Schicht.
7. **[[08 - PWA & Voice-Pfad]]** — die Bedienoberfläche und der Sprachweg.
8. **[[04 - Dev-Workflow Code ändern]]** — wenn du selbst etwas ändern willst.
9. **[[09 - Projekt-Historie]]** — für den vollständigen Verlauf und Kontext.
10. **[[10 - Glossar]]** — als Nachschlagewerk jederzeit parallel nutzbar.

> [!info] Tipp
> Notiz **10 - Glossar** ist kein Kapitel, das man linear liest, sondern ein **Nachschlagewerk**. Halte es beim Lesen der anderen Notizen offen, falls ein Begriff unklar ist.

---

## Technologie-Stack auf einen Blick

Damit du beim Lesen weißt, welche Komponente welche Rolle spielt:

| Komponente | Technologie | Rolle |
|------------|-------------|-------|
| Frontend | Vanilla JS + HTML/CSS | Mobile PWA, offline-first |
| Backend | FastAPI (Python) | API, Odoo-Adapter, Intent-Engine |
| Datenbank / ERP | Odoo 18 Community + Odoo-19-Trial | System of Record im Live-Stand; Trial fuer Migration und Traceability-Demo |
| Workflow-Engine | n8n | Async Events, Exception-Assist |
| ASR (Spracherkennung) | Whisper (lokal) | Voice-Recognition / STT |
| TTS (Sprachausgabe) | Piper + Browser-Fallback | Voice-Output |
| Lokales LLM | Ollama (`qwen2.5:7b`) | Asynchrone Quality-Alert-Disposition, mit Heuristik-Fallback |
| Reverse Proxy | Caddy | HTTPS + URL-Routing |
| Infrastruktur | Docker Compose | lokaler Dev + LAN-Betrieb |

> [!note] Lesehilfe
> **STT** = Speech-to-Text (gesprochenes Wort → Text). **ASR** = Automatic Speech Recognition (dasselbe Feld). **TTS** = Text-to-Speech (Text → gesprochenes Wort). Eine ausführliche Erklärung steht in [[10 - Glossar]].

---

## Architektur-Invarianten (die "Grundgesetze" des Projekts)

Diese acht Regeln gelten projektweit und werden in [[02 - Architektur & Diagramm erklärt]] vertieft. Sie sind hier nur zur Orientierung aufgeführt:

1. **Odoo ist System of Record** — keine Shadow-DB, keine doppelten Geschäftsdaten.
2. **FastAPI ist die einzige PWA-API** — die `pwa/` spricht nie direkt mit Odoo oder n8n.
3. **n8n ist nicht im Voice-Hot-Path** — nur Exception-Assist über async Callback.
4. **HTTPS-Pflicht im LAN** — Kamera, Mikrofon und Service Worker brauchen HTTPS.
5. **Touch immer als Fallback** — Voice und Scan sind nie die einzige Bedienweise.
6. **Keine externen Cloud-Dienste im Kern-Workflow** — STT läuft lokal (Whisper).
7. **n8n nur asynchron** — synchrone Antwort im Webhook, async Write-Callback.
8. **Circuit Breaker** — 3 Fehler → 60 s Lock, danach Fallback zum lokalen Betrieb.

---

## Verweis: Ordner "05 - Future Functions"

> [!info] Geplante Erweiterungen
> Neben den Notizen 00–10 gibt es im Wiki den Ordner **"05 - Future Functions"**. Dort werden **geplante Erweiterungen** dokumentiert — also Funktionen, die noch nicht (oder nur teilweise) umgesetzt sind. Beispiele aus der Projekt-Historie, die in diese Richtung zeigen:
> - **Odoo-Instanz-Switching** und **Cluster-/Batch-Picking** sind inzwischen umgesetzt und in die Funktionsdokumentation gewandert.
> - **Seriennummer-/Chargen-Bestätigung** ist umgesetzt, inklusive read-only Retouren-Abgleich; offen bleiben Wiederverwendungsprüfung und persistierte Abweichungen.
> - **Lokale Bild-KI** bleibt Forschungs-/Folgeschritt; umgesetzt ist bisher nur die textbasierte Ollama-Disposition fuer Quality Alerts.
> - **Odoo-19-Live-Cutover** bleibt offen; die aktuelle Odoo-19-Instanz ist eine Trial-/Demo-Kopie.

---

## Verweis: Ordner "12 - Funktionsdokumentation"

> [!success] Tiefe, zitierfähige Funktionsdokumentation
> Der Ordner **"12 - Funktionsdokumentation"** dokumentiert **jede umgesetzte Funktion** code-belegt (mit `Datei:Zeile`-Verweisen) nach einem einheitlichen **Drei-Linsen-Schema**: *Wie es funktioniert*, *Wie es mit Odoo kommuniziert*, *Was genau zugegriffen wird*. Er ist als direkte Vorlage für das Schreiben der Bachelorarbeit gedacht. Einstieg: [[12 - Funktionsdokumentation]] (Inhaltsverzeichnis des Ordners).
> Enthalten: Überblick & Datenfluss, Odoo-Zugriffskatalog, Einzel-Picking, Cluster-/Batch-Picking, Empfängerkarton-Bestätigung, Seriennummer-Bestätigung, Sprachassistent und Qualitätsmeldungen/n8n.

---

## Status des Projekts (Juli 2026)

> [!note] Kurzstand
> - **Kernfunktionen:** Einzel-Picking, Serien-/Chargen-Bestätigung, Cluster-/Batch-Picking, Empfängerkarton-Bestätigung, Voice Assistant und Quality Alerts sind dokumentiert.
> - **Odoo-Instanzen:** Live/Default bleibt Odoo 18; `lager-2` ist zweite Odoo-18-Testinstanz; `o19-trial` ist getrennte Odoo-19-Demo-/Migrationstest-Instanz.
> - **Traceability-Demo:** Odoo-19-Trial besitzt einen Demo-Schalter mit neun Modi für Endprodukt- und BOM-Komponenten-Tracking.
> - **Lokale KI:** Quality Alerts können asynchron über n8n ein lokales Ollama-LLM zur Disposition nutzen; bei Fehlern bleibt die n8n-Heuristik der Fallback.
> - **Offen:** produktiver Odoo-19-Cutover, volle n8n-Instanz-Bewusstheit, persistierte Retouren-Abweichungen und echte Vision-/Bild-KI.

Die vollständige Chronologie steht in [[09 - Projekt-Historie]].
