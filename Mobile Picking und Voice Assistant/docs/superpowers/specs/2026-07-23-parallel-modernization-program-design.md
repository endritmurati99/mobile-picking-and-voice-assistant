# Design Spec: Parallel Modernization Program

- **Datum:** 2026-07-23
- **Status:** Vom User als Programmdesign freigegeben; schriftlicher Review vor Ausfuehrungsplanung
- **Projekt:** `Mobile Picking und Voice Assistant`
- **Ausgangsbranch:** `codex/cluster-odoo19-hardening`
- **Ausgangs-HEAD:** `9d4790a8c8ab2cf344a5ca2e72118138e07eaf01`

---

## 1. Entscheidung

Die offenen Baustellen werden nicht in mehreren Terminals innerhalb derselben
Arbeitskopie bearbeitet. Das Programm nutzt stattdessen:

1. einen zentralen Integrations-Worktree,
2. genau einen isolierten Worktree pro Workstream,
3. exklusiven Dateibesitz fuer gemeinsam genutzte Integrationsdateien,
4. einen eigenen Design-Spec- und Implementierungsplan-Zyklus pro
   Teilprojekt,
5. parallele Unit-, Contract- und Mock-Tests, aber seriell ausgefuehrte
   Docker-, Odoo-, n8n- und Browser-Live-Tests.

Der primaere Checkout wird einmalig fuer den pfadgenauen Bootstrap-Commit
der freigegebenen Programm- und Foundation-Specs verwendet. Danach bleibt er
eingefroren. Feature-Agenten arbeiten weder im primaeren Checkout noch
direkt auf dem Integrationsbranch.

## 2. Zielbild

Das Programm liefert einen belastbaren Odoo-19-basierten mobilen
Lagerprozess mit:

- abgesicherten PWA-, FastAPI-, Odoo- und n8n-Grenzen,
- reproduzierbarer Odoo-19-Migration und Rueckfallstrategie,
- asynchroner visueller Qualitaetsbewertung mit lokalem Vision-Modell,
- idempotenter Versandlabel-Erstellung nach erfolgreichem Packabschluss,
- sicherem Voice-v2-Assistenten mit deterministischer Kommandoebene,
- mobiler und partiell offline-faehiger PWA,
- belastbarem Cluster-Picking und Seriennummernhandling,
- pruefbaren End-to-End-Vertraegen und einem kontrollierten Rollout.

Odoo bleibt das System of Record. Die PWA spricht nur mit FastAPI. n8n
orchestriert asynchrone Prozesse, ist aber weder App-Backend noch
Sicherheitsgrenze fuer Voice-Kommandos.

## 3. Bewertete Ausfuehrungsmodelle

### 3.1 Mehrere Terminals im selben Checkout

Der Start waere schnell, aber `pwa/js/app.js`, `docker-compose.yml`,
`backend/app/config.py`, `backend/app/dependencies.py` und die
n8n-Importskripte wuerden von mehreren Spuren gleichzeitig veraendert.
Ueberschreibungen und schwer nachvollziehbare Misch-Commits waeren
wahrscheinlich. Dieses Modell wird nicht verwendet.

### 3.2 Isolierte Worktrees mit zentralem Integrator

Jeder Workstream besitzt einen Branch und einen Worktree. Gemeinsame Dateien
haben genau einen Eigentuemer. Der Integrator fuehrt die Branches in
festgelegter Reihenfolge zusammen und startet die gemeinsamen Live-Gates.
Dieses Modell ist gewaehlt.

### 3.3 Serielle Umsetzung

Eine einzelne Spur waere konfliktarm, wuerde aber voneinander unabhaengige
Arbeiten wie Odoo-Faktenpruefung, Voice-Evaluation und n8n-Workflowtests
unnuetig blockieren. Dieses Modell bleibt nur fuer Live-Stack- und
Rollout-Schritte bestehen.

## 4. Bestehende Arbeit und kanonische Dokumente

Vorhandene Dokumente werden aktualisiert oder referenziert, nicht blind
dupliziert:

| Bereich | Kanonische Grundlage | Entscheidung |
| --- | --- | --- |
| Odoo 19 / Cluster | `docs/superpowers/specs/2026-07-08-cluster-picking-odoo19-hardening-design.md` | Um Runtime-Fakten, Migrationsstatus und Verifikationsnachweis ergaenzen |
| Voice v2 | `docs/superpowers/specs/2026-06-27-voice-v2-hybrid-nlu-evaluation-design.md` | Auf Odoo 19 und aktuelle Sicherheitsvertraege aktualisieren |
| PWA Review | `docs/superpowers/plans/2026-06-28-pwa-review-gate-fix.md` | Als abgeschlossenen visuellen Baseline-Nachweis referenzieren |
| Seriennummern | `docs/superpowers/plans/2026-07-01-seriennummer-retouren-haertung.md` | Offene Exception- und Live-Odoo-19-Punkte weiterfuehren |
| Alte Parallel-Chats | `docs/parallel-chats/README.md` und `CHAT-*.md` | Nur als historisches Ownership-Muster verwenden |
| Visuelle Qualitaet | keine dedizierte Spec vorhanden | Neue Design-Spec und neuer Plan |
| Versandlabels | bisher explizit nicht im Scope | Neue Design-Spec und neuer Plan |
| Plattformvertraege | keine zentrale Spec vorhanden | Erste neue Teilprojekt-Spec |

Historische Odoo-18-Annahmen, alte Branch-Hashes, freie
`lot_name`-Erzeugung und rein logische Clusterboxen sind nicht mehr
autoritativ.

## 5. Workstreams und exklusiver Dateibesitz

### 5.1 Platform Contracts and Security

Exklusiver Besitz:

- `docker-compose.yml` nach dem Odoo-19-Faktengate und formalen Handoff
- `.env.example`
- `backend/app/config.py`
- `backend/app/dependencies.py`
- `backend/app/main.py`
- `backend/app/models/n8n.py`
- `backend/app/services/n8n_webhook.py`
- `backend/app/routers/n8n_internal.py`
- neue Auth-, HMAC-, Event- und Dispatcher-Module
- `odoo/addons/picking_assistant_integration/**`
- nach dem Odoo-19-Handoff
  `odoo/addons/picking_assistant_core/**`
- `n8n/custom-nodes/**`
- `infrastructure/caddy/Caddyfile`
- `infrastructure/scripts/init-n8n-db.sql`
- einmaliges Migrationsskript/Runbook fuer die bestehende n8n-Datenbankrolle
- n8n-Credential-Provisioning
- `infrastructure/scripts/import-workflows.sh`
- `infrastructure/scripts/verify-workflows.py`
- `backend/tests/conftest.py` und gemeinsame Integrationsfixtures
- zentrale Event-, Outbox- und Security-Tests

Andere Workstreams liefern Aenderungsanforderungen an diese Spur, bearbeiten
die Dateien aber nicht selbst.

### 5.2 Odoo 19 Cutover

Exklusiver Besitz:

- `odoo/Dockerfile`
- `docker-compose.yml` bis zum Odoo-19-Faktengate und Merge
- Odoo-Konfigurationen
- `odoo/addons/**` ausser den neuen Add-ons
  `picking_assistant_integration`, `picking_assistant_visual_quality` und
  `picking_assistant_shipping`
- `odoo/addons18/**`
- Odoo-Migrations-, Upgrade- und Seed-Skripte
- Odoo-19-Runtime-Fakten und Cutover-Nachweise

Nach dem Odoo-19-Merge ist dieser Dateibesitz beendet. Visual Quality und
Shipping besitzen danach ausschliesslich ihre neuen Add-ons; Foundation
besitzt das Integrations-Add-on und uebernommene Core-Idempotenzdateien.

### 5.3 n8n Visual Quality

Exklusiver Besitz:

- `n8n/workflows/quality-alert-created.json`
- neuer Workflow fuer die visuelle Bewertung
- vision-spezifische n8n-Helfer
- neuer Router `backend/app/routers/n8n_quality.py`
- `backend/app/models/quality.py`
- neues Add-on `odoo/addons/picking_assistant_visual_quality/**` nach dem
  Odoo-19-Faktengate
- dedizierte Workflow- und Contract-Tests

Die Spur darf keine gemeinsamen Callback-, Config-, Compose-, Import- oder
Verifier-Dateien direkt aendern.

### 5.4 Voice v2 Safe Assistant

Exklusiver Besitz:

- `backend/app/routers/voice.py`
- `backend/app/models/voice.py`
- `backend/app/services/intent_engine.py`
- `backend/app/services/whisper_client.py`
- `backend/app/services/piper_client.py`
- neue voice-spezifische LLM- und Evaluationsmodule
- `pwa/js/voice*.js`
- `pwa/js/voice*.mjs`
- Voice-Tests

