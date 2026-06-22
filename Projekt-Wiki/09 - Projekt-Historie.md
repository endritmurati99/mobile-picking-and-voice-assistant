---
title: Projekt-Historie
tags:
  - bachelorarbeit
  - mobile-picking
  - voice-assistant
  - projekt-historie
  - chronologie
  - git
created: 2026-06-22
---

# Projekt-Historie

> [!info] Worum geht es in dieser Notiz?
> Diese Notiz erzählt die **vollständige Geschichte** des Projekts **Mobile Picking & Voice Assistant** — von der ersten Code-Zeile am 22.03.2026 bis zum Stand Juni 2026. Sie ist der **rote Faden**: *Was haben wir wann gebaut, und warum so?*
> Alle Angaben stammen aus **belegbaren Quellen**: dem `git log` des Repositories, den ADRs (`docs/DECISIONS.md`), den technischen Dokumenten in `docs/` und den projektinternen Arbeitsanweisungen (`CLAUDE.md`, `AGENTS.md`). Es wird nichts erfunden. Wo eine Aussage eine Interpretation ist, ist sie ausdrücklich als **Annahme** markiert.

> [!note] Analogie für Nicht-Experten
> Stell dir das Projekt wie den Bau eines Hauses vor: Zuerst das Fundament (Phase 0), dann die tragenden Wände gegen Erdbeben (Phase 1 = Transaktionshärtung), dann die Inneneinrichtung und Bedienung (Voice & UI), schließlich Feinschliff und Barrierefreiheit. Die "Wellen" und "Hotfixes" sind nachträgliche Reparaturen und Anbauten, die während des Bewohnens nötig wurden.

Schwesternotizen für Details: [[00 - Start Hier (Übersichtskarte)]] · [[01 - Was ist das Projekt & wie es anfing]] · [[02 - Architektur & Diagramm erklärt]] · [[05 - Backend (FastAPI)]] · [[06 - Odoo]] · [[07 - n8n]] · [[08 - PWA & Voice-Pfad]] · [[10 - Glossar]]

---

## Quellenlage und Methodik

> [!info] Worauf sich diese Chronologie stützt
> Die Phasenstruktur (0–7) ist eine **rekonstruierte Lesart** der tatsächlichen Entwicklung, abgeleitet aus zwei harten Belegquellen:
> 1. **Git-Historie** — die Commits mit Datum, Nachricht und geänderten Dateien (`git log`).
> 2. **Dokumentation im Repo** — ADRs, Phasen-Dokumente und Session-Notizen unter `docs/`.
>
> **Annahme zur Phasen-Nummerierung:** Die Commit-Nachrichten verwenden teilweise eigene Phasenbezeichnungen (z. B. `feat(phase5): hardening`). Diese stimmen **nicht 1:1** mit der hier verwendeten didaktischen Phasen-Nummerierung 0–7 überein. Die hier genutzte Nummerierung dient der verständlichen Gliederung; die jeweils genannten **Commit-Hashes und Daten** sind dagegen exakt aus dem `git log` belegt und gehen vor.

Die zentralen Belegdateien (Pfade relativ zum Projekt-Root `Mobile Picking und Voice Assistant/`):

| Datei | Inhalt |
|-------|--------|
| `docs/ARCHITECTURE.md` | Systemrollen, Architekturregeln, Hauptflüsse, Quality-Alert-Felder nach Welle A |
| `docs/DECISIONS.md` | ADR-001 bis ADR-006 (Architecture Decision Records) |
| `docs/PHASE_1_TRANSACTION_HARDENING.md` | Soft Claiming, Idempotency, Picker-Identität |
| `docs/N8N_CONTRACT_FREEZE_V1.md` | Eingefrorener n8n-Vertrag, erlaubte Writeback-Endpunkte |
| `docs/QUALITY_ALERT_AI_FIELDS.md` | Semantik der KI-Felder am Quality Alert |
| `docs/SESSION_2026-03-31_UI_HARDENING.md` | Detailprotokoll der UI-Härtung + n8n-Pipeline-Fix |
| `docs/VOICE_COMMANDS.md` | Voice-Kommando-Referenz, technische Audio-Parameter |
| `CLAUDE.md`, `AGENTS.md` | Operative Invarianten und Arbeitszonen |

---

## Überblick: Zeitstrahl der Meilensteine

> [!note] Die wichtigsten git-Meilensteine auf einen Blick
> Datum und Commit-Hash sind exakt aus `git log` belegt.

