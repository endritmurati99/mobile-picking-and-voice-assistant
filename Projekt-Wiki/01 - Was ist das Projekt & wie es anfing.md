---
title: Was ist das Projekt & wie es anfing
tags:
  - projekt
  - uebersicht
  - bachelor
  - poc
  - design-science-research
created: 2026-06-22
---

# Was ist das Projekt & wie es anfing

> [!info] Wofür diese Notiz
> Diese Notiz ist der Einstieg für jeden, der das Projekt zum ersten Mal versteht — egal ob ein Mensch (der Autor) oder ein KI-Agent, der daraus die Bachelorarbeit schreibt. Sie beantwortet vier Fragen: **Was** ist das Projekt, **warum** gibt es es, **wie** fing es an, und **welche Regeln** dürfen niemals gebrochen werden.
> Verwandte Notizen: [[00 - Start Hier (Übersichtskarte)]] · [[02 - Architektur & Diagramm erklärt]] · [[09 - Projekt-Historie]]

---

## 1. Projektziel in Kurzform

Das Projekt ist ein **Proof of Concept (PoC) im Rahmen einer Bachelorarbeit** mit dem Namen **"LogILab Mobile Picking & Voice Assistant"**. Es wird nach der Forschungsmethode **Design Science Research (DSR)** entwickelt und läuft vollständig **lokal im LAN** — es ist kein Cloud-Produkt, sondern ein abgeschlossenes System, das auf eigener Infrastruktur betrieben wird.

> [!note] Was bedeutet "PoC" und "Design Science Research"?
> Ein **Proof of Concept** ist ein lauffähiger Nachweis, dass eine Idee technisch funktioniert — kein fertiges Produkt, sondern der Beweis, dass das Konzept trägt.
> **Design Science Research** ist eine wissenschaftliche Methode, bei der man ein **Artefakt** (hier: die Software) baut, um damit ein konkretes praktisches Problem zu lösen, und aus dem Bauen selbst Erkenntnisse gewinnt. Das gebaute System *ist* der Forschungsbeitrag.

| Eckdaten | Wert |
|----------|------|
| Name | LogILab Mobile Picking & Voice Assistant |
| Art | Bachelorarbeit-PoC |
| Forschungsmethode | Design Science Research |
| Betrieb | Lokal im LAN (kein Cloud-Hosting) |
| Zeitraum | März–Juni 2026 |
| Projektstart | 2026-03-22 (Initial Commit) |
| Stand dieser Notiz | Juni 2026 |

---

## 2. Das Lager-Problem

Im Lager-Picking (Kommissionierung) holt ein Mitarbeiter Artikel von Lagerplätzen ab, um Bestellungen zusammenzustellen. Dabei entstehen typische Probleme, die dieses Projekt adressiert:

- **Hände sind beschäftigt** — wer Ware trägt oder scannt, kann nicht gleichzeitig bequem auf einem Bildschirm tippen. Eine reine Touch-Bedienung bremst.
- **Doppelbuchungen und Mehrgeräte-Konflikte** — wenn mehrere Geräte oder ein Doppelklick dieselbe Pick-Position bestätigen, drohen falsche Bestände.
- **Netzfehler im Lager** — instabiles WLAN führt zu wiederholten Anfragen, die ohne Schutz Daten doppelt schreiben.
- **Schlechte Lesbarkeit** — Lagerbeleuchtung ist dunkel (Annahme im Projekt: ~50 Lux), kleine Schrift ist schwer lesbar.
- **Ausnahmen / Störungen** — beschädigte Artikel, falsche Mengen, fehlende Ware (Shortage) müssen schnell und unterbrechungsfrei gemeldet werden.

> [!note] Was ist "Picking"?
> Picking (Kommissionierung) = das Zusammensuchen einzelner Artikel aus dem Lager für einen Auftrag. Eine "Pick-Zeile" (Move-Line) ist eine einzelne Position: *hole X Stück von Artikel Y am Platz Z*.

