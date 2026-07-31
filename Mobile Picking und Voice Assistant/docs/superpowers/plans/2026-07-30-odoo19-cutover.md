# Odoo-19 Cutover Plan — SUPERSEDED

> **SUPERSEDED on 2026-07-31 by `docs/superpowers/plans/2026-07-31-odoo19-cutover.md`. DO NOT
> EXECUTE THIS FILE.** It was written in a separate session, untracked, and reaches the same
> architectural conclusion (reseed, not migration) independently. It is committed rather than
> deleted because eleven of its findings are load-bearing and one of them — that `dbfilter` does not
> constrain Odoo's cron master, so isolation needs `db_name` — corrects a real error in the
> successor's first revision. All eleven are folded into the successor and attributed there in §0.5:
> its risks R1-R11, its Task 5 (defaults and documentation) and its Task 6 (stale analysis caches).
>
> Where the two disagree, **the successor wins**, and the disagreements are these: its D1/D2/D3 are
> open questions there and decided facts in the successor; its "what this plan deliberately does not
> do" defers the `secrets:` block and `RUNTIME_PROFILE` to Task 15, whereas the register's R3
> deployment obligation names *"Task 15, or whoever deploys first"* and the successor's Task 5 takes
> them on; and its exit gate G9-G12 is superseded by the successor's Task 9 Step 2.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **This document is the deliverable of branch `codex/odoo19-cutover`. Writing it is complete when it is committed. Executing it is a separate, later decision by the project owner.** Nothing in this file may be executed as a side effect of reviewing it.

**Goal:** Make Odoo 19 the default runtime of the stack, delete `odoo/addons18/` in the same commit that rebuilds Compose, stand up a fresh v19 database by reseed, and produce the `wave1-odoo19-handoff` tag that Foundation Tasks 12, 15, 16 and 17 are hard-blocked on.

**Architecture:** This is a **reseed, not a migration**. The project owner has confirmed that the live database `masterfischer` holds seed data only, with no real warehouse history. There is no OpenUpgrade tooling and no migration script in this repository, and Odoo Community has no official upgrade service, so a reseed was the only viable path regardless; the owner's answer makes it the correct path rather than a compromise. The v19 addon tree `odoo/addons/` already runs green under the `odoo19-trial` profile against `masterfischer_o19_trial`, and `infrastructure/scripts/seed-odoo.py` has already populated that database successfully. The cutover therefore promotes a proven configuration rather than inventing one: the `odoo` service keeps its name, its port and its DNS identity, and only its image, its mount, its config file, its volume and its database change.

**Tech Stack:** Docker Compose, `odoo:19.0` Community, PostgreSQL 16, XML-RPC seeding (`seed-odoo.py`), Caddy, FastAPI backend.

---

## 0. Corrections of record — where the commissioning brief and the files disagree

This plan was written by reading the files at `1e240f5`, the base of `codex/odoo19-cutover`. Several
facts in the commissioning brief did not survive that reading. They are recorded here rather than
silently corrected, because three plans in this programme have already shipped defects that cost fix
rounds, and every one of them started with a summary that nobody re-derived.

1. **The v19 addon footprint in the brief describes a different tree.** The brief states 5613 lines
   for `odoo/addons/`, `integration_job.py` at 515 lines, `receipts.py` at 713, `resources.py` at
   610, and a `tests/` directory of 10 files. At `1e240f5` the real numbers are **4316 lines**
   total, `integration_job.py` **411**, `receipts.py` **544**, `resources.py` **575**, `outbox.py`
   195 (the one figure that matches), and **8 files** under `tests/`. The brief's numbers are closer
   to `remediation/r2-odoo` HEAD (**7511 lines**, 12 files under `tests/`), which is not an ancestor
   of this branch. **Consequence for this plan: none of the numbers are load-bearing** — the cutover
   moves a mount, not a line count — but any reviewer who checks the brief against `git` will find a
   mismatch, and the mismatch is the branch, not an error in the survey.

2. **`odoo/addons18/` is 1197 lines across 23 files — the brief is exactly right**, and it is
   identical on `remediation/r2-odoo`. The 1197 includes `README.md`; the `.py`/`.xml`/`.csv` subtotal
   is 1192. The tree also carries `quality_alert_custom/static/description/icon.png`.

3. **`docs/superpowers/parallel/2026-07-23-program-status.md` does not exist on this branch.** It was
   introduced in `7a65183` and lives only on `remediation/r2-odoo` (and untracked in the main
   working tree). Neither does the reference plan
   `docs/superpowers/plans/2026-07-29-r2-odoo-leases-concurrency.md`, nor the R1/R3/R4 plans, nor
   `parallel/2026-07-29-handoff.md`. This is the **same defect shape the register itself already
   recorded once**, when R1's exit gate pointed it at a file its branch never had. This plan
   therefore does not assume the register is editable from here: see §5, exit gate item G7.

4. **`.env` is not in the repository and is not in this worktree.** Only `.env.example` is tracked,
   and it reads `ODOO_DB=picking` (line 10), not `masterfischer`. The live `.env` with
   `ODOO_DB=masterfischer` and the `o19-trial` entry in `ODOO_INSTANCES_JSON` exists only in the
   operator's main checkout at `Desktop/Bachelor/`. **Consequence: "update `.env`" is an operator
   action that no commit can carry.** The committed artefact is `.env.example`; Task 3 splits the
   two explicitly.

5. **The Odoo-19 group privilege field is `privilege_id`, not `privilege`.** The brief names it
   `privilege`. `odoo/addons/quality_alert_custom/security/quality_alert_security.xml` declares a
   `res.groups.privilege` record and then references it as
   `<field name="privilege_id" ref="res_groups_privilege_quality"/>`, and additionally adds a
   `sequence` field the v18 file lacks. Nothing in the cutover edits this file; the correction
   matters only so a reviewer grepping for `privilege` does not conclude the file is wrong.

6. **`quality_alert_custom/models/quality_alert.py` is byte-identical between the two trees once
   line endings are normalised** — the v19 copy is CRLF, the v18 copy is LF. A naive `diff -ru`
   reports the entire 190-line file as changed, which is what makes the tree look more divergent
   than it is. After the deletion the only surviving copy is the CRLF one; `git diff --check` will
   warn on any future edit to it, exactly as it already does for `backend/app/main.py`.

