# Cluster-Picking Abschluss — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `feat/cluster-picking` abnahmereif machen (Live-Test gegen echtes Odoo + lokaler Multi-Agent-Review + Fixes) und per Fast-Forward nach `main` bringen — inklusive der mitlaufenden Serial-Telemetrie- und PWA-Serial-Fixes.

**Architecture:** Der Branch `feat/cluster-picking` ist ein **linearer** Nachfahre von `origin/main` (`0048311`) und enthält bereits drei abgeschlossene Arbeitspakete in einem Strang: Serial-Telemetrie-Fix (`c9cf40e`/`ebd83db`), PWA-Bulk-Serial-Fix (`fd0d98b`) und das komplette Cluster-/Batch-Picking-Feature. Es wird **kein** neuer Feature-Code geschrieben außer Review-Fixes. Abschluss = verifizieren → reviewen → fixen → Fast-Forward-Merge → aufräumen → Nachverfolgbarkeit.

**Tech Stack:** FastAPI (Backend), pytest + pytest_asyncio, Playwright (e2e/PWA), Docker Compose (Stack), Odoo 18 `stock.picking.batch` (System of Record, DB `masterfischer`), Vanilla-JS PWA.

## Global Constraints

- Git-Repo-Root ist `C:\Users\endri\Desktop\Bachelor`; das Projekt liegt im Unterordner `Mobile Picking und Voice Assistant/`. Alle `make`/`npx`/`pytest`-Kommandos werden **aus dem Projekt-Unterordner** ausgeführt.
- Backend-Tests: `cd backend && PYTHONPATH=.deps python -m pytest -p pytest_asyncio tests/ -v` (oder `make test`).
- Playwright-Tests laufen unter Windows mit `npx.cmd playwright test <spec>`; der `webServer` (`python -m http.server 4173 --directory pwa`) startet automatisch, `reuseExistingServer: true`.
- Aktive Demo-DB: `masterfischer` (admin/admin), Picker „Max Picker" = uid 7. `.env` setzt `ODOO_DB=masterfischer`.
- Merge-Ziel ist `origin/main` (`0048311`), **nicht** das veraltete lokale `main` (`8bee236`, 38 Commits zurück).
- Merge-Strategie: **Fast-Forward** (kein `--no-ff`), damit die beschreibenden Commit-Messages beider Features in `main` erhalten bleiben.
- Nachverfolgbarkeit ist Pflicht (User-Standard): GitHub-Push + genaue Beschreibung + Memory + Obsidian.
- `picking_service.py` darf nur additiv/minimal berührt sein (laut Design unberührt; Diff zeigt +26/-? — im Review prüfen, dass keine Regression).
- Box-Zuordnung ist NUR logisch/visuell (Box N ↔ Auftrag N), KEINE echten Odoo-Packages.

---

### Task 0: Baseline verifizieren (keine Änderungen)

Stellt einen bekannten guten Stand her, bevor Live-Test und Review starten. Reiner Verifikationsschritt.

**Files:**
- Keine Änderungen.

**Interfaces:**
- Consumes: aktueller Checkout `feat/cluster-picking` (HEAD `87e459b`).
- Produces: Bestätigung „Working Tree sauber + alle Tests grün" als Voraussetzung für alle weiteren Tasks.

- [ ] **Step 1: Branch & Working Tree prüfen**

Run:
```bash
cd "/c/Users/endri/Desktop/Bachelor/Mobile Picking und Voice Assistant"
git branch --show-current && git status -sb
```
Expected: Branch `feat/cluster-picking`, synchron mit `origin/feat/cluster-picking`, nur untracked `docs/parallel-chats/`.

- [ ] **Step 2: Backend-Tests laufen lassen**