---

## 3. Die Lösung in einem Satz

> [!tip] Kernidee
> Eine **offline-fähige mobile Web-App (PWA)**, mit der ein Lagerarbeiter Picking-Aufträge **per Touch, Barcode-Scan oder deutscher Sprachsteuerung** abarbeitet — angebunden an **Odoo 18** als Datenquelle, mit lokaler Spracherkennung (Whisper) und Sprachausgabe (Piper), wobei komplexere Ausnahmefälle asynchron über **n8n** assistiert werden.

---

## 4. Wie das Projekt anfing

Der Start erfolgte am **2026-03-22** mit dem **Initial Commit** der MVP-Struktur. Bereits zu Beginn standen die Bausteine fest:

- **Odoo-Instanz** als System of Record (führende Datenquelle)
- **FastAPI-Backend** für den Picking-Flow und die Voice-Intent-Engine
- **Mobile PWA** (Vanilla JS, offline-first mit Service Worker)
- **n8n** für asynchrone Workflow-Orchestrierung
- **Whisper-Container** für lokale Spracherkennung (STT, Speech-to-Text)

Schon am ersten Tag wurden vier prägende Architekturentscheidungen (ADRs / Architecture Decision Records) getroffen:

| ADR | Entscheidung | Begründung |
|-----|--------------|------------|
| ADR-001 | **Odoo 18 JSON-RPC** statt XML-RPC/REST | Community-Edition + Custom Addons für volle Kontrolle |
| ADR-002 | **Whisper** statt Browser-SpeechRecognition oder Vosk | iOS-PWA-Zuverlässigkeit, bessere Deutsch-Trefferquote |
| ADR-003 | **n8n nicht im Voice-Hot-Path** | Standardkommandos (`confirm`, `next`, `done`) bleiben <500 ms; nur Exception-Assist nutzt n8n |
| (implizit) | **Voice-Toggle** statt Push-to-Talk | Always-on Listening mit Klick-Gate |
| (Security) | **HTTPS-Pflicht im LAN** | Mikrofon-/Kamera-Zugriff braucht HTTPS; mkcert-Zertifikate für Geräte |

> [!note] Was ist ein ADR?
> Ein **Architecture Decision Record** dokumentiert eine wichtige Technik-Entscheidung samt Grund. Spätere Leser verstehen so *warum* etwas so gebaut wurde — und nicht nur *dass* es so ist. Vertiefung in [[02 - Architektur & Diagramm erklärt]] und der Datei `DECISIONS.md`.

---

## 5. Die grobe Phasenreise (Phase 0–6)

Das Projekt wuchs in nachvollziehbaren Phasen. Jede Phase entspricht einem Bündel von Git-Commits. Details stehen in [[09 - Projekt-Historie]].

| Phase | Zeitraum | Schwerpunkt | Kernergebnis |
|-------|----------|-------------|--------------|
| **0 — Bootstrap & Picking-Grundlagen** | 22.–23. März | Grundgerüst | Picking-List + Detail-View, Route-Intelligenz (deterministische Sortierung), Voice-Grundgerüst (`recognize` + `assist`), Plattform-Verifizierung (Desktop Chrome, iOS Safari, Android Chrome) |
| **1 — Transaktionshärtung** | 24. März | Doppelbuchungs-Sicherheit | Soft Claiming (120 s TTL, Heartbeat), Idempotency-Layer in Odoo, Picker-Identität; Addon `picking_assistant_core` |
| **2 — Voice-First & UI-Tuning** | 23.–28. März | Sprache & Bedienung | Intent-Engine v1 (40+ deutsche Aliases), Audio-Feedback, Priority-Filter, Stock-Query per Voice, QA-Form, Scan-Flash grün/rot, State-Aware CTA, größere Schrift |
| **3 — Hardening & n8n-Pipeline** | 26.–28. März | Robustheit | n8n-Ressourcen-Caps, Healthcheck-Gate, Circuit Breaker (3 Fehler → 60 s Lock), Error-Trigger-Workflow, HMAC-Callback-Secret, `N8N_CONTRACT_FREEZE_V1` |
| **4 — Mobile-First & PWA-Refresh** | 28.–30. März | Mobile UX | Kompakt-Layout, iOS Safe-Area-Fixes, deutsche UI, Voice-Normalisierung (ä/ö/ü/ß), Produktbilder, Service Worker v1→v2 |
| **5 — Desktop & Accessibility** | 21.–22. April | Barrierefreiheit | 2-Spalten-Layout (Desktop), Umlaut-Fix in `ui.js`, Toggle-View "Einzeln \| Liste", 48 px Touch-Targets, Playwright-Baselines |
| **6 — TTS & Intent-Expansion** | 23. April | Sprachausgabe | Piper-TTS-Service (thorsten-high), Browser-TTS-Fallback, 60+ neue Aliases, `confirm_all`-Befehl, Login-Begrüßung, Audio-Tuning |