7. **`docs/SETUP.md`, `Makefile` and `e2e/cluster.live.js` also carry Odoo-18-era facts** and the
   brief lists none of them. `docs/SETUP.md` has six affected lines (DB-manager URL, API-key step,
   the `second-odoo` section, the seed invocation, the admin URL, the "do not start Odoo-18
   databases with the Odoo-19 container" warning that this cutover finally makes moot).
   `Makefile:51,119,122` read `$${ODOO_DB:-picking}` and port 8069 — these keep working unchanged
   provided `.env` is updated, which is why they are verification targets rather than edit targets.
   `e2e/cluster.live.js:5` is a comment naming `masterfischer`.

8. **`odoo/odoo-lager2.conf` exists and the brief does not mention it.** The `odoo-lager-2` service
   under the `second-odoo` profile has its own config with `dbfilter = ^(lager2|picking2|masterfischer2)$`
   and `list_db = True`. It also mounts `addons18`, so it cannot be left alone: see Task 2 and Task 7.

Everything else the brief asserted — the compose line numbers, the missing v18 models, the
`_sql_constraints` versus `models.Constraint` split, the `_commit_progress` calls, the manifest
version strings, the `stock_picking_batch` dependency added in v19, `Dockerfile:1`,
`Caddyfile:8-11`, `seed-odoo.py:145`, `cluster_service.py:12`, the absence of CI and `.github/` —
**was verified true.**

---

## Global Constraints

- **This plan lifts the Foundation Compose freeze for exactly the changes listed in Task 2, Task 3
  and Task 7, and for nothing else.** The Foundation plan (line 20) forbids editing
  `docker-compose.yml` before the Odoo-19 handoff; two bounded exceptions are already on the record
  (the R1 `CORS_ORIGINS`→`PWA_ORIGINS` rename, and R4 Step 9 which is itself gated on the tag this
  plan produces). This plan *is* the handoff. Any Compose edit not enumerated in a task below is
  still frozen and still requires its own recorded exception.

- **The deletion of `odoo/addons18/` and the Compose rebuild are ONE commit.** This is the project
  owner's explicit instruction and it is not a style preference: the live `odoo` container mounts
  `./odoo/addons18:/mnt/extra-addons:ro`, so a commit that deletes the directory before the mount
  moves leaves the running container unable to load `picking_assistant_integration` on its next
  restart. Splitting the commit for reviewability is forbidden. Task 2 is deliberately the largest
  task in this plan for that reason.

- **`masterfischer` is the live database and it is NOT dropped, NOT renamed and NOT touched.** It
  stays in place as the rollback artefact. A reseed makes it disposable; keeping it costs one
  database's disk on a cluster that is not short of it, and it is the only thing that makes §4's
  rollback a five-minute operation instead of a rebuild. The cutover creates a **new** database,
  `masterfischer_o19`. `masterfischer_o19_trial` (the trial) and `masterfischer_o19_foundation_test`
  (the addon test DB) also stay untouched and keep their current roles.

- **Never `docker compose down -v`, and never delete the `pg_data` volume, at any point in this
  plan.** Debt register finding #14 is open and owned by lane R4: `infrastructure/scripts/init-n8n-db.sql`
  currently presupposes the `n8n_app` role that the unmounted `init-db-roles.sh` would create, so an
  empty `pg_data` volume aborts during PostgreSQL init. The cutover creates a database **inside the
  existing cluster** and never re-initialises it, so it does not hit #14 — but only as long as
  nobody wipes the volume. If the volume is ever wiped before R4 Task 1 lands, the stack does not
  come back and this plan's rollback does not work either.

- **The Odoo addon test command is unchanged by this plan, on purpose.** It stays:
  ```bash
  docker compose --profile odoo19-trial run --rm --no-deps -T odoo19-trial \
    odoo --no-http --test-enable --stop-after-init \
    --workers=0 --max-cron-threads=0 \
    -d masterfischer_o19_foundation_test -u picking_assistant_integration
  ```
  **Every flag is load-bearing** and the reasons are already on the record: `run --rm --no-deps`
  rather than `up` plus `exec`, and `--max-cron-threads=0`, because the test database shares the
  PostgreSQL cluster with the live stack and a concurrently running Odoo with cron threads writes
  `ir_cron` during module load, killing the run with `SerializationFailure` before a single test
  executes. This plan **keeps the `odoo19-trial` profile service alive and unmodified** precisely so
  this command survives the cutover verbatim. Do not "clean up" that service; removing it would
  force every downstream plan to rewrite its test command, and would put addon tests on the same
  service that serves production. **Do not leave a long-running `odoo19-trial` container up.**

- **The production v19 service must pin `db_name` in its config.** See Risk R1 in §6. Odoo's cron
  master enumerates databases with `odoo.service.db.list_dbs(force=True)`, which does **not** apply
  `dbfilter` — `dbfilter` is an HTTP-layer filter. A long-running v19 container with cron threads
  will therefore attach to every database in the cluster, including `masterfischer` (the rollback
  artefact) and `masterfischer_o19_foundation_test`. Setting `db_name = masterfischer_o19` restricts
  the cron master to exactly one database. This is not optional hardening; it is what protects the
  rollback artefact and the test suite.

- **`docker compose config --quiet` must pass after every Compose edit**, and the full file must be
  re-read after each task — this is a hand-edited YAML file with four Odoo services in it.

- **This is WSL2 over `/mnt/c` and it is slow.** Print progress between steps. A command that runs
  silently for 600 seconds gets killed by the stall watchdog.

- **Every task below is independently reviewable and carries its own verification step.** Task 2 is
  the exception to "small commits", never to "verified commits".

---

## 1. Pre-flight — what must be true before Task 1 starts

- [ ] **P1. The project owner has signed off on executing this plan.** Writing it is this branch's
      deliverable; running it is a separate decision. Do not start Task 1 on the strength of this
      document alone.

- [ ] **P2. Decision §3.4 is executed as "delete", in writing.** The owner has answered: Odoo 19
      only, `odoo/addons18/` is to be deleted. The status file's §3.4 currently reads "narrow
      approved auth-compatibility port — or it is deleted". That entry must be amended to record the
      answer. Because the status file is not on this branch (§0.3), the amendment happens on the
      branch that carries it — see G7.

- [ ] **P3. R1, R2 and R3 are merged into `codex/integration-bachelor-hardening`, and the
      whole-branch gate of §5 of the program status is green on the merged tree.** The programme's
      own sequencing diagram is `R1 ─┐ R2 ─┼─> whole-branch gate ─> Odoo-19 handoff ─> 12 ─> 15 ─> 16 ─> 17`.
      The handoff sits **after** the gate. Cutting over before the lanes merge would put the live
      stack on addon code whose adversarial review has not closed, which is the exact failure mode
      the register was created to stop. Specifically, R2 closes findings #5, #6, #7, #10, #11, M1
      and M2 in the very addon this cutover promotes to production, and M1 (a revoked session being
      silently re-blessed, with role escalation writable onto it) was re-severitied to **High**.

- [ ] **P4. R4 is NOT a blocker, and this is a deliberate finding, not an omission.** The brief asks
      whether the cutover must wait for R4. It must not, and the reason is precise: R4 owns the
      PostgreSQL **role** separation and the `docker-entrypoint-initdb.d` **bootstrap**, both of
      which are properties of an *empty cluster*. This cutover creates a database inside the
      *existing* cluster using the existing `odoo` superuser role, mounts no init script, and
      changes no `db` service key. The two lanes intersect at exactly one point and it already
      points the right way: **R4 Step 9 is explicitly gated on the `wave1-odoo19-handoff` tag that
      this plan produces**, and R4's own exit gate requires recording that Step 9 is *not* done and
      why. So the dependency is R4-after-cutover, not cutover-after-R4. The one obligation this
      creates on the cutover side is the "never wipe `pg_data`" constraint above, because until R4
      Task 1 lands, a wiped volume cannot re-initialise.

- [ ] **P5. The trial stack is proven, recently.** Re-run the addon suite against
      `masterfischer_o19_foundation_test` and confirm it is green twice with identical results
      before touching Compose. A cutover onto an addon whose suite has not been run this week is a
      cutover onto an assumption.

- [ ] **P6. The operator has the admin credentials that the new database will be created with**, and
      knows that `ODOO_API_KEY` in the live `.env` is bound to `masterfischer` and will be invalid
      against `masterfischer_o19`. See Risk R4.

- [ ] **P7. `docker compose ps` is recorded, and `docker volume ls` output is saved.** The rollback
      in §4 refers to the pre-cutover state; capture it rather than reconstructing it later.

- [ ] **P8. Working tree clean, on `codex/odoo19-cutover`, rebased onto the merged
      `codex/integration-bachelor-hardening`.**

---

## 2. Cutover tasks

### Task 1: Record the runtime facts the handoff hands off

Foundation Task 15's handoff gate says: "Rebase first and **preserve the Odoo-19 service/image/mount
facts delivered by that branch**." Those facts must exist as a citable artefact before Compose
changes, or Task 15 has nothing to preserve and will re-derive them from a running container.

**Files:**
- Create: `docs/superpowers/specs/2026-07-30-odoo19-runtime-facts.md`

**Interfaces:**
- Consumes: nothing.
- Produces: the runtime fact sheet that Foundation Task 15 Step 1 and Task 12's handoff gate cite.
  It must state, as a table: service name `odoo`; image `odoo:19.0` via `ODOO_BASE_IMAGE`; addons
  mount `./odoo/addons`; config `./odoo/odoo19.conf`; filestore volume `odoo19_data`; database
  `masterfischer_o19`; published port `8069`; in-network URL `http://odoo:8069`; and the surviving
  `odoo19-trial` profile service with its own volume, config, database and localhost-only port 8100.

- [ ] **Step 1: Write the fact sheet**

State the facts as *decisions with their alternatives and why they lost*, not as a description.
Four decisions need that treatment, because each had a real alternative:

- **v19 takes over the `odoo` service name.** The alternative was to promote `odoo19-trial` to
  default and repoint everything at it. It loses on blast radius: `ODOO_URL: http://odoo:8069`
  (`docker-compose.yml:131`), the Caddy redirect (`infrastructure/caddy/Caddyfile:8-11`),
  `backend/app/config.py:24`'s default, `Makefile:29,48,118,119,122`, `docs/SETUP.md` and roughly
  twenty backend test fixtures all name `odoo` or `8069`. Taking over the name changes none of them.
  It also resolves the port collision by construction: `odoo` keeps `8069`, `odoo19-trial` keeps
  `127.0.0.1:8100`, and they never contend.
- **`odoo19-trial` survives, unmodified.** It is the only service that can run the addon test suite
  without touching production, and the documented test command depends on its name. Removing it
  would change that command's shape, which the brief correctly flagged as a question this plan must
  answer. **The answer is: nothing replaces it, because it does not go away.**
- **A new database `masterfischer_o19`, not a reuse of the name `masterfischer`.** Reusing the name
  would leave `.env`, `ODOO_DB` and the dbfilter untouched — but it would require dropping or
  renaming the live database, which destroys the rollback path. A new name costs three
  one-line edits and buys a rollback that is a config revert rather than a restore.
- **A new volume `odoo19_data`, not `odoo_data` and not `odoo19_trial_data`.** `odoo_data` holds the
  v18 filestore for `masterfischer` — the attachments belonging to the rollback artefact — and must
  not be shared with a v19 service that will write into it. `odoo19_trial_data` belongs to the trial
  and is declared with an explicit top-level `name:` (`docker-compose.yml:288`), so it is *not*
  project-prefixed and is visible to any other Compose project on the host; production should not
  inherit that. A third, project-scoped volume keeps all three lifecycles separate.

- [ ] **Step 2: Verify**

The fact sheet must be consistent with the Compose file that Task 2 will write. Since Task 2 has not
run yet, the check is the reverse: Task 2 Step 6 diffs the fact sheet against the real Compose file
and fails if they disagree. Note that obligation in the fact sheet itself.

- [ ] **Step 3: Commit**

```bash
git add "docs/superpowers/specs/2026-07-30-odoo19-runtime-facts.md"
git commit -m "docs(odoo19): record the runtime facts the handoff delivers"
```

---

### Task 2: The single cutover commit — Compose rebuild plus `addons18/` deletion

**This is the one irreversible-looking step, and the constraint that the deletion and the rebuild
share a commit comes from the owner.** Everything else in this plan is reversible with a config
change; this one needs `git revert`. Read the whole task before starting it.

**Files:**
- Create: `odoo/odoo19.conf`
- Create: `odoo/odoo-lager2-19.conf`
- Modify: `odoo/Dockerfile`
- Modify: `docker-compose.yml`
- Delete: `odoo/addons18/` — all 23 files, all three modules, plus `__pycache__` and the `.png`

**Interfaces:**
- Consumes: the fact sheet from Task 1.
- Produces: a Compose file with **zero** references to `addons18` or to `odoo:18.0`; services `odoo`
  (v19, default, no profile), `odoo-lager-2` (v19, profile `second-odoo`), `odoo19-trial` (v19,
  profile `odoo19-trial`, unchanged).

- [ ] **Step 1: Write the production v19 config**

Create `odoo/odoo19.conf`. Start from `odoo/odoo19-trial.conf`, not from `odoo/odoo.conf` — the
trial config already has the safer posture. Three deliberate differences from both:

```ini
[options]
db_host = db
db_port = 5432
db_user = odoo
; db_password wird vom Docker-Entrypoint via PASSWORD env-Variable gesetzt

addons_path = /mnt/extra-addons,/usr/lib/python3/dist-packages/odoo/addons

; Master-Passwort bewusst nicht im Repo setzen.
; db_name pinnt den Cron-Master auf GENAU diese Datenbank. dbfilter reicht dafuer
; NICHT: dbfilter ist ein HTTP-Filter, der Cron-Master enumeriert via
; odoo.service.db.list_dbs(force=True) den gesamten Cluster. Ohne db_name wuerde
; dieser Container Crons gegen masterfischer (Rollback-Artefakt) und gegen
; masterfischer_o19_foundation_test (Testdatenbank) fahren. Siehe Risiko R1.
db_name = masterfischer_o19
dbfilter = ^masterfischer_o19$
list_db = False
proxy_mode = True

workers = 2
max_cron_threads = 1
limit_memory_hard = 2684354560
limit_memory_soft = 2147483648
limit_time_cpu = 600
limit_time_real = 1200

log_level = info
log_handler = :INFO
```

The three differences from `odoo/odoo.conf`, each of which is a security or correctness improvement
and each of which must be called out in the commit message:

1. `list_db = False`. The v18 production config has `list_db = True` while publishing `8069:8069` on
   **all interfaces**. That is the Odoo database manager reachable from the LAN. The trial config
   already set `list_db = False`; production inherits it. **Consequence: the database cannot be
   created through the web manager any more.** Task 4 creates it from the CLI instead, which is
   better anyway — it is scriptable and leaves a log.
2. `dbfilter` anchored to exactly one database rather than `^(picking|masterfischer)$`. The old
   filter's `picking` alternative is a leftover from `.env.example`'s default and matches no
   database that exists.
3. `db_name` pinned. See the comment in the file and Risk R1.

Leave `odoo/odoo.conf` and `odoo/odoo19-trial.conf` **untouched**. `odoo.conf` is part of the
rollback path; `odoo19-trial.conf` is what keeps the test command working.

- [ ] **Step 2: Write the second-instance v19 config**

Create `odoo/odoo-lager2-19.conf` as a copy of `odoo19.conf` with `db_name = lager2_o19` and
`dbfilter = ^lager2_o19$`. Leave `odoo/odoo-lager2.conf` untouched for the same rollback reason.

The `odoo-lager-2` service is not optional collateral: it is the second instance behind the PWA
*Lagerumschalter*, which is a demonstrated thesis feature, and it mounts `addons18`. It cannot stay
on v18 once that directory is gone. Its database `lager2` is a v18 database and will not be reused —
Task 7 reseeds `lager2_o19`. Until Task 7 runs, **the instance switcher is broken**, and that is a
consequence this plan accepts openly rather than discovering during a demo.

- [ ] **Step 3: Move the image default**

`odoo/Dockerfile:1`: `ARG ODOO_BASE_IMAGE=odoo:18.0` → `ARG ODOO_BASE_IMAGE=odoo:19.0`. All three
services pass the arg explicitly, so this line is only the default — change it anyway, so that a
`docker build ./odoo` with no args stops producing an Odoo 18 image.

- [ ] **Step 4: Rebuild the Compose services**

In `docker-compose.yml`:

- Service `odoo` (currently lines 41–63): `ODOO_BASE_IMAGE: odoo:18.0` → `odoo:19.0`; volume
  `odoo_data:/var/lib/odoo` → `odoo19_data:/var/lib/odoo`; config mount
  `./odoo/odoo.conf` → `./odoo/odoo19.conf`; addons mount `./odoo/addons18` → `./odoo/addons`.
  **Do not change the service name, the `ports` mapping or the network.** Update the section comment
  from "Odoo 18 Community (Live/Default)" to "Odoo 19 Community (Live/Default)".
- Service `odoo-lager-2` (currently 66–90): `odoo:18.0` → `odoo:19.0`; `./odoo/addons18` →
  `./odoo/addons`; `./odoo/odoo-lager2.conf` → `./odoo/odoo-lager2-19.conf`; volume
  `odoo_lager2_data` → `odoo_lager2_19_data`. Profile, port variable and name unchanged.
- Service `odoo19-trial` (93–117): **no change whatsoever.**
- Volumes block (283–292): add `odoo19_data:` and `odoo_lager2_19_data:`. **Keep `odoo_data:` and
  `odoo_lager2_data:` declared.** A volume that is declared but unused is harmless; a volume that is
  removed from the file while still holding the rollback filestore invites `docker volume prune`.
  Add a comment on each saying it is the v18 rollback filestore and the date it may be removed.
- Leave `ODOO_URL: http://odoo:8069` (131) and `ODOO_DB: ${ODOO_DB:-picking}` (132) alone; the
  database name moves via `.env` in Task 3.

- [ ] **Step 5: Delete `odoo/addons18/`**

```bash
git rm -r "odoo/addons18"
```

All three modules go: `picking_assistant_core`, `picking_assistant_integration` and
`quality_alert_custom` — the cutover deletes the whole tree, not just the integration addon. Confirm
that `git status` shows 23 deleted tracked files and that no `__pycache__` remains on disk.

- [ ] **Step 6: Verify — before committing**

```bash
docker compose config --quiet && echo "compose OK"
grep -rn "addons18\|odoo:18.0" docker-compose.yml odoo/ && echo "STILL PRESENT — FAIL" || echo "clean"
grep -rn "addons18" --include="*.py" --include="*.yml" --include="*.sh" --include="*.js" . \
  | grep -v graphify-out | grep -v code-review-graph
test -d odoo/addons18 && echo "DIRECTORY STILL EXISTS — FAIL" || echo "deleted"
```

Expected: `compose OK`; no hits in `docker-compose.yml` or `odoo/`; the only surviving `addons18`
mentions are in `docs/superpowers/specs/` (historical analysis documents, which are records of what
was true and must not be rewritten) and in the stale generated caches `graphify-out/` and
`.code-review-graph/` (~465 hits, not source — Task 6 handles them).

Then diff the Compose file against the Task 1 fact sheet, key by key. If they disagree, the fact
sheet is wrong and gets fixed in this same commit — Foundation Task 15 will trust it.

**Do not start any container in this step.** The commit must be reviewable before anything runs.

- [ ] **Step 7: Commit — one commit, both halves**

```bash
git add docker-compose.yml odoo/Dockerfile odoo/odoo19.conf odoo/odoo-lager2-19.conf
git add -A odoo/addons18
git commit -m "feat(odoo19): cut the default stack over to Odoo 19 and delete the v18 addon tree

The odoo service moves to odoo:19.0, mounts ./odoo/addons, uses the new
odoo/odoo19.conf and a new odoo19_data volume. odoo-lager-2 follows. The
odoo19-trial profile service is unchanged so the addon test command keeps
working verbatim.

odoo/addons18 is deleted in this same commit by design: the live odoo
container mounts it read-only, so deleting it in a separate earlier commit
would leave that container unable to load picking_assistant_integration on
its next restart. Executes decision 3.4 of the program status (Odoo 19 only).

odoo19.conf differs from the retired odoo.conf in three deliberate ways:
list_db=False (the v18 config exposed the database manager on a LAN-published
port), an anchored single-database dbfilter, and db_name pinned so the cron
master cannot attach to masterfischer or to the addon test database --
dbfilter is an HTTP filter and does not constrain the cron master.

odoo_data and odoo_lager2_data stay declared: they hold the v18 filestores
and are the rollback path.

Lifts the Foundation compose freeze for exactly these services and keys."
```

---

### Task 3: Environment and instance registry

**Files:**
- Modify: `.env.example`
- Operator action, not a commit: the live `.env` in the main checkout

**Interfaces:**
- Consumes: the database name `masterfischer_o19` fixed in Task 1.
- Produces: an `.env.example` that documents the v19 world, and a written operator checklist for the
  untracked `.env`.

- [ ] **Step 1: Update `.env.example`**

- `ODOO_DB=picking` → `ODOO_DB=masterfischer_o19`, with a comment that this is the v19 production
  database and that `masterfischer` is the retained v18 rollback artefact.
- Under the `second-odoo` comment block, change the example `ODOO_INSTANCES_JSON` line's `lager-2`
  entry `"db":"lager2"` → `"db":"lager2_o19"`.
- Add a commented `o19-trial` example entry, since the live `.env` carries one and the example does
  not — the drift is how the example stopped being a usable template.
- Do **not** add `ODOO_API_KEY` guidance beyond what is there; do add a one-line warning that the
  API key is database-bound and must be regenerated after the cutover (Risk R4).

- [ ] **Step 2: Write the operator checklist for the live `.env`**

This cannot be a commit (§0.4). Put it in the fact sheet from Task 1, as an explicit
"operator actions outside version control" section:

1. `ODOO_DB=masterfischer` → `ODOO_DB=masterfischer_o19`.
2. `ODOO_API_KEY=<old>` → the key generated against the new database in Task 4 Step 5.
3. `ODOO_INSTANCES_JSON`: `lager-2`'s `"db"` → `"lager2_o19"`; leave the `o19-trial` entry exactly as
   it is — it points at the trial and the trial is unchanged.
4. Leave `DEMO_TRACEABILITY_ALLOWED_DBS=masterfischer_o19_trial` **unchanged**. See Step 3.
5. Keep a copy of the pre-cutover `.env` outside the repo. Rolling back means restoring two lines.

- [ ] **Step 3: Verify the instance registry does not need code changes**

This is a real trap and it needs an explicit negative check rather than an assumption.
`backend/app/config.py:97-98` declares
`ODOO19_TRIAL_PROFILE_NAMES = {"o19", "odoo19", "o19-trial", "odoo19-trial"}` and
`ODOO19_TRIAL_DB = "masterfischer_o19_trial"`, and line 143 **rejects** any profile whose key is in
that set unless its database is exactly the trial database. Confirm all three of the following:

- The canonical `local` profile is built from `odoo_url`/`odoo_db` and its key is `local`, which is
  not in `ODOO19_TRIAL_PROFILE_NAMES`. So pointing `local` at `masterfischer_o19` passes. **Nothing
  in `config.py` needs to change** — but a plan that had named the new database
  `masterfischer_o19_trial`, or had reused an `o19` profile key for production, would have hit a
  hard validation error at startup. This is why the name is `masterfischer_o19`.
- `demo_traceability_allowed_dbs` defaults to `masterfischer_o19_trial` (`config.py`). The new
  production database is therefore **not** in the allow-list and demo traceability stays off in
  production. That is the correct direction and it must not be "fixed".
- `odoo_db` still defaults to `"picking"` in `config.py:24-25` and Compose still reads
  `${ODOO_DB:-picking}`. Neither is changed here; both are made correct by `.env`. If a future
  deployment forgets `ODOO_DB`, the backend authenticates against a database that does not exist and
  fails loudly, which is the behaviour we want.

```bash
cd backend && PYTHONPATH=.deps python -m pytest -p pytest_asyncio \
  tests/test_instance_registry.py tests/test_dependencies_instance.py -q
```

Expected: green, unchanged. These tests hard-code `http://odoo:8069`, which is exactly the fact this
cutover preserves — if they had needed editing, the service rename decision would have been wrong.

- [ ] **Step 4: Commit**

```bash
git add .env.example "docs/superpowers/specs/2026-07-30-odoo19-runtime-facts.md"
git commit -m "chore(env): point the example environment at the Odoo 19 database"
```

---

### Task 4: Create and seed the fresh v19 database

Nothing here is committed. This task changes the running system for the first time.

**Files:** none. Operator commands only.

**Interfaces:**
- Consumes: the Compose file from Task 2 and the `.env` from Task 3.
- Produces: database `masterfischer_o19` with the three custom modules installed and seed data
  loaded; a fresh `ODOO_API_KEY`.

- [ ] **Step 1: Stop the v18 stack cleanly, without removing volumes**

```bash
docker compose stop odoo backend
docker compose ps
```

`docker compose down -v` is forbidden (Global Constraints). Stopping `backend` too prevents it
issuing JSON-RPC calls against a half-built database.

- [ ] **Step 2: Build the new image**

```bash
docker compose build odoo
```

- [ ] **Step 3: Create the database and install the modules from the CLI**

`list_db = False` means the web database manager is not available — deliberately. Create it with a
one-shot run so the operation is logged and repeatable:

```bash
docker compose run --rm --no-deps -T odoo \
  odoo --no-http --stop-after-init --workers=0 --max-cron-threads=0 \
  -d masterfischer_o19 \
  -i base,stock,stock_picking_batch,mail,picking_assistant_core,picking_assistant_integration,quality_alert_custom
```

`--max-cron-threads=0` for the same reason it appears in the test command. `stock_picking_batch` is
listed explicitly even though `picking_assistant_core`'s v19 manifest depends on it — the v18
manifest depended only on `stock`, so this is a genuinely new dependency and naming it makes the
install order visible in the log rather than implicit.

Expected: exit 0, and the log contains `Modules loaded` with no `ERROR`. If
`stock_picking_batch` is unavailable, stop — that is an Odoo 19 Community packaging question, not
something to work around.

- [ ] **Step 4: Start the v19 service and confirm it is alone in the database**

```bash
docker compose up -d odoo
docker compose logs --tail=80 odoo
docker compose exec db psql -U odoo -l
```

Expected: `masterfischer_o19` present; `masterfischer`, `masterfischer_o19_trial` and
`masterfischer_o19_foundation_test` all still present and untouched. The `odoo` log must show cron
work only for `masterfischer_o19` — if it names any other database, `db_name` did not take effect
and Task 2 Step 1 must be revisited before going further (Risk R1).

- [ ] **Step 5: Generate a new API key**

Log in at `http://<HOST>:8069/` as admin, Settings → API keys, generate, and put the value in the
live `.env` as `ODOO_API_KEY` (Task 3 Step 2 item 2). The old key was issued against `masterfischer`
and is meaningless here.

- [ ] **Step 6: Seed**

```bash
python infrastructure/scripts/seed-odoo.py \
  --url http://localhost:8069 \
  --db masterfischer_o19 \
  --user admin \
  --api-key <the key from Step 5>
```

Note that `seed-odoo.py`'s own defaults are `--url http://localhost:8069` (line 145) and
`--db masterfischer` (line 146). **The URL default is already correct after the cutover** — this is
the payoff of keeping the `odoo` service on port 8069, and the brief's expectation that the URL
default would need changing does not hold. The `--db` default is now wrong and Task 5 fixes it.
Pass both explicitly here regardless; a seeding run is not the place to rely on a default.

Add `--lego-seed` or `--bom-mode` only if the demo dataset requires them; they are not part of the
cutover.

- [ ] **Step 7: Restart the backend and verify**

```bash
docker compose up -d backend
docker compose logs --tail=40 backend
curl -sk https://localhost/api/health
```

Expected: backend healthy, authenticating against `masterfischer_o19`, no `OdooAPIError` in the log.

---

### Task 5: Route surface, seeder default, and stale documentation

Small, mechanical, entirely reviewable — and deliberately *after* the database exists, so that every
default it changes points at something real.

**Files:**
- Modify: `infrastructure/scripts/seed-odoo.py`
- Modify: `infrastructure/caddy/Caddyfile`
- Modify: `docs/SETUP.md`
- Modify: `backend/app/services/cluster_service.py` (comment only)
- Modify: `e2e/cluster.live.js` (comment only)

**Interfaces:**
- Consumes: the running v19 stack from Task 4.
- Produces: no behavioural change to any code path. Every edit here is a default, a comment or a
  document.

- [ ] **Step 1: `seed-odoo.py`**

Line 146: `--db` default `masterfischer` → `masterfischer_o19`. Leave line 145's `--url` default at
`http://localhost:8069` — it is correct. Update the module docstring's two usage examples, which
already say "Odoo 19" but name the old database.

- [ ] **Step 2: `Caddyfile`**

Lines 8–11 redirect `/odoo` and `/odoo/*` to `http://{host}:8069/`. **This is already correct** and
needs no change, because the `odoo` service kept port 8069. Verify it rather than edit it, and note
in the commit message that it was checked. Do **not** convert the redirect into a `reverse_proxy` in
this task — the route surface is Foundation Task 15's, it is still under the freeze, and the
`X-Forwarded-*`/`trusted_proxies` obligations from decision §3.5 belong with it.

- [ ] **Step 3: `docs/SETUP.md`**

Six places: line 40 (the database-manager URL — now unreachable, replace with the CLI creation
command from Task 4 Step 3), line 46 (API-key step, add the "regenerate after cutover" note), lines
56–78 (the `second-odoo` section: `lager2` → `lager2_o19`, and a note that Task 7 must run before
the switcher works), lines 129–130 (`--db masterfischer` → `masterfischer_o19`), line 139, and lines
142–145 (the "do not blindly start Odoo-18 databases with the Odoo-19 container" warning — this
cutover is exactly the sanctioned way to do it, so rewrite the warning to point here).

- [ ] **Step 4: Two comments**

`backend/app/services/cluster_service.py:12` cites `2026-06-23-odoo18-batch-api-facts.md`. Do **not**
delete the citation — that document records verified API facts and remains historically true. Add
the v19 fact sheet from Task 1 alongside it. `e2e/cluster.live.js:5` names `masterfischer`; change to
`masterfischer_o19`.

- [ ] **Step 5: Verify**

```bash
grep -rn "masterfischer\b" --include="*.py" --include="*.js" --include="*.md" \
  infrastructure/ backend/app/ e2e/ docs/SETUP.md | grep -v "_o19"
docker compose config --quiet
```

Expected: the only bare `masterfischer` hits are in `docs/superpowers/` history and in the rollback
notes, which are meant to say it.

- [ ] **Step 6: Commit**

```bash
git add infrastructure/scripts/seed-odoo.py docs/SETUP.md \
  backend/app/services/cluster_service.py e2e/cluster.live.js
git commit -m "chore(odoo19): point defaults and docs at the v19 database

The Caddy /odoo redirect and seed-odoo.py's --url default were checked and
are already correct: the odoo service kept port 8069."
```

---

### Task 6: Regenerate the stale analysis caches

**Files:**
- Modify: `graphify-out/`, `.code-review-graph/` (regenerated, not hand-edited)

- [ ] **Step 1: Regenerate**

Both caches hold roughly 465 references to `addons18` and to files that no longer exist. They are
generated artefacts, not source, and a stale code graph is worse than none — the next agent that
asks "where is `_lock_or_create`" gets two answers, one of which is a deleted file. Regenerate with
whatever produced them; if the generator is not available, delete the caches rather than leave them
lying. Check `.gitignore` first: if they are ignored, this task is a local hygiene step with no
commit.

- [ ] **Step 2: Verify**

```bash
grep -rl "addons18" graphify-out .code-review-graph 2>/dev/null | head
```

Expected: nothing.

---

### Task 7: Second instance reseed — optional, before any switcher demo

Not required for the handoff tag. Required before the PWA *Lagerumschalter* is demonstrated.

- [ ] **Step 1: Create and seed `lager2_o19`**

```bash
docker compose --profile second-odoo run --rm --no-deps -T odoo-lager-2 \
  odoo --no-http --stop-after-init --workers=0 --max-cron-threads=0 \
  -d lager2_o19 \
  -i base,stock,stock_picking_batch,mail,picking_assistant_core,picking_assistant_integration,quality_alert_custom
docker compose --profile second-odoo up -d odoo-lager-2
python infrastructure/scripts/seed-odoo.py --url http://localhost:8070 --db lager2_o19 \
  --user admin --api-key <key generated on lager2_o19>
```

- [ ] **Step 2: Update the live `.env`** `ODOO_INSTANCES_JSON` `lager-2` entry to
`"db":"lager2_o19"` with the new password/key, restart `backend`.

- [ ] **Step 3: Verify** — switch instances in the PWA and confirm the picking list changes. The old
`lager2` database stays in place as its own rollback artefact.

---

### Task 8: End-to-end smoke on the v19 stack

The cutover is not done because containers started. It is done because a picker can pick.

**Interfaces:**
- Consumes: everything above.
- Produces: the evidence rows of the exit gate.

- [ ] **Step 1: Addon suite, unchanged command, twice**

```bash
docker compose --profile odoo19-trial run --rm --no-deps -T odoo19-trial \
  odoo --no-http --test-enable --stop-after-init \
  --workers=0 --max-cron-threads=0 \
  -d masterfischer_o19_foundation_test -u picking_assistant_integration
```

Expected: green, twice, identical. **This is also the proof that Risk R1's mitigation works**: the
production `odoo` container is now running with cron threads on the same PostgreSQL cluster, and if
`db_name` did not pin it, this run dies with `SerializationFailure` exactly as it did for lane R2.
A green run here with the live service up is a stronger result than the same run was before the
cutover. If it fails with `SerializationFailure`, do not retry it with the live service stopped —
that hides the defect. Fix `db_name`.

- [ ] **Step 2: Backend suite**

```bash
cd backend && PYTHONPATH=.deps python -m pytest -p pytest_asyncio tests/ -q
```

Expected: green. `pytest` is vendored, gitignored, at `backend/.deps` **in the main tree only** — it
does not exist in worktrees. From a worktree, point `PYTHONPATH` at the main tree's copy. Do not
build a venv.

- [ ] **Step 3: The picking flow, by hand, against `masterfischer_o19`**

Through the PWA at `https://<LAN_HOST>/`, not through curl. Minimum path: log in; open a picking;
scan/confirm a line; complete the picking; confirm the transfer is `done` in Odoo at
`http://<HOST>:8069/`. Then a quality alert with a photo, and confirm the attachment lands in the
**new** `odoo19_data` volume, not in `odoo_data`.

- [ ] **Step 4: Cluster picking specifically**

Do not fold this into Step 3. `backend/app/services/cluster_service.py` chooses between
`stock.package` (Odoo 19) and `stock.quant.package` (Odoo 18) at runtime by probing `ir.model`. On
`masterfischer_o19` that branch resolves to `stock.package` **in production for the first time**;
until now only the trial exercised it. Run a cluster of at least `CLUSTER_MIN_ORDERS` (2, ideally
4+) through to `action_done` and confirm each order's goods land in its own package.

- [ ] **Step 5: The four new crons**

`odoo/addons/picking_assistant_integration/data/ir_cron.xml` adds four cron records the v18 tree
never had: `_cron_recover_stalled_jobs` (every **1 minute**), `_cron_cleanup_ephemeral` (10 minutes),
`_cron_cleanup_audit` (daily), `_cron_cleanup_job_resources` (daily). With `max_cron_threads = 1`
these now run **in production, continuously, for the first time**. Leave the stack up for at least
fifteen minutes and read the log. Expected: `_cron_recover_stalled_jobs` fires roughly fifteen times
and does nothing, since there are no integration jobs yet. Any traceback here is a blocker — a
one-minute cron that raises will raise about 1400 times a day.

- [ ] **Step 6: Confirm the rollback artefacts are intact**

```bash
docker compose exec db psql -U odoo -l | grep -E "masterfischer|lager2"
docker volume ls | grep -E "odoo_data|odoo_lager2_data|odoo19"
```

Expected: `masterfischer` present, `odoo_data` present, both untouched. Record the output; §4 depends
on it.

---

## 3. What this plan deliberately does not do

Stated so that a reviewer does not read an omission as an oversight.

- It does not convert the Caddy `/odoo` **redirect** into a reverse proxy, does not add
  `trusted_proxies`, does not pin the Caddy image, and does not add `request_body max_size`. Those
  are Foundation Task 15 obligations under decisions §3.5 and §3.8 and are still frozen.
- It does not add a `secrets:` block to Compose. R3's deployment obligation requires `uid`, `gid`
  and `mode` on it; that belongs to whoever wires it, in Task 15.
- It does not change `RUNTIME_PROFILE`'s `${RUNTIME_PROFILE:-development}` default
  (`docker-compose.yml:155`). That residual was adjudicated and stands; it belongs with the
  deployment work.
- It does not touch `infrastructure/scripts/init-n8n-db.sql` or the `db` service. That is R4.
- It does not remove the `odoo19-trial` service, and it does not delete `odoo_data`,
  `odoo_lager2_data`, `masterfischer` or `lager2`.
- It does not attempt any data migration. There is nothing to migrate.

---

## 4. Rollback

`git revert` restores the addon files and the Compose file. **The database state is the real
question, and the answer is that there is no database question — because nothing was destroyed.**
That is the whole point of creating a new database and a new volume rather than upgrading in place.

**Rollback window: open until the operator deletes `odoo_data`, and no earlier than 14 days of green
running.** The window is bounded by an explicit act, not by a timer, so it cannot lapse by accident.
While it is open, `masterfischer`, `lager2`, `odoo_data` and `odoo_lager2_data` are load-bearing and
must not be pruned.

**To roll back, in this order:**

1. **Stop the v19 stack.** `docker compose stop odoo odoo-lager-2 backend`. Do not `down -v`.
2. **Revert the cutover commit.** `git revert --no-commit <Task 2 SHA>` restores `odoo/addons18/`,
   `odoo/Dockerfile`, and the `odoo`/`odoo-lager-2` service definitions. Also revert Task 3 and Task
   5 if they landed. `odoo/odoo.conf` and `odoo/odoo-lager2.conf` were never modified, so they need
   no revert — that is why Task 2 created new config files instead of editing the old ones.
3. **Restore two lines in the live `.env`:** `ODOO_DB=masterfischer` and the old `ODOO_API_KEY` (the
   pre-cutover copy kept per Task 3 Step 2 item 5). The old key is still valid because
   `masterfischer` was never touched. If `ODOO_INSTANCES_JSON` was changed in Task 7, restore
   `"db":"lager2"` too.
4. **Rebuild and start.** `docker compose build odoo && docker compose up -d odoo backend`.
5. **Verify.** `docker compose logs odoo` shows an Odoo 18 boot against `masterfischer`; the PWA
   serves a picking list; `curl -sk https://localhost/api/health` is healthy.
6. **Leave `masterfischer_o19` and `odoo19_data` in place.** They cost nothing and a second cutover
   attempt then starts from Task 4 Step 4 rather than Task 4 Step 1.

**Two things that are NOT recoverable by this procedure, and must be understood before the window
closes:**

- **Anything created in `masterfischer_o19` after the cutover is lost on rollback.** Picks, quality
  alerts, photos, integration jobs — all of it lives only in the new database. This is why the
  window is measured in days of *running* and why the plan says to close it deliberately: the longer
  the v19 stack is used, the more a rollback costs, until at some point rolling back is worse than
  fixing forward. That crossover is a judgement the operator makes, and this plan's job is to make
  sure it is made rather than stumbled into.
- **`ODOO_API_KEY` is per-database.** Rolling back the code without rolling back the key gives a
  backend that boots and then 401s on every JSON-RPC call. Step 3 is not optional.

**Partial rollback, which is usually the better move:** because the v18 tree only exists as a
`git revert` and the v18 *database* is untouched, a v18 container can be brought up alongside the
v19 one on a spare port for comparison without reverting anything, by temporarily adding a service
that uses `odoo:18.0`, `./odoo/addons18` restored from `git show <SHA>^:odoo/addons18`, and
`odoo_data`. Prefer this for diagnosing a suspected regression; it does not disturb the v19 stack.

---

## 5. Exit gate

The cutover counts as done when **all** of the following are recorded green, in one pass, on the
merged tree.

- [ ] **G1.** `docker compose config --quiet` passes, and `grep -rn "addons18\|odoo:18.0"` over
      `docker-compose.yml` and `odoo/` returns nothing.
- [ ] **G2.** `odoo/addons18/` does not exist, and its deletion is in the **same commit** as the
      Compose rebuild. Verify with `git show --stat <Task 2 SHA>` — one commit, both halves.
- [ ] **G3.** The addon suite is green twice, identical, with the **live v19 `odoo` service running**,
      using the unchanged `--profile odoo19-trial run --rm --no-deps -T` command (Task 8 Step 1).
- [ ] **G4.** The backend suite is green.
- [ ] **G5.** The manual picking flow, the cluster-picking flow and a photo-bearing quality alert all
      complete end to end against `masterfischer_o19` (Task 8 Steps 3–4).
- [ ] **G6.** Fifteen minutes of cron log with no traceback (Task 8 Step 5).
- [ ] **G7.** `masterfischer`, `lager2`, `odoo_data` and `odoo_lager2_data` are all confirmed present
      and untouched (Task 8 Step 6), and the rollback window's closing condition is written down
      where the operator will find it.
- [ ] **G8.** The runtime fact sheet `docs/superpowers/specs/2026-07-30-odoo19-runtime-facts.md`
      matches the Compose file key for key.

**Register entries this closes** — and where, given §0.3:

- [ ] **G9.** **Decision §3.4** is amended from "narrow approved port — or deleted" to the executed
      answer: **deleted**, with this plan's Task 2 commit SHA as the evidence. This closes the
      register's standing live-system exposure — that `odoo/addons18/` was serving production while
      carrying the unfixed `_lock_or_create` throttle defect and the M1 session-revocation hole
      (re-severitied to **High**) — because the code serving production becomes the fixed v19 tree.
- [ ] **G10.** The "Raised during remediation" entries *"The live Odoo-18 stack still carries the
      expired-lease hole"* and *"`odoo/addons18/` still serves the live stack"* are marked resolved
      by execution.
- [ ] **G11.** The whole-branch gate line *"the v18 auth-port suite, if that port survives decision
      §3.4"* is struck: the port did not survive, so that gate item is void rather than pending.
- [ ] **G12.** **These three edits do not happen on `codex/odoo19-cutover`**, because
      `docs/superpowers/parallel/2026-07-23-program-status.md` does not exist on it (§0.3). They
      happen on the branch that carries the file, at integration time — the same correction the
      register already recorded once for R1's exit gate. Do not create a second copy of the status
      file on this branch to satisfy a checkbox; that is how the register got two homes in the first
      place.
- [ ] **G13.** **The tag.** After the integrator merges this branch:
      ```bash
      cd "$WT/00-integration-bachelor-hardening"
      git merge --no-ff codex/odoo19-cutover -m "merge: establish Odoo 19 foundation base"
      git tag -a wave1-odoo19-handoff -m "Odoo 19 runtime and addon handoff"
      ```
      The Odoo-19 runtime fact gate (G8) is attached to that merge review. The Foundation worktree
      then rebases onto `codex/integration-bachelor-hardening` before touching Compose or Core.
- [ ] **G14.** With the tag in place, the following unblock: **Foundation Task 12** (Odoo-19 core
      idempotency handoff), **Task 15** (Compose, network, Caddy, TLS — which must preserve the G8
      facts), **Task 16** (blocked behind 12 and 15), **Task 17**, and **R4 Step 9** (whose own exit
      gate currently requires recording that Step 9 is *not* done for lack of this tag).

---

## 6. Risks this plan found that the brief did not anticipate

Ordered by how much damage they do if missed.

**R1 — `dbfilter` does not constrain Odoo's cron master; a live v19 container would run this addon's
crons against `masterfischer` and against the addon test database. (Critical, mitigated in Task 2.)**
This is the most important finding in this plan and it is the mechanism behind a failure the
programme has already paid for. `dbfilter` is applied by `odoo.http.db_list`, i.e. at the HTTP layer.
The cron master enumerates with `odoo.service.db.list_dbs(force=True)`, which applies **no filter at
all** and returns every database on the cluster. That is exactly why "a concurrently running Odoo
service with cron threads writes `ir_cron` during module load and kills the run with
`SerializationFailure`" — the recorded fact that cost lane R2 a green run — and why
`--max-cron-threads=0` is load-bearing in the test command. **The cutover makes this strictly worse
before it makes it better**, because the v19 addon adds four cron records the v18 tree never had,
one of them on a one-minute interval, and promotes them onto the always-on default service. Two
consequences the brief did not consider: (a) the addon test suite would become permanently
un-runnable while the production stack is up; (b) an Odoo 19 cron master attaching to
`masterfischer`, an **Odoo 18** database, is an unreviewed interaction against the artefact this
plan's entire rollback strategy depends on being pristine. The fix is one line — `db_name =
masterfischer_o19` in `odoo19.conf` — because Odoo's cron master honours `db_name` when it is set,
and it is the only mechanism that does. Task 8 Step 1 is written to *detect* the failure rather than
work around it.

**R2 — the retired `odoo.conf` published the Odoo database manager on the LAN, and a naive cutover
would have carried that forward. (Important, fixed in Task 2.)** `odoo/odoo.conf` has
`list_db = True`, and the `odoo` service publishes `"8069:8069"` — **all interfaces**, not
`127.0.0.1`. The trial service had already made the safer choice on both counts (`list_db = False`,
`127.0.0.1:8100`). The obvious implementation of "point the `odoo` service at v19" is to keep
`odoo.conf` and change only the mount, which silently promotes the trial's *addon* while retaining
the v18 *posture*. The brief's framing — "which volume, which service name" — did not surface the
config file as a decision at all. It is one, and the answer is a new file derived from the trial
config. The port stays public because Caddy's `/odoo` redirect sends admins there and the thesis
demo needs it; `list_db = False` is what makes that acceptable.

**R3 — `backend/app/config.py` would have hard-rejected several plausible database names.
(Important, avoided by naming, verified in Task 3 Step 3.)** `ODOO19_TRIAL_PROFILE_NAMES` and
`ODOO19_TRIAL_DB` (`config.py:97-98`) cause line 143 to reject any profile keyed `o19`, `odoo19`,
`o19-trial` or `odoo19-trial` whose database is not exactly `masterfischer_o19_trial`. A cutover
that had reused the `o19-trial` profile for production, or had named the production database
`masterfischer_o19_trial` to avoid editing `.env`, would fail at backend startup with a validation
error whose message points at the instance registry rather than at the cutover. Related and in the
opposite direction: `demo_traceability_allowed_dbs` defaults to `masterfischer_o19_trial`, so a
cutover that *did* reuse that name would have silently enabled demo traceability in production. The
chosen name `masterfischer_o19` avoids both, and Task 3 Step 3 checks it explicitly instead of
assuming.

**R4 — `ODOO_API_KEY` is bound to the database and becomes invalid the moment the backend points at
the new one. (Important, handled in Task 4 Step 5.)** The live `.env` carries a 40-character API key
issued against `masterfischer`. A cutover that changes `ODOO_DB` but not `ODOO_API_KEY` produces a
backend that starts cleanly and then 401s on every JSON-RPC call — a failure mode that looks like a
network problem. The same trap sits in the rollback: restoring the code without restoring the old
key breaks the recovered stack. Both directions are now explicit steps.

**R5 — `odoo-lager-2` mounts `addons18` too, and deleting the directory breaks the instance
switcher. (Important, handled in Task 2 and Task 7.)** The brief lists the service but treats the
addons18 mount at `:88` as a footnote. It is not: `odoo-lager-2` is the second instance behind the
PWA *Lagerumschalter*, which is a demonstrated thesis feature with its own plan
(`2026-06-27-odoo-instance-switch.md`). Its config `odoo/odoo-lager2.conf` — which the brief does not
mention exists — and its database `lager2` are both v18. Repointing it in the cutover commit is
mandatory (otherwise Compose still references a deleted directory); reseeding `lager2_o19` is Task 7
and the switcher is **broken until Task 7 runs**. Stated openly here so it is not discovered during
a demonstration.

**R6 — the four new crons run in production for the first time on cutover day. (Important, verified
in Task 8 Step 5.)** `ir_cron.xml` in the v19 tree adds `_cron_recover_stalled_jobs` (1 min),
`_cron_cleanup_ephemeral` (10 min), `_cron_cleanup_audit` (daily) and `_cron_cleanup_job_resources`
(daily). Until now they have only ever executed inside `--test-enable` runs. On the live service they
become continuous background load against real data, and the retention cron in particular is the
subject of open finding **#11** ("retention deletes delivered/dead outbox rows regardless of job
state; the watchdog then tolerates a missing outbox"), owned by R2 and not yet verified closed by a
second reviewer. This is an additional, independent reason for pre-flight **P3**: cutting over before
R2 merges puts an unfixed retention cron on a daily schedule against production data. A one-minute
cron that raises does so about 1400 times a day.

**R7 — `docker compose down -v` at any point in this procedure bricks the stack, and it is the
reflex command for "start clean". (Important, stated as a Global Constraint.)** Open finding #14:
`init-n8n-db.sql` presupposes the `n8n_app` role created by the unmounted `init-db-roles.sh`, and is
mounted into `docker-entrypoint-initdb.d` where it runs against `POSTGRES_DB=postgres` with no
`\connect n8n`. An empty `pg_data` volume therefore aborts during init. That defect is invisible
today because nobody has emptied the volume — and a cutover is precisely the occasion on which
somebody would. The cutover itself never needs a fresh cluster; it creates a database inside the
existing one.

**R8 — the exit gate cannot tick its own register checkboxes from this branch, and the brief asked
for exactly that. (Process, handled as G12.)** The register file lives only on
`remediation/r2-odoo`. This is the second time this exact shape has appeared: R1's exit gate was
written to require edits to a file its own branch did not carry, and the register itself recorded
the defect with the note "Recorded so the next plan does not repeat the shape." G12 exists so this
plan is not the third instance.

**R9 — the `odoo19_trial_data` volume is declared with an explicit global `name:` and is therefore
not project-scoped. (Minor, avoided.)** `docker-compose.yml:288` pins the name, so any other Compose
project on the same host addressing `odoo19_trial_data` gets the same volume. Reusing it for
production — which is the tempting shortcut, since the trial database already works — would put the
production filestore in a globally-addressable volume and would also mean the trial and production
share attachments. A separate project-scoped `odoo19_data` costs one line.

**R10 — `quality_alert_custom/models/quality_alert.py` survives as the CRLF copy. (Cosmetic,
noted.)** The two trees' copies are byte-identical after line-ending normalisation; the v19 one is
CRLF. After deletion, `git diff --check` will warn on every added line in any future edit to it,
exactly as it already does for `backend/app/main.py`. Do not "fix" the line endings in the cutover
commit — that would put a whole-file diff inside the one commit that most needs to be readable.

**R11 — `docs/SETUP.md` line 40 tells the operator to create databases through
`http://<HOST>:8069/web/database/manager`, which Task 2 makes unreachable. (Minor, fixed in Task 5
Step 3.)** A document that instructs an operator to visit a URL that now returns an error is worse
than no document; Task 5 replaces it with the CLI command that actually works.

---

## 7. One-line summary for the status file

> **2026-07-30 — Odoo-19 cutover plan written** (`docs/superpowers/plans/2026-07-30-odoo19-cutover.md`,
> branch `codex/odoo19-cutover`). Decision §3.4 executed as **delete**. Eight tasks: runtime fact
> sheet; one commit carrying the Compose rebuild **and** the `addons18/` deletion; `.env.example`;
> fresh database `masterfischer_o19` created and seeded, `masterfischer` retained intact as the
> rollback artefact; defaults and docs; cache regeneration; second-instance reseed; end-to-end smoke.
> Gated on R1/R2/R3 merging and the whole-branch gate; **not** gated on R4, which is gated on this
> plan's tag instead. Produces `wave1-odoo19-handoff`, unblocking Foundation Tasks 12, 15, 16, 17 and
> R4 Step 9.