| Datum | Commit | Meilenstein |
|-------|--------|-------------|
| 2026-03-22 | `017dda4` | **Initial commit** — Projektgrundgerüst |
| 2026-03-22 | `efb48f2` | Deterministische Picking-Route (`feat(route)`) |
| 2026-03-22 | `83227f4` | Voice-First: Priority-Filter, Proactive Greeting |
| 2026-03-22 | `363ca7c` | Voice-First: Audio-Feedback, Filter-Badge, Stock-Query |
| 2026-03-22 | `198b7a9` | Cross-Platform Voice (iOS Safari + Android Chrome) |
| 2026-03-22 | `6f5d3c5` | Backend: `picking_service` Location-Helfer + Route-Grouping |
| 2026-03-22 | `7c1fb17` | Repo "private-clean" (Notzien/.claude entfernt) |
| 2026-03-31 | (Session) | UI-Härtung + n8n-Pipeline-Fix (`SESSION_2026-03-31`) |
| 2026-03-22 | `3698656` | **Phase-5-Commit:** Hardening + Safe AI Rollout |
| 2026-03-22 | `dbaf055` | **Phase-5-Commit:** n8n-Hardening + PWA-Overhaul |
| 2026-03-22 | `d27685d` | PWA mobile-first Refresh |
| 2026-04-21 | `c2863fe` | PWA Desktop-Layout, Umlaut-Fixes, Emoji-Nav, List-View |
| 2026-04-22 | `84d13e8` | PWA Responsive-Redesign + A11y-Fixes |
| 2026-04-23 | `a17a06a` | **Piper TTS**, erweiterte Intent-Engine, Login-Begrüßung |
| 2026-05-06 … 05-09 | div. | Deployment-Planung (Hostinger VPS), Doku-Refresh |
| 2026-05-15 | `27ea056` | Fix: lokaler Docker-Dev-Stack-Start |
| 2026-05-19 | `3519a11`…`d16a793` | Architektur-Diagramm + Odoo-n8n-Trigger-Doku |

> [!warning] Datums-Anomalie in der Git-Historie
> Mehrere inhaltlich "spätere" Commits (z. B. die Phase-5-Commits `3698656`/`dbaf055`, der PWA-Refresh `d27685d`) tragen im `git log` das **Author-Datum 2026-03-22**, obwohl die zugehörige Session-Doku `SESSION_2026-03-31` auf Ende März datiert. **Annahme:** Diese frühen Daten entstehen durch Rebase/Cherry-Pick auf dem Branch `wip/staff-hardening-2026-03-22` (alle als `Merge pull request #1…#5 from endritmurati99/wip/staff-hardening-2026-03-22` gemergt). Für die inhaltliche Reihenfolge ist daher die **logische Abfolge** maßgeblich, nicht das nominelle Commit-Datum. Die ab April datierten Commits (`c2863fe` ff.) sind chronologisch zuverlässig.

---

## Der Anfang: Frühjahr 2026

Projektstart am **2026-03-22** mit dem `Initial commit` (`017dda4`). Von Beginn an stand die Grobarchitektur fest und wurde direkt als Mehr-Komponenten-Stack angelegt:

- **Odoo 18 Community** als *System of Record* (fachliche Datenquelle für Pickings, Quality Alerts, Nutzer, Lagerplätze).
- **FastAPI-Backend** als einzige API-Schicht zwischen PWA und Odoo/n8n, inkl. JSON-RPC-Bridge zu Odoo und Voice-Intent-Engine.
- **Mobile PWA** (Vanilla JS, HTML, CSS) — offline-first mit Service Worker.
- **n8n** als Orchestrator für asynchrone Events und synchrone Ausnahmeassistenz.
- **Whisper** als lokaler ASR-/STT-Service.

Mehrere **Architekturentscheidungen** wurden sofort getroffen und sind in `docs/DECISIONS.md` als ADRs festgehalten:

> [!note] Die Gründungs-ADRs (belegt in `docs/DECISIONS.md`)
> - **ADR-001 — Odoo 18 Community statt Enterprise:** Enterprise-Lizenz war nicht verfügbar; Entscheidung für Community + Custom Modules. *Konsequenz:* mehr Eigenbau, dafür volle Kontrolle über Datenmodell und Schnittstellen.
> - **ADR-002 — Whisper statt Browser-SpeechRecognition / Vosk:** Browser-STT in iOS-PWAs ist zu unzuverlässig, Vosk war für Deutsch im Lagerkontext nicht treffsicher genug. *Konsequenz:* bessere Erkennung, dafür etwas mehr Latenz + Audio-Konvertierung im Backend.
> - **ADR-003 — n8n nicht im normalen Voice-Pfad:** Standardkommandos (`confirm`, `next`, `done`) dürfen nie auf LLM-/Workflow-Latenz warten. Der normale Voice-Loop bleibt komplett im App-Backend; n8n ist nur für den separaten Exception-Assist-Pfad `/api/voice/assist` erlaubt und dort *read-only*.
> - **ADR-004 — HID-Scanner als Primär-Scan-Methode:** Bluetooth-HID-Scanner sind Primärpfad, Kamera und Touch bleiben Fallbacks (Kamera-Scanning war weniger robust).
> - **ADR-005 — FastAPI als Command Gatekeeper:** Operative Writes nach Odoo laufen ausschließlich über FastAPI-Commands. n8n darf direkt aus Odoo **lesen**, aber den fachlichen Zustand nicht unkontrolliert mutieren.
> - **ADR-006 — Circuit Breaker für den Sync-Assist-Pfad:** `request_reply()` öffnet nach drei Fehlversuchen einen In-Memory-Circuit-Breaker für 60 Sekunden.