Die Spur liefert ein PWA-Adapter-Interface. Sie integriert nicht selbst in
`pwa/js/app.js`. Foundation behaelt `backend/app/models/n8n.py`; Voice
verschiebt Voice-spezifische Request-/Response-Typen in
`backend/app/models/voice.py`, nachdem Foundation gelandet ist.

### 5.5 Cluster and Serial Concurrency

Exklusiver Besitz:

- `backend/app/services/cluster_service.py`
- `backend/app/services/serial_validation.py`
- `backend/app/services/picking_service.py`
- `backend/app/routers/cluster.py`
- dedizierte Backend- und E2E-Tests

Gemeinsame Router-, Config- oder PWA-Dateien werden ueber den Integrator
geaendert.

### 5.6 n8n Shipping Labels

Exklusiver Besitz:

- neuer Shipping-Label-Workflow
- neuer Carrier-Adapter auf Workflow-Seite
- neuer Router `backend/app/routers/n8n_shipping.py`
- neues Add-on `odoo/addons/picking_assistant_shipping/**` nach dem
  Odoo-19- und Cluster-Abschlussgate
- label-spezifische Helfer und Tests

Die Spur aendert weder Workflow-Importer noch Callback-Router oder Compose.
Die Integration erfolgt ueber die in der Foundation-Spec eingefrorenen
Events.

### 5.7 PWA Mobile and Offline

Exklusiver Besitz:

- `pwa/js/app.js`
- `pwa/js/api.js` nach der einmaligen Foundation-Umstellung auf Session und
  CSRF
- `pwa/js/pwa.js`
- `pwa/sw.js`
- `pwa/js/ui.js`
- `pwa/index.html`
- `pwa/manifest.json`
- `pwa/css/app.css`
- gemeinsame PWA-E2E-Mocks

Diese Spur ist der einzige Eigentuemer von `pwa/js/app.js`. Voice, Cluster,
Visual Quality und Shipping liefern Module und Vertraege, die hier
integriert werden. Die Foundation passt `pwa/js/api.js` in Welle 1 einmalig
an; die PWA-Spur startet von diesem Integrationsstand und besitzt die Datei
danach exklusiv.

## 6. Abhaengigkeiten und Arbeitswellen

### 6.1 Welle 0: Contract Freeze

Vor Feature-Code wird die Foundation-Spec freigegeben und geplant. Sie
friert ein:

- Picker-Authentifizierung,
- n8n-Ingress- und Callback-Authentifizierung,
- versionierte Event-Envelopes,
- Odoo-Instanzrouting,
- Idempotenz und persistente Outbox,
- Netzwerk- und Portgrenzen,
- Registry fuer Workflows, Callbacks und Events.

Die Vertragsdefinition muss abgeschlossen sein, bevor Visual Quality oder
Shipping gegen produktive Schnittstellen implementiert werden.

### 6.2 Welle 1: Parallele Grundlagen

Vier aktive Spuren:

1. Der Integrator implementiert Platform Contracts and Security auf Basis
   des eingefrorenen Vertrags und rebased diese Spur vor dem Merge auf den
   Odoo-19-Stand. Vor dem Odoo-Handoff veraendert diese Spur
   `docker-compose.yml` oder bestehende Odoo-Core-Add-ons nicht.
2. Ein Agent bearbeitet Odoo 19 Cutover.
3. Ein Agent bearbeitet Voice v2 Backend und isolierte Voice-Module.
4. Ein Agent bearbeitet n8n Visual Quality gegen Mock-Vertraege.

Visual Quality darf in dieser Welle Workflow, Adapter und Tests liefern.
Odoo-Addon- und zentrale Callback-Aenderungen landen erst nach dem
Odoo-19- beziehungsweise Platform-Gate.

Integrationsreihenfolge:

1. Odoo 19 Cutover und Runtime-Faktengate
2. Platform Contracts and Security
3. n8n Visual Quality
4. Voice v2 Safe Assistant

Die produktive Foundation ist Odoo-19-only. Odoo 18 bleibt waehrend der
Migration im Legacy-v1-Pfad und erhaelt keinen Dual-Port des neuen
Integrations-Add-ons. Der Odoo-19-Track uebergibt nach seinem Merge
`docker-compose.yml` und die Odoo-Addon-Flaeche formal an Foundation.
Foundation aktiviert Session, Outbox oder v2-Callbacks erst auf dem
verifizierten Odoo-19-Profil.