Run:
```bash
cd "/c/Users/endri/Desktop/Bachelor/Mobile Picking und Voice Assistant/backend" && PYTHONPATH=.deps python -m pytest -p pytest_asyncio tests/ -q
```
Expected: PASS, ~128 Tests grün (insb. `test_cluster_service.py`, `test_cluster_routes.py`, `test_picking_service.py`). Falls rot → Ursache notieren, vor Weitermachen stoppen.

- [ ] **Step 3: Cluster- + Serial-e2e laufen lassen**

Run:
```bash
cd "/c/Users/endri/Desktop/Bachelor/Mobile Picking und Voice Assistant" && npx.cmd playwright test e2e/cluster.spec.js e2e/serial-confirm.spec.js --reporter=list
```
Expected: PASS (beide Specs grün). Der HTTP-Server auf :4173 startet automatisch.

- [ ] **Step 4: Ergebnis festhalten**

Notiere Testanzahl + Status in den Arbeitsnotizen für den späteren Memory-/Obsidian-Eintrag. Kein Commit (keine Dateiänderung).

---

### Task 1: Live-Verifikation gegen echtes Odoo

Beweist, dass der Cluster-Flow nicht nur in Mocks, sondern gegen echtes `stock.picking.batch` in `masterfischer` funktioniert. Läuft zeitlich parallel zu Task 2 (Review-Agenten im Hintergrund).

**Files:**
- Keine Code-Änderungen (außer evtl. Bugfixes, die dann als Findings in Task 3 wandern).

**Interfaces:**
- Consumes: laufender Docker-Stack, Backend mit `ODOO_DB=masterfischer`.
- Produces: bestätigter End-to-End-Durchlauf (Batch erstellt → Boxen zugeordnet → Rundgang/Serial → confirm → `action_done`) + Liste etwaiger Laufzeit-Bugs.

- [ ] **Step 1: Stack starten**

Run:
```bash
cd "/c/Users/endri/Desktop/Bachelor/Mobile Picking und Voice Assistant" && docker compose up -d && docker compose ps
```
Expected: Container `odoo`, `backend`, `caddy`, `postgres`, `n8n` laufen (Status `Up`/`healthy`).

- [ ] **Step 2: Prüfen, ob `stock_picking_batch` in `masterfischer` installiert ist**

Run:
```bash
cd "/c/Users/endri/Desktop/Bachelor/Mobile Picking und Voice Assistant" && docker compose exec -T odoo odoo shell -d masterfischer --no-http <<'PY'
m = env['ir.module.module'].search([('name','=','stock_picking_batch')])
print('STATE:', m.state if m else 'NOT FOUND')
PY
```
Expected: `STATE: installed`.

- [ ] **Step 3: Falls NICHT installiert — Modul installieren**

Nur ausführen, wenn Step 2 nicht `installed` zeigt:
```bash
cd "/c/Users/endri/Desktop/Bachelor/Mobile Picking und Voice Assistant" && docker compose exec -T odoo odoo -d masterfischer -i stock_picking_batch --stop-after-init && docker compose restart odoo
```
Expected: Installations-Log endet ohne Fehler; danach Step 2 erneut → `STATE: installed`.

- [ ] **Step 4: Cluster-Flow gegen echtes Odoo durchspielen (e2e, nicht-gemockt)**

Voraussetzung: offene `assigned` Pickings für „Max Picker" (uid 7) vorhanden (laut Seed ~16). Falls nötig: `make seed` (mit `ODOO_DB=masterfischer`).
Run (UI-getrieben, sichtbar):
```bash
cd "/c/Users/endri/Desktop/Bachelor/Mobile Picking und Voice Assistant" && npx.cmd playwright test e2e/cluster.spec.js --headed --reporter=list
```
Expected: PASS. Beobachten: Batch-Erstellung, Box-Tags, Voice/Serial-Schritte, Abschluss-View.

- [ ] **Step 5: Im Odoo-Backend gegenchecken**