Aus der projektübergreifenden Memory-Notiz sind außerdem zwei frühe Tausch-Entscheidungen vom **2026-03-22** belegt:

- **Whisper ersetzte Vosk** (bessere WER für Deutsch).
- **Voice-Toggle ersetzte Push-to-Talk** (ein Klick aktiviert kontinuierliches Zuhören).

> [!info] Detail-Quellen
> Vollständige Architektur-Begründung siehe [[02 - Architektur & Diagramm erklärt]]. Stack-Details siehe [[03 - Docker & Container]].

---

## Phase 0 — Bootstrap & Picking-Grundlagen

> [!note] Zeitraum & Commits
> **22.–23. März 2026.** Von `Initial commit` (`017dda4`) bis `feat(mobile): cross-platform voice picking` (`198b7a9`).

**Was gebaut wurde:**

- **Picking-List + Detail-View** als touch- und barcode-bedienbare Grundoberfläche der PWA.
- **Route-Intelligenz:** deterministische Sortierung offener Positionen — Commit `efb48f2` `feat(route): add deterministic picking route intelligence`.
- **Picking-Service im Backend:** Location-Parser und Route-Grouping — Commit `6f5d3c5` `feat(backend): extend picking_service with location helpers + route grouping`.
- **Voice-Grundgerüst:** die beiden Voice-Endpunkte `POST /api/voice/recognize` (Hot-Path, lokal) und `POST /api/voice/assist` (Exception-Assist, read-only über n8n) wurden angelegt (belegt in `docs/ARCHITECTURE.md`, Abschnitt *Hauptflüsse*).
- **Cross-Platform-Verifikation:** Voice-Picking lief verifiziert auf **iOS Safari + Android Chrome** (Commit `198b7a9`); Desktop Chrome ebenfalls.

**Frühe plattformspezifische Probleme** (Hotfix-Charakter, siehe auch Abschnitt *Wellen & Hotfixes*):

- iOS Service Worker fing `/api/*`-Requests ab → `null respondWith`. Fix: Service Worker cached nur statische Assets, nicht die API.
- iOS-TTS-Race: nach `speechSynthesis.cancel()` war eine kurze Verzögerung (~80 ms) nötig, bevor die nächste Ausgabe startete.

> [!info] Detail-Quellen
> Picking-Service und Intent-Engine: [[05 - Backend (FastAPI)]]. PWA-/Voice-Pfad: [[08 - PWA & Voice-Pfad]].

---

## Phase 1 — Transaktionshärtung

> [!note] Zeitraum & Quelle
> Detailliert protokolliert in `docs/PHASE_1_TRANSACTION_HARDENING.md`. Aufräum-Commits im Umfeld: `e9ff20c` (`chore: cleanup repo structure`) bis `7c1fb17` (`chore: make repo private-clean`).

**Fokus:** Der bestehende Picking-Flow sollte **nicht umgebaut**, sondern gegen reale Störungen gehärtet werden — also kein Doppelbuchen bei Retry/Doppelklick, kein paralleles Bearbeiten desselben Pickings ohne sichtbaren Konflikt, und echte Picker-Zuordnung statt technischer Default-Namen.

**Was gebaut wurde:**

- **Soft Claiming** (belegt in `docs/PHASE_1_TRANSACTION_HARDENING.md`):
  - Claim wird **beim Öffnen** eines Pickings gesetzt.
  - **Heartbeat** verlängert den Claim während der Bearbeitung.
  - **Release** erfolgt beim Abschluss oder beim Verlassen der Detailansicht.
  - **TTL = `120s`** (Standard).
- **Idempotency-Layer:**
  - Idempotency wird **in Odoo gespeichert**, nicht nur im FastAPI-Prozess.
  - Eindeutigkeit basiert auf `endpoint + key`; zusätzlich wird ein **Fingerprint des Payloads** gespeichert.

  | Situation | Antwort |
  |-----------|---------|
  | gleicher Key + gleicher Fingerprint | Replay (idempotent wiederholt) |
  | gleicher Key + anderer Fingerprint | `409` |
  | laufender gleicher Request | `409` |

- **Picker-Identität:** Die PWA verwendet einen ausgewählten Odoo-Benutzer; dessen User-ID wird in Write-Headern gesendet. Das Gerät erhält zusätzlich eine lokale **`device_id`**.

**Was sich fachlich NICHT geändert hat** (bewusst):

- `confirm-line` bestätigt weiter die **komplette Zielmenge** der aktuellen Zeile — keine Partial-Pick-Logik.
- `next` / `skip` sind noch **keine** fachlich persistierten Skip-Vorgänge.
- Quality Alerts bleiben additive Erweiterungen und ändern den Picking-Abschluss nicht.