> [!note] Begleitend zu den Phasen: Welle A
> Parallel entstand die **Welle A — Quality-Alert-KI-Bewertung**: im Repo umgesetzt, aber noch **nicht live** (Addon-Upgrade in der Live-DB steht aus). Sie ergänzt Odoo-Felder wie `ai_evaluation_status`, `ai_failure_reason`, `ai_enhanced_description`, `ai_photo_analysis` und einen UI-Tab "Systembewertung". **Nicht** Teil von Welle A: keine Mobile-Diktierfunktion, kein Draft-Enhancement, keine echte Vision-Pipeline, kein OpenAI-Zwang.

---

## 6. Die 6 harten Architektur-Invarianten

> [!warning] Diese Regeln dürfen NICHT gebrochen werden
> Eine **Invariante** ist eine Regel, die zu jedem Zeitpunkt gilt. Wer Code ändert, muss sie einhalten — sonst zerfällt das Gesamtdesign. Vertiefung in [[02 - Architektur & Diagramm erklärt]] und [[04 - Dev-Workflow Code ändern]].

1. **Odoo ist System of Record** → keine Shadow-DB, keine doppelten Geschäftsdaten. Odoo ist die einzige Wahrheit über Bestände und Pickings. Siehe [[06 - Odoo]].
2. **FastAPI ist die einzige PWA-API** → die `pwa/` spricht **niemals** direkt mit Odoo oder n8n, immer nur über FastAPI. Siehe [[05 - Backend (FastAPI)]] und [[08 - PWA & Voice-Pfad]].
3. **n8n ist nicht im Voice-Hot-Path** → Standardkommandos bleiben schnell (<500 ms); nur Exception-Assist läuft über asynchronen n8n-Callback. Siehe [[07 - n8n]].
4. **HTTPS-Pflicht im LAN** → Kamera, Mikrofon und Service Worker funktionieren nur über HTTPS (mkcert-Zertifikate).
5. **Touch ist immer Fallback** → Voice und Scan sind nie die einzige Bedienweise; per Hand geht alles auch.
6. **Keine externen Cloud-Dienste im Kern-Workflow** → STT läuft lokal (Whisper); der Kernablauf bleibt im LAN.

> [!note] Zwei weitere stützende Regeln
> In der Analyse-Quelle stehen acht Schlüsselregeln. Sechs davon sind die oben genannten "harten" Invarianten. Zwei weitere sind eng damit verwandt und konkretisieren sie:
> - **n8n nur asynchron** → synchrone Antwort im Webhook, asynchroner Write-Callback (konkretisiert Regel 3).
> - **Circuit Breaker** → 3 Fehler → 60 s Lock, danach Fallback zu lokalem Betrieb (konkretisiert Regel 6 / Robustheit).
> *(Annahme: Diese Zuordnung — 6 harte Invarianten + 2 stützende Regeln — ist eine Strukturierung dieser Wiki-Notiz; die Quelle listet alle acht gleichrangig auf.)*