Run:
```bash
cd "/c/Users/endri/Desktop/Bachelor/Mobile Picking und Voice Assistant" && docker compose exec -T odoo odoo shell -d masterfischer --no-http <<'PY'
b = env['stock.picking.batch'].search([], order='id desc', limit=1)
print('BATCH', b.id, 'state=', b.state, 'pickings=', len(b.picking_ids))
print('PICKING states:', b.picking_ids.mapped('state'))
PY
```
Expected: Zuletzt verarbeiteter Batch ist `done`; zugehörige Pickings `done`.

- [ ] **Step 6: Laufzeit-Bugs notieren**

Jeden beim Live-Test gefundenen Fehler als Finding mit Schweregrad festhalten → fließt in Task 3 ein. Keine Fixes hier direkt.

---

### Task 2: Lokaler Multi-Agent-Review

Drei spezialisierte Agenten reviewen den vollen Feature-Diff parallel. Ihre Berichte werden in eine Findings-Datei zusammengeführt.

**Files:**
- Create: `docs/superpowers/reviews/2026-06-24-cluster-picking-review.md` (Findings-Sammlung)

**Interfaces:**
- Consumes: Diff `origin/main..feat/cluster-picking` (19 Dateien, u.a. `cluster_service.py`, `routers/cluster.py`, `pwa/js/app.js`, `pwa/js/api.js`, `pwa/css/app.css`).
- Produces: triagierte Findings-Liste (Severity high/medium/low + Datei:Zeile + Vorschlag), die Task 3 abarbeitet.

- [ ] **Step 1: Review-Scope festschreiben**

Run:
```bash
cd "/c/Users/endri/Desktop/Bachelor/Mobile Picking und Voice Assistant" && git diff --stat origin/main..feat/cluster-picking
```
Expected: 19 Dateien, ~3371 Insertions. Diese Liste ist der Review-Input.

- [ ] **Step 2: Drei Review-Agenten parallel dispatchen**

In EINER Nachricht drei Agenten starten (laufen nebenläufig zu Task 1):
- `everything-claude-code:security-reviewer` — Fokus: IDOR/Ownership-Gates in `cluster_service.py` + `routers/cluster.py`, CSS/JS-Injection in `app.js`/`app.css` (`safeColor`/`safeInt`), Authz-Parität. Prompt enthält den exakten Diff-Range `origin/main..feat/cluster-picking`.
- `everything-claude-code:code-reviewer` — Fokus: Korrektheit `confirm_cluster_line`/`validate_batch`/`action_done`-Wizard-Handling, `suggest_batches`-Heuristik, PWA-State (`app.js`), keine Regression in `picking_service.py`.
- `pr-review-toolkit:silent-failure-hunter` — Fokus: verschluckte Fehler / Fallbacks im Backend-Service und in den n8n-Event-Pfaden.

Jeder Agent gibt strukturierte Findings zurück (Severity, Datei:Zeile, Beschreibung, Fix-Vorschlag).

- [ ] **Step 3: Findings zusammenführen und triagieren**

Alle Agent-Ausgaben in `docs/superpowers/reviews/2026-06-24-cluster-picking-review.md` schreiben. Duplikate zusammenfassen, nach Severity sortieren, jedes Finding mit Status `offen` markieren.

- [ ] **Step 4: Findings-Datei committen**

```bash
cd "/c/Users/endri/Desktop/Bachelor/Mobile Picking und Voice Assistant"
git add docs/superpowers/reviews/2026-06-24-cluster-picking-review.md
git commit -m "docs(cluster): finaler Multi-Agent-Review — Findings gesammelt"
git push origin feat/cluster-picking
```
Expected: Commit + Push erfolgreich.

---

### Task 3: Findings fixen (TDD pro Finding)

Arbeitet die in Task 1 (Laufzeit) + Task 2 (Review) gesammelten high/medium-Findings ab. Exakter Code ist erst nach dem Review bekannt — daher ist dies ein **disziplinierter Prozess**, kein vorgeschriebener Patch. Low-Severity-Findings nur fixen, wenn risikolos; sonst als Backlog-Notiz dokumentieren.