> [!note] Warum man davon in der UI kaum etwas sieht
> Der Nutzen der Transaktionshärtung liegt fast ausschließlich in **Fehlerfällen**: doppelte Requests, instabiles Netz, versehentlich doppelt geöffnete Pickings, mehrere Geräte im selben Auftrag. Im **Happy Path** arbeitet die App deshalb fast wie zuvor — die Härtung ist eine unsichtbare Versicherung.

> [!info] Detail-Quelle
> Idempotency-/Claiming-Layer im Backend: [[05 - Backend (FastAPI)]]. Custom-Addons in Odoo (`picking_assistant_core`, `quality_alert_custom`): [[06 - Odoo]].

---

## Phase 2 — Voice-First & UI-Tuning

> [!note] Commits
> `83227f4` `feat(voice-first): priority filter, proactive greeting, voice commands` · `363ca7c` `feat(voice-first): audio feedback, filter badge, stock query` · `198b7a9` Cross-Platform Voice. Die UI-Anteile (QA-Form, Scan-Flash, State-Aware CTA, Font) sind im Detail in `docs/SESSION_2026-03-31_UI_HARDENING.md` dokumentiert.

**Was gebaut wurde (Voice & Interaktion):**

- **Intent-Engine v1:** deutschsprachige Kommando-Erkennung mit zahlreichen Aliases (siehe `docs/VOICE_COMMANDS.md` für die Kommando-Tabelle: *Bestätigt, Nächster, Zurück, Problem, Foto, Wiederholen, Pause, Fertig, Hilfe*).
- **Audio-Feedback:** Haptik + Ton bei Scan-Erfolg/-Fehler.
- **Priority-Filter:** dringende Pickings (`priority === '1'`) werden hervorgehoben; Badge in der Listenansicht.
- **Proactive Greeting:** das System fragt nach Idle aktiv nach der nächsten Aktion.
- **Stock-Query per Voice:** Bestandsabfrage ("wieviel in WH/RACK/BIN?").

**Was gebaut wurde (UI-Tuning — belegt in `SESSION_2026-03-31`):**

- **QA-Form mit Schnellauswahl-Chips** in `pwa/js/app.js` (`openQualityAlertForm`): vier vordefinierte Chips — `Verpackung defekt`, `Artikel beschädigt`, `Menge falsch`, `Sonstiges` — mit `role="group"` + `aria-label`. Mehrfachauswahl, Freitext bleibt editierbar. Senkt die QA-Eingabezeit laut Session-Doku von ~15 s auf ~3 s.
- **Scan-Flash-Feedback** in `pwa/js/feedback.js` + `pwa/css/app.css`: Vollbild-Farbflash grün (`scan-flash--success`) / rot (`scan-flash--error`), CSS-Keyframe `scan-flash-in-out` über **400 ms**, GPU-kompositierte Opacity-Animation, `z-index: 9999`, `pointer-events: none`.
- **State-Aware CTA** in `pwa/js/app.js` (`renderQueueOverview`): der Dashboard-Button passt sein Label an den Zustand an:
  - `Fortsetzen: WH/OUT/XXX` (aktives Picking),
  - `Nächsten Prio-Pick starten (N dringend)` (es gibt dringende Pickings),
  - `Picking starten` (Default).
- **Font-Vergrößerung der Location** in `pwa/css/app.css`: von `1.05rem` auf **`1.3rem`** (≈ +23 %), Label von `0.7rem` auf `0.8rem`. Begründung: Lesbarkeit von WH/RACK/BIN auf Armlänge bei typischem Lagerlicht (~50 Lux).

> [!info] Detail-Quelle
> Vollständige Code-Snippets dieser UI-Änderungen stehen in `docs/SESSION_2026-03-31_UI_HARDENING.md`. PWA-Aufbau: [[08 - PWA & Voice-Pfad]].

---

## Phase 3 — Hardening & n8n-Pipeline

> [!note] Commits (Commit-eigene Bezeichnung "phase5")
> `3698656` `feat(phase5): hardening + safe AI rollout — resource caps, error workflow, AI evaluation lifecycle` · `dbaf055` `feat(phase5): n8n hardening, PWA UI overhaul, workflow backups & Projektbeschreibung`. Der eingefrorene Vertrag ist in `docs/N8N_CONTRACT_FREEZE_V1.md` festgehalten.

**Was gebaut wurde (n8n-Härtung):**

- **Ressourcen-Caps** für den n8n-Container (in `docker-compose.yml`), um einen einzelnen Container daran zu hindern, den Stack zu destabilisieren.
- **Healthcheck-Gate:** das Import-Skript wartet auf die n8n-Health, bevor Workflows aktiviert werden.
- **Circuit Breaker** (ADR-006): drei Fehlversuche öffnen einen 60-Sekunden-In-Memory-Lock; Folgeanfragen fallen sofort auf den lokalen FastAPI-Fallback zurück.
- **Error-Trigger-Workflow:** zentrale n8n-Fehlerbehandlung, die nach Quellworkflow verzweigt; erlaubte Writebacks `POST /api/internal/n8n/quality-assessment-failed` und `POST /api/internal/n8n/manual-review-activity`.
- **HMAC-Callback-Schutz:** write-relevante interne Callbacks verlangen den Pflichtheader `X-N8N-Callback-Secret` (+ `Idempotency-Key`).
- **Workflow-Verifikation:** `python infrastructure/scripts/verify-workflows.py` prüft die Verträge zwischen `n8n/workflows/*.json` und den `n8n.fire(...)`-Payloads im Backend (auch als `make verify-workflows`).