### 6.3 Welle 2: Fachliche Prozesse und PWA

Drei Agentenspuren plus Integrator:

1. Cluster and Serial Concurrency
2. n8n Shipping Labels
3. PWA Mobile and Offline

Shipping entwickelt gegen das eingefrorene Packabschluss-Event. Bei der
Integration landet Cluster/Serial vor Shipping, damit der reale
Abschlusszeitpunkt autoritativ ist. PWA landet zuletzt, weil diese Spur alle
Frontend-Adapter zusammenfuehrt und anschliessend den Service-Worker-Cache
versioniert.

Integrationsreihenfolge:

1. Cluster and Serial Concurrency
2. n8n Shipping Labels
3. PWA Mobile and Offline

### 6.4 Welle 3: Kontrollierte Integration und Rollout

Seriell:

1. Odoo-19-Testdatenbank sichern und upgraden.
2. Add-ons aktualisieren und Seed-Smokes ausfuehren.
3. n8n sichern und neue Workflows inaktiv importieren.
4. Workflows einzeln aktivieren und Callback-Vertraege pruefen.
5. Visual-Quality-End-to-End-Test ausfuehren.
6. Packen-zu-Label-End-to-End-Test ausfuehren.
7. Voice-Sicherheits- und Fehlbefehlstests ausfuehren.
8. PWA-Mobile-, Offline-, Screenshot- und Playwright-Gates ausfuehren.
9. Restart-, Netzwerk- und Degraded-Mode-Verhalten pruefen.

## 7. Worktree- und Branch-Modell

Worktrees werden ausserhalb des Repositories unter folgendem Stamm
angelegt:

```text
/mnt/c/Users/endri/Desktop/Bachelor-worktrees/
```

Geplante Zuordnung:

| Worktree | Branch |
| --- | --- |
| `00-integration-bachelor-hardening` | `codex/integration-bachelor-hardening` |
| `01-foundation-platform-contracts-security` | `codex/foundation-platform-contracts-security` |
| `02-odoo19-cutover` | `codex/odoo19-cutover` |
| `03-n8n-visual-quality` | `codex/n8n-visual-quality` |
| `04-voice-v2-safe-assistant` | `codex/voice-v2-safe-assistant` |
| `05-cluster-serial-concurrency` | `codex/cluster-serial-concurrency` |
| `06-n8n-shipping-labels` | `codex/n8n-shipping-labels` |
| `07-pwa-mobile-offline` | `codex/pwa-mobile-offline` |

Der Integrationsbranch wird vom Ausgangs-HEAD
`9d4790a8c8ab2cf344a5ca2e72118138e07eaf01` abgeleitet. Nach schriftlicher
Freigabe und Commit der Programm- und Foundation-Spec wird der resultierende
Commit als unveraenderlicher `WAVE1_BASE` festgehalten. Welle 2 startet vom
vollstaendig verifizierten Integrationsstand nach Welle 1.

Der ungetrackte Repository-Nachbar `graphify/` und alle `.serena/**`-Dateien
werden nicht in Feature-Commits aufgenommen. Es wird ausschliesslich
pfadgenau gestaged; `git add .` und `git add -A` sind verboten.

## 8. Agenten- und Terminalbetrieb

- Maximal drei Feature-Agenten arbeiten parallel; der vierte aktive Slot
  bleibt beim Integrator.
- Jeder Agent erhaelt genau einen Workstream, erlaubte Pfade, eine Spec,
  einen Plan und konkrete Verifikationsbefehle.
- Agenten bearbeiten keine fremden Worktrees oder Branches.
- Nur der Integrator schreibt auf dem Integrationsbranch.
- Docker-Compose-, Odoo-, n8n- und Playwright-Live-Laeufe werden nicht
  parallel gestartet.
- Ein manuelles Zusatzterminal ist nur fuer gemeinsame Live-Logs oder
  kontrollierte Rollout-Schritte vorgesehen, nicht als weiterer
  unkoordinierter Code-Writer.

## 9. Dokumentations- und Fortschrittsprotokoll

Jedes Teilprojekt durchlaeuft:

1. Brainstorming und Designfreigabe,
2. eigene Spec unter `docs/superpowers/specs/`,
3. schriftlichen User-Review,
4. eigenen Writing-Plan unter `docs/superpowers/plans/`,
5. taskweise TDD-Ausfuehrung mit kleinen Commits,
6. Track-Verifikation,
7. Integrationsreview und gemeinsame Gates.