**Files:**
- Modify: je nach Finding (`backend/app/services/cluster_service.py`, `backend/app/routers/cluster.py`, `pwa/js/app.js`, …)
- Test: je nach Finding (`backend/tests/test_cluster_service.py`, `backend/tests/test_cluster_routes.py`, `e2e/cluster.spec.js`)

**Interfaces:**
- Consumes: Findings-Liste aus Task 2 Step 3.
- Produces: alle high/medium-Findings auf `behoben` gesetzt; Tests grün; Branch gepusht.

**Pro Finding (wiederholen):**

- [ ] **Step 1: Fehlschlagenden Test schreiben**, der das Finding reproduziert (Backend: pytest-Fall in der passenden Testdatei; PWA-Verhalten: Playwright-Fall in `e2e/cluster.spec.js`). Der Test muss exakt das fehlerhafte Verhalten abdecken.

- [ ] **Step 2: Test laufen lassen, Fehlschlag bestätigen**

Run (Backend-Beispiel):
```bash
cd "/c/Users/endri/Desktop/Bachelor/Mobile Picking und Voice Assistant/backend" && PYTHONPATH=.deps python -m pytest -p pytest_asyncio tests/test_cluster_service.py -k <neuer_test> -v
```
Expected: FAIL (Finding reproduziert).

- [ ] **Step 3: Minimalen Fix implementieren** — nur so viel Code wie nötig, um den Test grün zu machen; bestehende Sicherheits-Gates (fail-closed `_is_authorized`, scoped `search_read`) nicht aufweichen.

- [ ] **Step 4: Test laufen lassen, grün bestätigen**

Expected: PASS.

- [ ] **Step 5: Volle Testsuite laufen lassen (keine Regression)**

Run:
```bash
cd "/c/Users/endri/Desktop/Bachelor/Mobile Picking und Voice Assistant/backend" && PYTHONPATH=.deps python -m pytest -p pytest_asyncio tests/ -q
```
Expected: alle grün.

- [ ] **Step 6: Commit + Push (ein Commit pro logischem Fix)**

```bash
cd "/c/Users/endri/Desktop/Bachelor/Mobile Picking und Voice Assistant"
git add -A && git commit -m "fix(cluster): <Finding kurz beschrieben>"
git push origin feat/cluster-picking
```

- [ ] **Step 7: Finding in der Review-Datei auf `behoben` setzen** und nach Abarbeitung aller high/medium die Datei committen/pushen.

---

### Task 4: Fast-Forward-Merge nach `main` + Push

Bringt den verifizierten, reviewten Branch nach `main`. Da der Branch linear von `origin/main` abstammt, ist es ein sauberer Fast-Forward.

**Files:**
- Keine Datei-Änderungen (nur Git-Refs).

**Interfaces:**
- Consumes: grüner, gepushter `feat/cluster-picking`.
- Produces: `origin/main` zeigt auf `87e459b` (bzw. neuesten Fix-Commit); Serial + PWA + Cluster sind in `main`.

- [ ] **Step 1: Remote-Stand holen & FF-Vorbedingung prüfen**

Run:
```bash
cd "/c/Users/endri/Desktop/Bachelor/Mobile Picking und Voice Assistant"
git fetch origin
git merge-base --is-ancestor origin/main feat/cluster-picking && echo "FF-fähig" || echo "KEIN FF — STOP"
```
Expected: `FF-fähig`. Falls nicht → stoppen, Lage neu bewerten (jemand hat `origin/main` weitergeschoben).

- [ ] **Step 2: Lokales `main` auf `origin/main` bringen**

Run:
```bash
cd "/c/Users/endri/Desktop/Bachelor/Mobile Picking und Voice Assistant"
git checkout main
git merge --ff-only origin/main
```
Expected: lokales `main` == `origin/main` (`0048311`).