**Quality-Alert-KI-Felder (Welle A) — Datenmodell-Erweiterung** (belegt in `docs/ARCHITECTURE.md` + `docs/QUALITY_ALERT_AI_FIELDS.md`):

| Feld | Typ/Rolle | Sichtbares Label in Odoo |
|------|-----------|--------------------------|
| `description` | Originalbeschreibung des Pickers (unverändert) | — |
| `ai_evaluation_status` | technischer Status: `pending` → `completed`/`failed` | `Analyse-Status` |
| `ai_disposition` | Einstufung: z. B. `sellable`, `rework`, `quarantine`, `scrap` | `Einstufung` |
| `ai_recommended_action` | konkrete operative Empfehlung | (im Hauptblock) |
| `ai_last_analyzed_at` | Zeitstempel des letzten erfolgreichen KI-Writebacks | `Analysiert am` |
| `ai_confidence` | numerischer Konfidenzwert | — |
| `ai_summary` | interne System-Begründung (gehört in Chatter, nicht in Hauptblock) | — |
| `ai_enhanced_description` | sprachlich bereinigte Fassung, **ohne neue Fakten** (optional) | — |
| `ai_photo_analysis` | reiner visueller Bildbefund, **ohne** Empfehlung (optional) | — |
| `ai_failure_reason` | Begründung bei fehlgeschlagenem Dispatch | — |

Der sichtbare Odoo-Hauptblock heißt **`Systembewertung`** und zeigt nur: `ai_evaluation_status`, `ai_disposition`, `ai_recommended_action`, `ai_last_analyzed_at`.

**Produktive n8n-Workflows** (`n8n/workflows/`, belegt in `docs/N8N_CONTRACT_FREEZE_V1.md`):

| Workflow | Rolle |
|----------|-------|
| `quality-alert-created` | FastAPI feuert Event → n8n bewertet heuristisch → Writeback `POST /api/internal/n8n/quality-assessment` |
| `shortage-reported` | Replenishment-Logik → Writeback `POST /api/internal/n8n/replenishment-action` |
| `voice-exception-query` | Sync-Assist (Request-Reply); in Stufe 1 keine fachliche Antwortlogik-Änderung |
| `pick-confirmed` | in Stufe 1 nur als Vertrags-/Syntaxobjekt behandelt (kein funktionaler Umbau) |
| `error-trigger` | n8n-interner Fehlerpfad |

> [!note] N8N_CONTRACT_FREEZE_V1 — der eingefrorene Vertrag
> Um Regressionen im bestehenden `FastAPI + PWA + Odoo + n8n`-Stand zu vermeiden, wurde der Stufe-1-Vertrag eingefroren (`docs/N8N_CONTRACT_FREEZE_V1.md`):
> - **FastAPI bleibt die einzige Writeback-Grenze zu Odoo** — direkte Odoo-Writebacks aus n8n sind in produktiven Flows verboten.
> - **Whitelist** erlaubter Backend-Writebacks: `POST /api/internal/n8n/quality-assessment`, `…/replenishment-action`, `…/quality-assessment-failed`, `…/manual-review-activity`, `POST /api/integration/log`. (`POST /api/obsidian/log` ist nur noch Legacy-Alias.)
> - `correlation_id` = Trace-ID; `Idempotency-Key` = Replay-/Dedupe-Schlüssel. Bei write-relevanten async Callbacks müssen beide **identisch** sein.
> - Neue/angefasste Producer senden `schema_version: "v1"`; Legacy-Producer ohne Version werden als `legacy_payload=true` geloggt.

> [!info] Detail-Quelle
> n8n-Verträge, Circuit Breaker und HMAC-Secret: [[07 - n8n]].

---

## Phase 4 — Mobile-First & PWA-Refresh

> [!note] Commit
> `d27685d` `feat(pwa): mobile-first refresh — dense layout, German umlauts, product images, resume/online reload`.

**Was gebaut wurde:**

- **Kompakt-/dichtes Layout** für kleine Screens (kleinerer Header, Filterzeile, Listenansicht).
- **Deutsche UI** mit echten Umlauten statt ASCII-Ersatz (z. B. *Bestätigen, Zurück, Störung, Priorität*).
- **Produktbilder:** Thumbnails in der Liste, größeres Bild in der Detailansicht.
- **Resume/Online-Trigger:** gezieltes Neuladen von List/Detail beim Wiedereinstieg statt Dauer-Polling.
- **Offline-First-Verfeinerung** der PWA (Service-Worker-Caching für Assets, nicht für `/api/*`).

> [!info] Detail-Quelle
> Service-Worker-Strategie und Offline-Verhalten: [[08 - PWA & Voice-Pfad]].