Der Integrator besitzt allein:

```text
docs/superpowers/parallel/2026-07-23-program-status.md
```

Der Status enthaelt pro Workstream:

- Branch und Worktree,
- Spec- und Planpfad,
- aktuellen Commit,
- laufende beziehungsweise bestandene Tests,
- Blocker,
- Integrationsstatus,
- Rollback-Punkt.

Feature-Agenten aktualisieren nur ihre eigene Spec, ihren eigenen Plan und
ihre eigenen Testnachweise.

Formale Handoffs:

- Odoo 19 uebergibt Compose und bestehende Odoo-Core-Add-ons an Foundation.
- Visual Quality und Shipping liefern Router-Registrierungs- und
  Workflow-Registry-Deltas an Foundation.
- Foundation allein integriert `backend/app/main.py`,
  `backend/tests/conftest.py`, gemeinsame Fixtures, Compose, Workflow-
  Importer und Workflow-Verifier.

## 10. Verifikationsstrategie

### 10.1 Pro Workstream

Jeder Plan definiert:

- einen fehlschlagenden Test vor der Implementierung,
- fokussierte Unit- oder Contract-Tests,
- Negativ- und Replay-Faelle,
- exakte Befehle und erwartete Ergebnisse,
- einen separaten Commit je pruefbarem Deliverable.

### 10.2 Pro Integrationsmerge

Vor jedem Merge:

1. Feature-Branch gegen den aktuellen Integrationsbranch aktualisieren.
2. Track-Tests im Feature-Worktree ausfuehren.
3. Diff auf Pfadverletzungen und Secrets pruefen.
4. Mit `--no-ff` in der Integrations-Worktree mergen.
5. Betroffene Cross-Track-Tests erneut ausfuehren.

### 10.3 Gemeinsames Abschlussgate

Pflicht sind:

- komplette Backend-Tests,
- PWA-Unit-Tests,
- n8n-Contract- und Workflow-Verifikation,
- Odoo-19-Addon- und Seed-Smokes,
- PWA-Playwright auf Desktop und Mobile,
- visuelle Snapshot-Pruefung,
- Voice-Corpus- und Safety-Evaluation,
- Visual-Quality-Benchmark mit bekannten Bildern,
- Label-Replay-, Retry- und Reprint-Test,
- Restart- und Netzwerk-Smokes.

## 11. Fehler- und Rollback-Regeln

- Odoo-Upgrades erfolgen zuerst gegen eine Kopie der Datenbank.
- n8n-Workflows werden vor Import gesichert, inaktiv importiert und einzeln
  aktiviert.
- Service-Worker-Versionen werden erst nach vollstaendiger
  Frontend-Integration erhoeht.
- Asynchrone Events werden nicht bei Netzwerkfehlern verworfen.
- Label- und Quality-Callbacks muessen bei Wiederholung denselben
  fachlichen Zustand liefern und duerfen keine Duplikate erzeugen.
- Jede Welle besitzt einen dokumentierten Integrationscommit als
  Rueckfallpunkt.

## 12. Nicht im Scope dieses Programmdesigns

Dieses Dokument implementiert keine Features und ersetzt nicht die
Teilprojekt-Specs. Insbesondere werden hier nicht festgelegt:

- konkreter Carrier-Anbieter,
- konkretes Vision-Modell,
- finales Voice-Modell,
- visuelle Detailgestaltung einzelner PWA-Dialoge,
- Produktions-Cutover-Datum.

Diese Entscheidungen werden in den jeweiligen Teilprojekt-Specs anhand
messbarer Kriterien getroffen.

## 13. Akzeptanzkriterien

Das Parallelisierungsdesign gilt als erfolgreich umgesetzt, wenn:

- jeder Workstream einen isolierten Branch und Worktree besitzt,
- kein gemeinsamer Integrationspfad gleichzeitig von mehreren Agenten
  bearbeitet wird,
- jede Feature-Implementierung auf einer freigegebenen Spec und einem
  eigenen Writing-Plan basiert,
- der zentrale Status jederzeit Branch, Teststand und Blocker zeigt,
- alle Integrationen in der festgelegten Reihenfolge landen,
- Live-Stack-Tests seriell und reproduzierbar laufen,
- kein Feature-Commit `graphify/`, `.serena/**` oder fremde
  Arbeitskopie-Aenderungen enthaelt,
- der vollstaendige Abschlussgate-Nachweis vor einem Main-Merge vorliegt.