- [ ] **Step 3: Cluster-Branch per Fast-Forward in `main` mergen**

Run:
```bash
cd "/c/Users/endri/Desktop/Bachelor/Mobile Picking und Voice Assistant"
git merge --ff-only feat/cluster-picking
git log --oneline -3
```
Expected: FF erfolgreich; `main` zeigt auf den neuesten Cluster-Commit.

- [ ] **Step 4: `main` pushen**

Run:
```bash
cd "/c/Users/endri/Desktop/Bachelor/Mobile Picking und Voice Assistant"
git push origin main
```
Expected: `origin/main` aktualisiert.

- [ ] **Step 5: Verifizieren, dass beide Features in `main` sind**

Run:
```bash
cd "/c/Users/endri/Desktop/Bachelor/Mobile Picking und Voice Assistant"
git merge-base --is-ancestor fd0d98b main && echo "PWA-Serial-Fix in main: OK"
git merge-base --is-ancestor c9cf40e main && echo "Serial-Telemetrie in main: OK"
```
Expected: beide `OK`.

---

### Task 5: Branch-Aufräumen

Entfernt die nun in `main` enthaltenen Feature-/Fix-Branches, lokal und remote.

**Files:**
- Keine.

**Interfaces:**
- Consumes: erfolgreich gemergtes `main` (Task 4).
- Produces: aufgeräumte Branch-Liste.

- [ ] **Step 1: Bestätigen, dass alle Kandidaten Vorfahren von `main` sind**

Run:
```bash
cd "/c/Users/endri/Desktop/Bachelor/Mobile Picking und Voice Assistant"
for b in feat/cluster-picking feat/seriennummer-bestaetigung fix/pwa-bulk-serial fix/telemetry-und-cleanup; do
  git merge-base --is-ancestor "$b" main && echo "$b: in main (löschbar)" || echo "$b: NICHT in main (behalten)"
done
```
Expected: alle vier „in main (löschbar)".

- [ ] **Step 2: Lokale Branches löschen**

Run (nur die als löschbar bestätigten):
```bash
cd "/c/Users/endri/Desktop/Bachelor/Mobile Picking und Voice Assistant"
git branch -d feat/cluster-picking feat/seriennummer-bestaetigung fix/pwa-bulk-serial fix/telemetry-und-cleanup
```
Expected: gelöscht (`-d` schlägt fehl, falls doch nicht gemergt → dann stoppen).

- [ ] **Step 3: Remote-Branches löschen (nur die, die remote existieren)**

Run:
```bash
cd "/c/Users/endri/Desktop/Bachelor/Mobile Picking und Voice Assistant"
git push origin --delete feat/cluster-picking feat/seriennummer-bestaetigung
```
Expected: gelöscht. (`fix/*` existieren laut `git branch -vv` nur lokal → kein Remote-Delete nötig; vor dem Push mit `git branch -r` gegenprüfen.)

- [ ] **Step 4: `docs/parallel-chats/` entscheiden**

Untracked Briefing-Dateien: entweder committen (Traceability) oder löschen. Default: ins Repo aufnehmen.
```bash
cd "/c/Users/endri/Desktop/Bachelor/Mobile Picking und Voice Assistant"
git add docs/parallel-chats/ && git commit -m "docs: Parallel-Chat-Briefings archiviert" && git push origin main
```

---

### Task 6: Nachverfolgbarkeit (Memory + Obsidian)

Schließt den User-Standard ab: Push (erledigt) + genaue Beschreibung + Memory + Obsidian.

**Files:**
- Modify: `C:\Users\endri\.claude\projects\C--Users-endri\memory\project_cluster_picking.md`
- Modify: `C:\Users\endri\.claude\projects\C--Users-endri\memory\project_serial_confirmation_status.md`
- Modify: `C:\Users\endri\.claude\projects\C--Users-endri\memory\MEMORY.md` (falls Hooks anzupassen)
- Modify: Obsidian-Note `Projekt-Wiki/05 - Future Functions/Cluster- und Batch-Picking.md` (bzw. nach `04 - …/`/abgeschlossen verschieben)