---

## Phase 5 — Desktop & Accessibility

> [!note] Commits
> `c2863fe` (2026-04-21) `feat(pwa): desktop layout, umlaut fixes, emoji nav, list view toggle` · `84d13e8` (2026-04-22) `feat(pwa): implement responsive redesign & accessibility fixes`. Snapshot davor: `4eae52c` `chore: snapshot current state before desktop UI improvements`.

**Was gebaut wurde:**

- **Desktop-Layout:** responsives Layout für größere Viewports (zusätzlich zum Mobile-First-Stand).
- **Umlaut-Fixes** in der UI-Logik: `Stueck → Stück`, `Bestaetigen → Bestätigen`, `Naechster → Nächster`, `Stoerung → Störung`.
- **Emoji-Navigation:** Symbole für Voice/Scan/Problem in der Navigationsleiste.
- **List-View-Toggle:** Umschalten zwischen Einzel- und Listenansicht der Move-Lines.
- **Accessibility-Fixes** (responsive Redesign): Kontrast, Touch-Targets und semantische Korrekturen (vgl. die A11y-Anforderungen `make verify-a11y` / Axe + Playwright in `CLAUDE.md`).
- **Visual-Baselines:** Playwright-Snapshots wurden für die neuen Layouts aktualisiert (`make test-visual-diff-update`).

> [!info] Detail-Quelle
> Dev-/Test-Workflow (Playwright, Axe, Visual-Diff): [[04 - Dev-Workflow Code ändern]].

---

## Phase 6 — TTS & Intent-Expansion

> [!note] Commit (exakt belegt)
> `a17a06a` (2026-04-23, Author-Datum *Thu Apr 23 20:08:59 2026 +0200*) `feat(voice): Piper TTS, erweiterte Intent-Engine und Login-Begrüßung`. Geänderte Kerndateien: `backend/app/services/piper_client.py` (neu), `backend/app/services/intent_engine.py`, `backend/app/routers/voice.py`, `piper/Dockerfile` + `piper/server.py` (neu), `docker-compose.yml`, `pwa/js/voice.js`, `pwa/js/app.js`.

**Was gebaut wurde (laut Commit-Body, belegt):**

- **Piper TTS als Docker-Service** mit der Stimme **`thorsten-high`** (natürliche deutsche Stimme) und **automatischem Fallback auf Browser-TTS**, falls Piper nicht verfügbar ist.
- **Intent-Engine erweitert:** **60+ neue Aliases**; die Fuzzy-Schwellen wurden gesenkt: **0.78 → 0.73** und **0.72 → 0.68** (empfindlichere Erkennung).
- **Neuer Voice-Befehl `confirm_all`:** bestätigt alle verbleibenden Picking-Zeilen auf einmal.
- **Audio-Tuning:** `SPEECH_RMS` **25 → 18** (empfindlicher), `MIN_SPEECH_MS` **150 → 100**, Cooldown **900 → 500 ms**.
- **Login-Begrüßung:** "Guten Morgen/Tag/Abend [Vorname]" beim Profil-Klick.
- **TTS-Texte gekürzt** und natürlicher gestaltet.

> [!warning] Quellen-Differenz beim TTS-Engine-Stand
> `docs/VOICE_COMMANDS.md` nennt als TTS-Engine noch **"Browser SpeechSynthesis (de-DE)"** und Audio-Parameter mit den **alten** Werten (z. B. `RMS > 25`, `Min. Sprechdauer 150ms`). Der spätere Commit `a17a06a` führt **Piper als primäre TTS** ein (Browser nur noch Fallback) und senkt die Parameter (RMS 18, 100 ms). **Interpretation:** `docs/VOICE_COMMANDS.md` bildet den Stand **vor** Phase 6 ab; der Commit `a17a06a` ist der aktuellere Beleg. Für die Bachelorarbeit gilt der Commit-Stand als der spätere.

> [!info] Detail-Quelle
> Kompletter Voice-Pfad von STT (Whisper) bis TTS (Piper + Fallback): [[08 - PWA & Voice-Pfad]].

---

## Phase 7 — Deployment-Vorbereitung & Diagramm-Konsolidierung

> [!note] Commits (chronologisch zuverlässig datiert, Mai 2026)
> Deployment-Strang (alle 2026-05-06 bis 2026-05-09): `2a8a8c1` `docs: refresh public README`, `d082d74` `chore: harden deployment defaults`, `aa48c53` `docs: plan quality vision workflow`, `687a391`/`b0ccc85`/`4e00d98` (Hostinger-VPS-Runbook & Ressourcenplan), `980917d` `docs: record deployment decision log`, `af67638`/`b109c24` (Workspace-Cleanup), `cfe64eb` `docs: record local development learnings`. Stabilisierung: `27ea056` (2026-05-15) `Fix local Docker dev stack startup`. Diagramm: `3519a11`→`f52faf2`→`5d6c6cf`→`d16a793` (2026-05-19) Architektur-Diagramm + Odoo-n8n-Trigger-Doku.