---

## 7. Technologie-Stack auf einen Blick

| Komponente | Technologie | Rolle | Wiki-Notiz |
|------------|-------------|-------|------------|
| Frontend | Vanilla JS + HTML/CSS | Mobile PWA, offline-first | [[08 - PWA & Voice-Pfad]] |
| Backend | FastAPI (Python) | API, Odoo-Adapter, Intent-Engine | [[05 - Backend (FastAPI)]] |
| Datenbank | Odoo 18 Community | System of Record | [[06 - Odoo]] |
| Workflow-Engine | n8n | Async Events, Exception-Assist | [[07 - n8n]] |
| ASR (Spracherkennung) | Whisper (lokal) | Voice-Recognition / STT | [[08 - PWA & Voice-Pfad]] |
| TTS (Sprachausgabe) | Piper + Browser-Fallback | Voice-Output | [[08 - PWA & Voice-Pfad]] |
| Reverse Proxy | Caddy | HTTPS + URL-Routing | [[03 - Docker & Container]] |
| Infrastruktur | Docker Compose | Lokaler Dev + LAN-Betrieb | [[03 - Docker & Container]] |

> [!note] Begriffe (siehe [[10 - Glossar]])
> **PWA** = Progressive Web App (installierbare Web-App, läuft auch offline). **ASR/STT** = Spracherkennung (Sprache → Text). **TTS** = Sprachausgabe (Text → Sprache). **Reverse Proxy** = Vermittler, der eingehende HTTPS-Anfragen an die richtigen internen Dienste verteilt.

---

## 8. Was ein Leser zuerst wissen muss

> [!tip] Die fünf wichtigsten Merksätze
> 1. **Es ist ein PoC, kein Produkt** — gebaut zum Nachweis und zur Forschung (Design Science Research), läuft lokal im LAN.
> 2. **Odoo entscheidet, FastAPI vermittelt, die PWA bedient** — diese Schichtung ist heilig (Invarianten 1 & 2).
> 3. **Drei Bedienwege, Touch immer als Sicherheit** — Voice (Whisper/Piper), Scan (Barcode) und Touch; Touch fällt nie weg (Invariante 5).
> 4. **Voice muss schnell bleiben** — Standardkommandos <500 ms, n8n nur für Ausnahmen und nur asynchron (Invarianten 3 & 7).
> 5. **Robust gegen Lager-Realität** — Soft Claiming + Idempotency gegen Doppelbuchungen, Circuit Breaker gegen n8n-Ausfälle, offline-first PWA gegen Netzlücken.

> [!info] Wo geht es weiter?
> - Architektur im Detail: [[02 - Architektur & Diagramm erklärt]]
> - Wie man das System startet: [[03 - Docker & Container]]
> - Wie man Code sicher ändert: [[04 - Dev-Workflow Code ändern]]
> - Vollständige Commit-Historie & Hotfixes: [[09 - Projekt-Historie]]
> - Begriffe nachschlagen: [[10 - Glossar]]
> - Gesamtübersicht: [[00 - Start Hier (Übersichtskarte)]]

---

> [!note] Quellenhinweis für die Bachelorarbeit
> Alle Fakten dieser Notiz stammen aus der projektinternen Geschichts-Analyse (`[history]`) und den dort referenzierten Dokumenten: `ARCHITECTURE.md`, `DECISIONS.md`, `N8N_CONTRACT_FREEZE_V1.md`, `PHASE_1_TRANSACTION_HARDENING.md`, `SESSION_2026-03-31_UI_HARDENING.md`. Konkrete Endpunkte, Modelle und Pfade werden in den jeweiligen Themen-Notizen ([[05 - Backend (FastAPI)]], [[06 - Odoo]], [[07 - n8n]]) zitierfähig vertieft. Als **Annahme** markierte Aussagen (z. B. ~50 Lux Lagerlicht, die 6+2-Strukturierung der Regeln) sind nicht direkt belegt, sondern Interpretationen.