**Interfaces:**
- Consumes: finaler Merge-Stand + Review-Ergebnis.
- Produces: konsistente Memory + Obsidian-Doku; offene Punkte (Live-Test-Ergebnis, evtl. Backlog-Lows) dokumentiert.

- [ ] **Step 1: Memory `project_cluster_picking.md` aktualisieren**

Status → „**Abgeschlossen & in `main` gemergt** (FF, <Datum>)". Review-Ergebnis + behobene Findings + Live-Test-Ergebnis (Batch `done` gegen `masterfischer`) ergänzen. „Offen"-Abschnitt leeren bzw. Backlog-Lows notieren.

- [ ] **Step 2: Memory `project_serial_confirmation_status.md` korrigieren**

Die alte Merge-Ketten-Beschreibung ersetzen durch die **tatsächliche** Topologie (Serial-Telemetrie + PWA-Serial-Fix lagen linear auf `feat/cluster-picking` und sind mit dem Cluster-FF nach `main` gekommen). Status → „komplett, in `main`".

- [ ] **Step 3: Obsidian-Feature-Note aktualisieren**

`Cluster- und Batch-Picking.md`: Status „implementiert & gemergt", Verweis auf Plan + Review-Datei + Merge-Commit-Hash. Falls Konvention „Future Functions" → „abgeschlossen": Note entsprechend verschieben/markieren.

- [ ] **Step 4: Obsidian-Vault committen/pushen (falls im Git-Repo `docs/projektdoku`)**

Laut Memory liegt die kanonische Doku im Repo unter `Projekt-Wiki/` (Branch `docs/projektdoku`). Änderungen dort committen + pushen, damit der Thesis-Schreib-Agent sie sieht.

- [ ] **Step 5: Abschluss-Zusammenfassung an den User**

Kurzbericht: was reviewt/gefixt wurde, Live-Test-Ergebnis, Merge-Hash in `main`, gelöschte Branches, aktualisierte Memory/Obsidian-Dateien.

---

## Self-Review

**1. Spec-Abdeckung** (gegen den im Brainstorming abgenommenen 6-Phasen-Plan):
- Phase 0 (Baseline) → Task 0 ✓
- Phase 1 (Live-Test gegen Odoo) → Task 1 ✓
- Phase 2 (Multi-Agent-Review) → Task 2 ✓
- Phase 3 (Fixes) → Task 3 ✓
- Phase 4 (FF-Merge + Push) → Task 4 ✓
- Phase 5 (Branch-Cleanup) → Task 5 ✓
- Phase 6 (Memory + Obsidian) → Task 6 ✓
- Keine Lücken.

**2. Placeholder-Scan:** Task 3 enthält bewusst keinen vorgeschriebenen Patch-Code, weil die Findings erst aus Task 2 entstehen — stattdessen ist der TDD-Prozess pro Finding vollständig und mit exakten Kommandos beschrieben. Das ist kein verstecktes „TODO", sondern die korrekte Modellierung einer review-getriebenen Fix-Phase. Alle anderen Tasks haben exakte Kommandos + erwartete Ausgaben.

**3. Typ-/Namens-Konsistenz:** Branch-Namen, Commit-Hashes (`0048311`, `c9cf40e`, `fd0d98b`, `87e459b`), DB-Name (`masterfischer`), Test-Kommandos (`PYTHONPATH=.deps … -p pytest_asyncio`) und Pfade sind über alle Tasks identisch verwendet. Merge-Ziel durchgängig `origin/main`.

**Bekanntes Risiko:** Falls `origin/main` zwischen Planung und Ausführung weiterbewegt wird, ist der FF in Task 4 nicht mehr möglich (Step 1 fängt das ab → dann Rebase nötig, separate Entscheidung).