> [!info] Einordnung
> Diese Phase ist in der ursprünglichen Quell-Skizze nicht als eigene "Phase 7" benannt, ergibt sich aber klar aus dem `git log` (April-/Mai-Commits nach Phase 6). Inhaltlich geht es **nicht** mehr um neue Fachfunktionen, sondern um **Produktionsreife**: Deployment-Planung (Hostinger VPS), gehärtete Deployment-Defaults, Aufräumen portabler Tooling-Artefakte, Stabilisierung des lokalen Docker-Dev-Stacks und die Konsolidierung des Architektur-Diagramms (siehe `Projekt-Wiki/_attachments/architektur.png`). Eine geplante "Quality Vision Workflow"-Erweiterung ist als Doku angelegt (`aa48c53`), aber **nicht** als produktiver Flow umgesetzt.

---

## Wellen & Hotfixes

### Welle A — Quality-Alert-KI-Bewertung (im Repo umgesetzt, nicht live)

> [!note] Quelle
> `docs/ARCHITECTURE.md` (Abschnitt *Quality Alert mit Welle A* und *Runtime-Hinweis*) + `docs/QUALITY_ALERT_AI_FIELDS.md`.

**Was Welle A umfasst:**

- Aufräumen/Definition des Odoo-Hauptblocks `Systembewertung` (nur 4 Felder sichtbar, Rest in Chatter).
- Erweiterung des Datenmodells um `ai_enhanced_description` und `ai_photo_analysis` (beide optional, mit klarer Semantik: bereinigter Text *ohne neue Fakten* bzw. reiner Bildbefund *ohne Empfehlung*).
- Erweiterung des internen Writeback-Vertrags `quality-assessment`.
- KI-Chatter als **Klartext** (nicht mehr als HTML-Fragment).
- Heuristik-Fallback wird beibehalten (kein OpenAI-Zwang).

**Der vollständige Welle-A-Fluss** (`docs/ARCHITECTURE.md`):

1. PWA → `POST /api/quality-alerts`
2. FastAPI erstellt `quality.alert.custom` in Odoo
3. FastAPI → n8n `quality-alert-created`
4. Nur bei erfolgreicher Übergabe setzt FastAPI `ai_evaluation_status = pending`
5. Scheitert die Übergabe → `failed` + Grund in den Chatter
6. n8n bewertet heuristisch und ruft `POST /api/internal/n8n/quality-assessment` auf
7. FastAPI schreibt die KI-Felder kontrolliert nach Odoo zurück

> [!warning] Welle A ist im Repo, aber noch nicht live sichtbar
> Laut `docs/ARCHITECTURE.md` (*Runtime-Hinweis*) bildet der Repo-Stand Welle A bereits ab. Für den **sichtbaren Live-Effekt** fehlen aber weiterhin: **(a)** das Odoo-Addon-Upgrade in der **aktiven Datenbank** und **(b)** der kontrollierte Import-/Aktivierungsabgleich des aktualisierten `quality-alert-created`-Workflows.

> [!note] Was NICHT Teil von Welle A ist
> Keine Mobile-Diktierfunktion, kein Draft-Enhancement-Flow, keine echte Vision-Pipeline, kein erzwungener OpenAI-Einsatz. Welle A ist bewusst eine additive, heuristisch abgesicherte Erweiterung.

### Hotfixes (chronologisch quer durch die Phasen)

> [!note] Quelle
> Im Detail protokolliert in `docs/SESSION_2026-03-31_UI_HARDENING.md` (Abschnitt B1 + *Error Diagnosis Chain*) sowie aus den frühen iOS-Beobachtungen.

| Hotfix | Symptom | Maßnahme |
|--------|---------|----------|
| **iOS Service Worker Cache** | SW fing `/api/*` ab → `null respondWith` | nur Assets cachen, API nie abfangen |
| **iOS TTS-Race** | nächste Ansage startete zu früh nach `cancel()` | ~80 ms Verzögerung vor Neustart |
| **Obsidian-Endpunkt** | Node "Log To Obsidian" rief nicht existierendes `/api/obsidian/log` → 422/500, QA-Status immer "Error" | Node + Connection aus `n8n/workflows/quality-alert-created.json` entfernt |
| **Falsche `errorWorkflow`-Referenz** | `"error-trigger"` (Name) statt ID → nicht gefunden | korrekte Workflow-ID `99fa93a638824b84b8578e4c8942c419` gesetzt |
| **Frozen-Addon-Schutz** | Linter fügte nicht existierende Felder `ai_enhanced_description`/`ai_photo_analysis` in `odoo/addons/quality_alert_custom/models/quality_alert.py` ein → 502 bei Schreibzugriff | Modell auf eingefrorenen Originalstand zurückgesetzt |
| **502 bei Quality Assessment** | Backend schrieb unautorisierte Odoo-Spalten in `backend/app/routers/n8n_internal.py` (`_build_quality_write_values`) | unautorisierte Writes entfernt → `POST /api/internal/n8n/quality-assessment` liefert wieder `200 OK` |

> [!info] Warum die Frozen-Addon-Regel existiert
> Custom-Odoo-Modelle in Produktion brauchen DB-Migrationen. Werden Felder ohne Migration ergänzt, scheitern Schreibzugriffe mit `502 Bad Gateway`, weil die Spalte in der DB fehlt. Daher: keine manuellen Model-Edits am eingefrorenen `quality_alert_custom`; neue Felder nur über Odoo Studio oder Migrationsdatei (siehe `SESSION_2026-03-31`, *Frozen Addon Protection Note*).

---

## Schlüsselentscheidungen als roter Faden

> [!note] Die acht Architektur-Invarianten (belegt in `CLAUDE.md` + `docs/ARCHITECTURE.md` + `docs/DECISIONS.md`)
> Diese Regeln galten über alle Phasen hinweg und erklären, *warum* viele Detailentscheidungen so getroffen wurden.

1. **Odoo ist System of Record** — keine Schatten-DB, keine doppelten Geschäftsdaten. *(CLAUDE.md, Invariante 1; ARCHITECTURE.md Regel 1)*
2. **FastAPI ist die einzige PWA-API** — `pwa/` spricht nie direkt mit Odoo oder n8n. *(CLAUDE.md, Invariante 2; ARCHITECTURE.md Regel 2)*
3. **n8n nicht im Voice-Hot-Path** — nur Exception-Assist (`/api/voice/assist`), read-only. *(ADR-003)*
4. **HTTPS-Pflicht im LAN** — für Kamera, Mikrofon und Service Worker. *(CLAUDE.md, Invariante 4)*
5. **Touch ist immer Fallback** — Voice und Scan nie die einzige Bedienweise. *(CLAUDE.md, Invariante 5; ARCHITECTURE.md Regel 5)*
6. **Keine externen Cloud-Dienste im Kern-Workflow** — STT bleibt lokal (Whisper). *(CLAUDE.md, Invariante 6)*
7. **n8n nur asynchron / kontrollierter Writeback** — fachliche Writes aus n8n laufen ausschließlich über interne FastAPI-Callbacks. *(ADR-005; ARCHITECTURE.md Regel 4)*
8. **Circuit Breaker** — 3 Fehler → 60 s Lock, dann lokaler Fallback. *(ADR-006)*

> [!info] Detail-Quelle
> Vertiefung aller Invarianten: [[02 - Architektur & Diagramm erklärt]].

---

## Technologie-Stack (Stand der Historie)

| Komponente | Technologie | Rolle |
|------------|-------------|-------|
| Frontend | Vanilla JS + HTML/CSS | Mobile PWA, offline-first |
| Backend | FastAPI (Python) | API, Odoo-Adapter (JSON-RPC), Intent-Engine |
| Datenbank | Odoo 18 Community | System of Record |
| Workflow-Engine | n8n | async Events, Exception-Assist |
| ASR/STT | Whisper (faster_whisper, small, lokal) | Spracherkennung |
| TTS | Piper (`thorsten-high`) + Browser-Fallback | Sprachausgabe (ab Phase 6) |
| Reverse Proxy | Caddy | HTTPS + URL-Routing |
| Infrastruktur | Docker Compose | lokaler Dev + LAN-Betrieb |

> [!info] Detail-Quellen
> Stack-/Container-Details: [[03 - Docker & Container]]. Begriffe wie ASR, STT, TTS, Idempotency, Circuit Breaker: [[10 - Glossar]].

---

## Status Juni 2026

> [!note] Kurzstand (belegt aus Git-Historie + `docs/ARCHITECTURE.md`)
> - **Phase 0–6:** alle abgeschlossen und committed; Phase 7 (Deployment-Vorbereitung) als Mai-Doku-Strang im Repo.
> - **Welle A:** im Repo umgesetzt, **Addon-Upgrade in der Live-DB noch ausstehend** (siehe Runtime-Hinweis in `docs/ARCHITECTURE.md`).
> - **Dokumentation:** `ARCHITECTURE.md`, `DECISIONS.md`, `N8N_CONTRACT_FREEZE_V1.md`, `PHASE_1_TRANSACTION_HARDENING.md`, `QUALITY_ALERT_AI_FIELDS.md`, `SESSION_2026-03-31_UI_HARDENING.md`, `VOICE_COMMANDS.md`.
> - **Verifikation:** Python-Tests (`make test`), Workflow-Vertragsprüfung (`make verify-workflows`), Playwright-E2E + Visual-Diff + Axe-A11y.
> - **Nächste Schritte:** gestufter n8n-Rollout (`backup → import → activate` über `infrastructure/scripts/import-workflows.sh`), Live-Smoke-Tests, Telemetrie-/Metriken-Export.

---

> [!info] Weiterlesen
> Zurück zur Übersicht: [[00 - Start Hier (Übersichtskarte)]]. Wer das System verstehen will, beginnt mit [[01 - Was ist das Projekt & wie es anfing]] und [[02 - Architektur & Diagramm erklärt]].
