# Odoo-19 Cutover Plan

> **For agentic workers:** REQUIRED SUB-SKILL: use `superpowers:executing-plans` (or
> `superpowers:subagent-driven-development`) to work this plan task by task. Steps use `- [ ]`
> checkbox syntax.
>
> **This document is the deliverable of branch `codex/odoo19-cutover`. Writing it is complete when
> it is committed. Executing it is a separate, later decision by the project owner.** No step in
> this file may be executed as a side effect of reviewing it. Task 0 and Task 1 in particular
> require a running Docker daemon that did not exist when the plan was written.

**Companion document:** every factual claim below is traceable to
`docs/superpowers/plans/2026-07-31-odoo19-cutover-facts.md` (F0-F10). Where the facts file says
**UNESTABLISHED**, this plan says so too rather than papering over it.

---

**Goal:** Make Odoo 19 the productive runtime. Delete `odoo/addons18/` in the *same commit* that
repoints Compose at `odoo/addons/`, so the live `odoo` service can never start with an empty addons
mount. Stand up a fresh v19 database by reseed. Leave `codex/odoo19-cutover` in a state the
integrator can merge and tag `wave1-odoo19-handoff`, which unblocks Foundation Tasks 12, 15, 16, 17.

**Architecture:** This is a **reseed, not a migration** (F5). Three facts force it:
`masterfischer` is served by a v18 container built from `odoo:18.0` (F2); the v19 addon tree carries
five models the v18 tree has never had — `picking.assistant.outbox`,
`picking.assistant.integration.job`, `picking.assistant.webhook.nonce`,
`picking.assistant.event.receipt`, `picking.assistant.callback.receipt` (F3); and the repository
contains no migration tooling of any kind, while it *does* contain a seeder whose docstring reads
"Seed-Daten für Odoo 19 Community" and whose documented target database is `masterfischer` (F5).
The cutover therefore creates a **new** v19 database beside the old one on the same cluster (F4),
and leaves `masterfischer` byte-for-byte untouched. That is what makes rollback cheap: rollback is a
`git revert` plus an image rebuild, not a database restore.

**Tech Stack:** Docker Compose, `odoo:19.0` Community, PostgreSQL 16, XML-RPC seeding
(`infrastructure/scripts/seed-odoo.py`), Caddy, FastAPI backend, n8n 2.13.3.

---

## Global Constraints

1. **The atomic-commit constraint is real and is wider than the commission stated.** The live `odoo`
   service resolves `picking_assistant_integration` only through
   `./odoo/addons18:/mnt/extra-addons:ro` (`docker-compose.yml:61`). **A second service has the same
   dependency: `odoo-lager-2` mounts `./odoo/addons18` at `docker-compose.yml:88`.** Both mounts
   must move in the commit that deletes the directory, or the `second-odoo` profile breaks the next
   time anyone starts it. The commission named only the first.
2. **`masterfischer` is never opened by a v19 process.** Enforced structurally, not by discipline:
   after the cutover `odoo/odoo.conf` carries a `dbfilter` that does not match `masterfischer`, and
   `list_db = False`. This is what preserves the rollback window.
3. **Never run `make clean`** during the cutover window. `Makefile:116` is
   `docker compose down -v --rmi local`; `-v` destroys `pg_data`, which holds `masterfischer`,
   `masterfischer_o19_trial` and n8n's database on one volume (F4).
4. **`.env` is not in the repository** (`Makefile:11`, `.gitignore`). Every `.env` change below is an
   **operator action that no commit can carry**. Only `.env.example` is committable (F10).
5. **Do not pre-empt Foundation Task 15.** Task 15 will remove `ports:` from every Odoo service and
   split `picking-net` into `edge-net` / `core-net` / `automation-net` (F9). This plan keeps the
   existing single network and the existing `8069:8069` publication so Task 15 has exactly one
   change to make, not one change plus one revert.
6. **Odoo 18 knowledge is deleted, not archived.** `odoo/addons18/README.md` records the one
   substantive porting difference (`res.groups.privilege` in v19 vs `res.groups.category_id` in
   v18). Task 3 moves that sentence into `odoo/addons/` before deleting the file, so the knowledge
   survives the deletion.

---

## 0. Corrections of record — where the commission and the files disagree

Recorded rather than silently fixed, because a reviewer checking the commission against `git` will
otherwise conclude the plan is wrong.

1. **Three named background documents do not exist on this branch** (F0):
   `docs/superpowers/parallel/2026-07-23-program-status.md`,
   `docs/superpowers/parallel/2026-07-29-handoff.md`, and the house-style reference
   `docs/superpowers/plans/2026-07-29-r4-postgres-handoff.md`. The entire `parallel/` directory is
   absent. **Consequence: frozen decisions §3.4 and §3.8 and the debt register could not be read at
   source.** Where this plan acts on them it says "as commissioned", not "as verified".
2. **The Caddy `request_body max_size` requirement could not be re-derived** (F7). The Foundation
   plan contains no `request_body`, no `max_size`, no Caddy version constraint. The requirement is
   carried forward on the commission's authority alone.
3. **`RUNTIME_PROFILE` is not merely missing — it is a live security hole.** The commission framed it
   as a hardening nice-to-have. `backend/app/config.py:175` reads
   `if candidate.runtime_profile != "production": return`, so the whole of
   `validate_runtime_security()` is skipped today, because Compose never sets the variable and the
   default is `"development"` (F8). This is a defect, not a polish item, and Task 5 treats it as one.
4. **An uncommitted cutover plan for the same work already exists**: `2026-07-30-odoo19-cutover.md`,
   1030 lines, untracked, no commit touches it (F0b). It reaches the same reseed conclusion
   independently. This plan does not delete it; see "Decisions owed by the owner", D6.
5. **The escape hatch does not open.** The commission asked to say loudly if `masterfischer` were
   already v19. **It is not** (F2). The plan does not collapse.

---

## Task 0: Establish the two live facts that no file can settle

**Gate:** Docker was down when this plan was written (facts file, header). Nothing after this task
may run until Task 0 has been run with the daemon up and its output pasted into this file.

**Files:**
- Modify: `docs/superpowers/plans/2026-07-31-odoo19-cutover-facts.md` (paste results under F2, F6)

**Interfaces:**
- Consumes: a running Docker daemon; the existing `db` service.
- Produces: a confirmed major version for `masterfischer`, and a confirmed data census that either
  authorises or forbids the reseed.

- [ ] **Step 1: Confirm the daemon and the database inventory (read-only)**

```bash
export PATH="$PATH:/mnt/c/Program Files/Docker/Docker/resources/bin"
docker.exe version --format '{{.Server.Version}}'
cd "/mnt/c/Users/endri/Desktop/Bachelor/Mobile Picking und Voice Assistant"
docker.exe compose exec -T db psql -U "${POSTGRES_USER:-odoo}" -d postgres \
  -c "SELECT datname, pg_size_pretty(pg_database_size(datname)) FROM pg_database ORDER BY 1;"
```

Expected: `masterfischer`, `masterfischer_o19_trial`, `n8n` and `postgres` on one cluster (F4). If
`masterfischer` is absent, **stop** — the whole premise is wrong and the owner must be asked.

- [ ] **Step 2: Prove the major version of `masterfischer` — READ ONLY, `psql` not `odoo shell`**

`odoo shell` against `masterfischer` from a v19 image is forbidden: it can trigger a registry load
against a v18 schema. Use SQL:

```bash
docker.exe compose exec -T db psql -U "${POSTGRES_USER:-odoo}" -d masterfischer \
  -c "SELECT name, latest_version, state FROM ir_module_module WHERE name IN ('base','picking_assistant_integration','picking_assistant_core','quality_alert_custom') ORDER BY name;"
```

Expected: `base.latest_version` begins `18.0`. If it begins `19.0`, **stop and tell the owner
loudly** — the cutover collapses to a Compose rename and Tasks 1, 6 and 7 are unnecessary.
Also expected: `picking_assistant_integration.latest_version = 18.0.1.0.0`, matching
`odoo/addons18/picking_assistant_integration/__manifest__.py:3` (F3).

- [ ] **Step 3: Census the live data — this decides whether reseed is acceptable (F6)**

```bash
docker.exe compose exec -T db psql -U "${POSTGRES_USER:-odoo}" -d masterfischer -c "
SELECT 'stock.picking' AS model, state, count(*), min(create_date), max(create_date)
  FROM stock_picking GROUP BY state
UNION ALL SELECT 'stock.move.line', '', count(*), min(create_date), max(create_date) FROM stock_move_line
UNION ALL SELECT 'res.partner', '', count(*), min(create_date), max(create_date) FROM res_partner
UNION ALL SELECT 'quality.alert', '', count(*), min(create_date), max(create_date) FROM quality_alert
ORDER BY 1,2;"
```

Read it against F6's expectation of seed-only content. The signal that **refutes** seed-only, and
therefore blocks the reseed: `stock_picking` rows in state `done` with `create_date` clustered after
the last seeding run, or `res_partner` rows that are not the seeder's demo customers
(`seed-odoo.py:256-267`, `build_demo_customers()`).

- [ ] **Step 4: Record the verdict**

Paste both outputs verbatim into the facts file under F2 and F6, replacing the **UNESTABLISHED**
markers. If Step 3 refutes seed-only, **stop the plan here and escalate D1** (below). Do not proceed
to Task 3 on an assumption.

---

## Task 1: Pre-cutover backup **with a rehearsed restore**

**Gate:** Task 0 green.

A backup nobody has restored is a rumour. This task takes the backup and then proves it by restoring
it into a disposable copy — using the tool the repository already ships for exactly this
(`infrastructure/scripts/clone-postgres-volume.sh`, F10), which refuses to run while a container
mounts the source volume, verifies with SHA-256 manifests plus matching `PG_VERSION`, and stamps an
identity token into the copy so a rehearsal can never be mistaken for the original.

**Files:**
- Create: `infrastructure/backups/` entries (untracked; `.gitignore` must cover them)
- Modify: `.gitignore` — add `infrastructure/backups/`

**Interfaces:**
- Consumes: `infrastructure/scripts/clone-postgres-volume.sh` (`create|verify|delete|assert-target|compose-up`);
  the `db` service; the `pg_data` volume.
- Produces: a logical dump of `masterfischer`, a verified volume clone, and a **timed** restore
  rehearsal whose measured duration becomes the rollback budget in Task 7.

- [ ] **Step 1: Logical dump of the live database, custom format**

```bash
cd "/mnt/c/Users/endri/Desktop/Bachelor/Mobile Picking und Voice Assistant"
mkdir -p infrastructure/backups
STAMP=$(date +%Y%m%d-%H%M%S)
docker.exe compose exec -T db pg_dump -U "${POSTGRES_USER:-odoo}" -Fc masterfischer \
  > "infrastructure/backups/masterfischer-${STAMP}.dump"
docker.exe compose exec -T db pg_dumpall -U "${POSTGRES_USER:-odoo}" --globals-only \
  > "infrastructure/backups/globals-${STAMP}.sql"
sha256sum infrastructure/backups/masterfischer-${STAMP}.dump | tee "infrastructure/backups/masterfischer-${STAMP}.sha256"
```

Expected: a non-empty `.dump`, and `pg_restore --list` on it names `stock_picking` and
`ir_module_module`.

- [ ] **Step 2: Back up the Odoo filestore**

The database dump does **not** contain attachments. `odoo_data:/var/lib/odoo`
(`docker-compose.yml:59`) holds `filestore/masterfischer`.

```bash
docker.exe run --rm -v odoo_data:/src:ro -v "$PWD/infrastructure/backups":/out alpine \
  tar czf "/out/odoo_filestore-${STAMP}.tgz" -C /src .
```

Expected: the archive lists `./filestore/masterfischer/`.

- [ ] **Step 3: REHEARSE the restore — this is the step that makes Step 1 real**

Stop the stack first (`clone-postgres-volume.sh` refuses to clone a mounted source), clone the
volume, bring the clone up under a **separate Compose project name**, and restore the dump into it.

```bash
docker.exe compose down                        # NOT down -v (Global Constraint 3)
bash infrastructure/scripts/clone-postgres-volume.sh create \
  pg_data pg_data_rehearsal infrastructure/backups/manifests
bash infrastructure/scripts/clone-postgres-volume.sh verify \
  pg_data pg_data_rehearsal infrastructure/backups/manifests
bash infrastructure/scripts/clone-postgres-volume.sh compose-up \
  infrastructure/backups/manifests pg_data_rehearsal cutover-rehearsal
```

Then, against the rehearsal project only:

```bash
docker.exe compose -p cutover-rehearsal exec -T db \
  psql -U "${POSTGRES_USER:-odoo}" -d postgres -c "CREATE DATABASE masterfischer_restore_test;"
docker.exe compose -p cutover-rehearsal exec -T db \
  pg_restore -U "${POSTGRES_USER:-odoo}" -d masterfischer_restore_test \
  < "infrastructure/backups/masterfischer-${STAMP}.dump"
docker.exe compose -p cutover-rehearsal exec -T db \
  psql -U "${POSTGRES_USER:-odoo}" -d masterfischer_restore_test \
  -c "SELECT count(*) FROM stock_picking;"
```

Expected: `pg_restore` exits 0, and the `stock_picking` count **equals the number Task 0 Step 3
recorded**. Anything else means the backup is not restorable and the cutover must not proceed.

- [ ] **Step 4: Time it and tear the rehearsal down**

Record the wall-clock time from "start restore" to "count matches". That number, plus the image
rebuild time measured in Task 6, is the rollback budget quoted in Task 7.

```bash
docker.exe compose -p cutover-rehearsal down
bash infrastructure/scripts/clone-postgres-volume.sh delete \
  pg_data_rehearsal infrastructure/backups/manifests
```

Expected: `docker volume ls` no longer lists `pg_data_rehearsal`; `pg_data` still exists.

- [ ] **Step 5: Keep the backups out of git**

Add `infrastructure/backups/` to `.gitignore` and confirm `git status --short` shows nothing under
it. The dump contains credentials hashes; it must never be committed.

---

## Task 2: Create the fresh v19 database *before* the cutover commit

**Gate:** Task 1 green.

Ordering matters. The new database is created and seeded while the v18 stack is still the default,
using the existing `odoo19-trial` profile — the one invocation pattern that is safe
(`--profile odoo19-trial run --rm --no-deps -T odoo19-trial`, never `exec odoo`). If seeding fails,
nothing has been cut over and there is nothing to roll back.

**Files:**
- Modify: `odoo/odoo19-trial.conf` — `dbfilter` must admit the new database name (currently
  `^masterfischer_o19_trial$`, `odoo/odoo19-trial.conf:11`)

**Interfaces:**
- Consumes: `odoo19-trial` service (`docker-compose.yml:93-117`), `odoo/addons` mount (line 115),
  `infrastructure/scripts/seed-odoo.py`.
- Produces: a populated v19 database with `picking_assistant_core`,
  `picking_assistant_integration` and `quality_alert_custom` installed.

> **The database name is owner-owned — see D2.** This plan writes `${NEW_DB}` throughout. The
> recommended value is `masterfischer_o19`, because it keeps the `masterfischer` prefix that
> `backend/app/config.py:98` and `docker-compose.yml:158` already pattern on.

- [ ] **Step 1: Widen the trial dbfilter to admit `${NEW_DB}`**

`odoo/odoo19-trial.conf:11` is `dbfilter = ^masterfischer_o19_trial$`. Change to
`dbfilter = ^masterfischer_o19(_trial)?$` (or the regex matching D2's chosen name). Leave
`list_db = False` (line 12) alone.

- [ ] **Step 2: Create and initialise `${NEW_DB}` under the trial profile**

```bash
docker.exe compose --profile odoo19-trial run --rm --no-deps -T odoo19-trial \
  odoo -d "${NEW_DB}" -i base,stock,stock_picking_batch,picking_assistant_core,picking_assistant_integration,quality_alert_custom \
  --without-demo=all --stop-after-init
```

Expected: exit 0; the container is gone (`--rm`); `docker compose ps` shows no `odoo19-trial`.
Then confirm from `db`:

```bash
docker.exe compose exec -T db psql -U "${POSTGRES_USER:-odoo}" -d "${NEW_DB}" \
  -c "SELECT name, latest_version, state FROM ir_module_module WHERE state='installed' AND name LIKE 'picking%' OR name='quality_alert_custom' ORDER BY name;"
```

Expected: `picking_assistant_integration` at `19.0.1.0.0` (F3), state `installed`.

- [ ] **Step 3: Seed it**

`seed-odoo.py` speaks XML-RPC, so the service must be listening. Start it, seed, stop it.

```bash
docker.exe compose --profile odoo19-trial up -d odoo19-trial
python infrastructure/scripts/seed-odoo.py \
  --url http://localhost:8100 --db "${NEW_DB}" --user admin --api-key "${ODOO_API_KEY}"
docker.exe compose --profile odoo19-trial stop odoo19-trial
docker.exe compose --profile odoo19-trial rm -f odoo19-trial
```

Port `8100` is `docker-compose.yml:111` (`127.0.0.1:${ODOO19_TRIAL_PORT:-8100}:8069`), loopback-only.

Expected: the seeder reports created locations, products and pickings; a repeat run is idempotent
(`find_or_create`, `seed-odoo.py:~180`). Confirm counts:

```bash
docker.exe compose exec -T db psql -U "${POSTGRES_USER:-odoo}" -d "${NEW_DB}" \
  -c "SELECT state, count(*) FROM stock_picking GROUP BY state;"
```

Expected: a non-zero row count in `assigned`/`confirmed`, comparable to what Task 0 Step 3 found in
`masterfischer`.

- [ ] **Step 4: Run the v19 Odoo test suite against a throwaway, not against `${NEW_DB}`**

```bash
docker.exe compose --profile odoo19-trial run --rm --no-deps -T odoo19-trial \
  odoo -d "${NEW_DB}_test" -i picking_assistant_integration \
  --test-enable --test-tags /picking_assistant_integration --stop-after-init
```

Expected: the eight test modules under `odoo/addons/picking_assistant_integration/tests/` (F3) pass.
Drop `${NEW_DB}_test` afterwards.

---

## Task 3: THE ATOMIC COMMIT — delete `addons18/` and rework Compose

**Gate:** Tasks 0-2 green. This is the only irreversible-looking step, and it is reversible by
`git revert` (Task 7) precisely because Task 2 left `masterfischer` untouched.

**Files:**
- Delete: `odoo/addons18/` — all 24 files (23 code/asset files + `README.md`, F3)
- Modify: `docker-compose.yml`
- Modify: `odoo/Dockerfile`
- Modify: `odoo/odoo.conf`
- Modify: `odoo/odoo-lager2.conf`
- Modify: `odoo/addons/README.md` (create, carrying forward the porting note from
  `odoo/addons18/README.md`)
- Modify: `.env.example`

**Interfaces:**
- Consumes: the v19 tree at `odoo/addons/` (F3), `${NEW_DB}` from Task 2.
- Produces: a stack whose default `odoo` service is v19; the Odoo-19 service/image/mount facts that
  Foundation Task 15 is required to preserve (F9).

### Exactly which Compose keys change

| # | Key | From | To | Why |
|---|---|---|---|---|
| 1 | `services.odoo.build.args.ODOO_BASE_IMAGE` (line 46) | `odoo:18.0` | `odoo:19.0` | the version decision |
| 2 | `services.odoo.volumes[2]` (line 61) | `./odoo/addons18:/mnt/extra-addons:ro` | `./odoo/addons:/mnt/extra-addons:ro` | **the constraint** — without this in the same commit the container starts with an empty addons path |
| 3 | `services.odoo` comment (line 40) | `── Odoo 18 Community (Live/Default) ──` | `── Odoo 19 Community (Live/Default) ──` | the comment is the first thing a reader trusts |
| 4 | `services.odoo-lager-2.build.args.ODOO_BASE_IMAGE` (line 71) | `odoo:18.0` | `odoo:19.0` | second consumer of `addons18` |
| 5 | `services.odoo-lager-2.volumes[2]` (line 88) | `./odoo/addons18:/mnt/extra-addons:ro` | `./odoo/addons:/mnt/extra-addons:ro` | **the constraint, second occurrence — the commission missed this one** |
| 6 | `services.odoo19-trial` (lines 92-117) | whole service, incl. `profiles: [odoo19-trial]` | **removed** | the profile gating disappears; v19 is no longer a trial |
| 7 | `volumes.odoo19_trial_data` (lines 287-288) | declared with `name: odoo19_trial_data` | **kept, with a comment** | see note below — removing it here orphans the trial filestore during the rollback window |
| 8 | `services.backend.environment.ODOO_DB` (line 132) | `${ODOO_DB:-picking}` | `${ODOO_DB:?ODOO_DB muss gesetzt sein}` | the `picking` default is a database that does not exist; a silent wrong default is how a cutover looks green and serves nothing |

**Keys that deliberately do NOT change**, so Foundation Task 15 has one clean edit (Global
Constraint 5): `services.odoo.ports` stays `8069:8069`; `networks` stays the single `picking-net`;
`services.backend.environment.ODOO_URL` stays `http://odoo:8069` (it names the *service*, and the
service keeps its name — that is why the backend, Caddy and n8n need no change at all).

`services.odoo.volumes[0]` (`odoo_data:/var/lib/odoo`, line 59) also does not change. The filestore
is per-database (`/var/lib/odoo/filestore/<db>`), so `${NEW_DB}` gets a fresh subdirectory and
`filestore/masterfischer` stays intact for rollback.

**On key 7:** `odoo19_trial_data` is where Task 2's work lives if the trial service ever wrote a
filestore. Deleting the declaration in this commit would leave a dangling volume and remove the
paper trail. Delete it in a follow-up commit after the rollback window closes (Task 7 Step 5).

### Config-file changes in the same commit

- `odoo/Dockerfile` line 1: `ARG ODOO_BASE_IMAGE=odoo:18.0` → `ARG ODOO_BASE_IMAGE=odoo:19.0`.
  Compose passes the arg explicitly, so this only fixes the default for anyone building the
  directory by hand — but leaving it at 18.0 after `addons18/` is gone is a trap.
- `odoo/odoo.conf` line 11: `dbfilter = ^(picking|masterfischer)$` → `dbfilter = ^${NEW_DB}$`.
  **This is the safety interlock of the whole plan** (Global Constraint 2): after the commit the
  productive v19 container is structurally unable to open `masterfischer`.
- `odoo/odoo.conf` line 12: `list_db = True` → `list_db = False`. With `list_db = True` the v19 DB
  manager would offer `masterfischer` in a dropdown regardless of the filter's intent.
- `odoo/odoo-lager2.conf` line 11: `dbfilter = ^(lager2|picking2|masterfischer2)$` — these are v18
  databases that a v19 `odoo-lager-2` must not open either. Narrow to the v19 name the owner
  chooses for the second warehouse, or, if there is none, set
  `dbfilter = ^$` so the profile cannot open anything until D3 is answered.
- `odoo/addons/README.md` (new): carry over the porting note from `odoo/addons18/README.md` —
  "Odoo 19 security XML uses `res.groups.privilege`, Odoo 18 used `res.groups.category_id`" — plus a
  line recording that `addons18/` was deleted in this commit and is recoverable from git history.
- `.env.example` line 10: `ODOO_DB=picking` → `ODOO_DB=masterfischer_o19` (or D2's value).

- [ ] **Step 1: Make every change above in one working tree, commit nothing yet**

- [ ] **Step 2: Prove the deletion and the repoint are in the same change set**

```bash
git add -A
git diff --cached --stat -- "Mobile Picking und Voice Assistant/odoo/addons18" \
  "Mobile Picking und Voice Assistant/docker-compose.yml"
git diff --cached -- "Mobile Picking und Voice Assistant/docker-compose.yml" | grep -E '^\+.*addons'
```

Expected: the stat shows 24 deletions under `addons18/` **and** the compose diff shows **two** added
`./odoo/addons:/mnt/extra-addons:ro` lines (the `odoo` service and `odoo-lager-2`), and **zero**
remaining `addons18` references:

```bash
grep -rn "addons18" "Mobile Picking und Voice Assistant/" --exclude-dir=docs
```

Expected: no output. (Under `docs/` the string survives in historical plans; that is correct.)

- [ ] **Step 3: Validate the file before committing**

```bash
cd "Mobile Picking und Voice Assistant" && docker.exe compose config >/dev/null
```

Expected: exit 0 and no `odoo19-trial` in the rendered output. `docker compose config` will fail on
the new `${ODOO_DB:?…}` unless `.env` already carries it — that failure is the feature working; set
`.env` first (Task 4 Step 1).

- [ ] **Step 4: Commit**

```
feat(odoo)!: make Odoo 19 the productive runtime and delete the v18 addon tree

BREAKING CHANGE: the `odoo` service now builds odoo:19.0 and mounts odoo/addons.
`odoo/addons18/` is deleted; the `odoo19-trial` profile is removed. ODOO_DB must
be set explicitly and must name a v19 database. The live v18 database
`masterfischer` is untouched and remains restorable — see
docs/superpowers/plans/2026-07-31-odoo19-cutover.md Task 7.
```

---

## Task 4: Operator-side switch (`.env`) — not carried by any commit

**Gate:** Task 3 committed but **not yet deployed**.

`.env` lives only in the operator's checkout at `Desktop/Bachelor/` and is git-ignored (F10, Global
Constraint 4). These are hand edits.

**Files:**
- Modify (operator machine, untracked): `Mobile Picking und Voice Assistant/.env`

**Interfaces:**
- Consumes: `.env.example` as committed by Task 3.
- Produces: an environment whose `ODOO_DB` names the v19 database.

- [ ] **Step 1: Set `ODOO_DB=${NEW_DB}`** in `.env`. Without it, Task 3 key 8 makes the stack refuse
  to start — deliberately.
- [ ] **Step 2: Update `ODOO_INSTANCES_JSON`** if it carries an `o19-trial` entry pointing at
  `http://odoo19-trial:8069`. That service no longer exists (Task 3 key 6); the entry must point at
  `http://odoo:8069` or be removed. `backend/tests/test_instance_registry.py:76-79` shows the
  registry rejects a mismatched db name, so a stale entry fails loudly rather than silently.
- [ ] **Step 3: Leave `DEMO_TRACEABILITY_ALLOWED_DBS` alone** unless D2 changes the name; its
  default `masterfischer_o19_trial` (`docker-compose.yml:158`) only matters when
  `DEMO_TRACEABILITY_ENABLED=true`.
- [ ] **Step 4: Verify** `docker.exe compose config | grep -A2 "ODOO_DB"` renders `${NEW_DB}`.

---

## Task 5: Image pinning, the `secrets:` block, and `RUNTIME_PROFILE`

**Gate:** Task 3 committed. **Separate commit, deliberately.** These changes are independent of the
`addons18` constraint, and folding them into the atomic commit would make the cutover revert
(Task 7) also revert the security hardening. One rollback, one concern.

**Files:**
- Modify: `docker-compose.yml`
- Modify: `.env.example`
- Modify: `infrastructure/caddy/Caddyfile`

**Interfaces:**
- Consumes: `read_secret()`'s permission contract from the Foundation plan (a secret file with any
  bit set in `0o077` is rejected — F8); `backend/app/config.py:69,175`.
- Produces: reproducible image resolution; file-based secrets at `/run/secrets/pwr_*`; a fail-closed
  runtime profile. Foundation Task 15 consumes all three.

### 5a — Pinning (F7: **no service in the file is digest-pinned today**)

- [ ] **Step 1: Pin every floating tag.** Current state and the shape of the fix:

| Service | Line | Today | Action |
|---|---|---|---|
| `caddy` | 4 | `caddy:2-alpine` | pin to a concrete **>= 2.10** tag, e.g. `caddy:2.10.2-alpine`, then append `@sha256:…` |
| `pwa` | 275 | `caddy:2-alpine` | **same pin as `caddy`** — two Caddies drifting apart is worse than one unpinned |
| `db` | 21 | `postgres:16-alpine` | pin the patch, e.g. `postgres:16.10-alpine`, plus digest. **Never bump the major** — that would silently require a `pg_upgrade` of `pg_data` |
| `whisper` | 168 | `…:latest` | pin to the digest currently running (`docker image inspect`), because `:latest` has no recoverable version |
| `ollama` | 189 | `…:latest` | same |
| `n8n` | 200 | `…:2.13.3` | append `@sha256:…`; the tag is already right |
| `odoo` / `odoo-lager-2` | 46 / 71 (post-Task 3) | `odoo:19.0` | `odoo:19.0` is a moving tag. Pin the digest in the build arg |

Resolve digests from what is actually running, not from the registry's current `latest`:

```bash
docker.exe image inspect caddy:2-alpine --format '{{index .RepoDigests 0}}'
```

- [ ] **Step 2: Caddy >= 2.10 and `request_body max_size`.** The commission attributes this to frozen
  decision §3.8, which **could not be read** (F0, F7); `infrastructure/caddy/Caddyfile` contains no
  `request_body` directive today. Add, inside the `:443` block, before the `handle /api/*` at
  `Caddyfile:4`:

```
request_body {
    max_size 16MB
}
```

  `16MB` mirrors `N8N_PAYLOAD_SIZE_MAX: 16` (`docker-compose.yml:258`) so the two limits cannot
  disagree. **Confirm the number with the owner (D5)** — the facts file could not source it.
  Verify the pinned image really has the directive:
  `docker.exe run --rm caddy:2.10.2-alpine caddy build-info` and a `caddy validate` of the file.

### 5b — The `secrets:` block (F8: none exists today)

- [ ] **Step 3: Add the top-level block with explicit `uid`, `gid`, `mode` on every entry.**
  The explicit `mode` is not decoration: Docker mounts secrets `0444` by default, and
  `read_secret()` rejects any file with a bit set in `0o077`, so a default-mounted secret fails
  backend startup (F8).

```yaml
secrets:
  pwr_backend_to_n8n_active_hmac:
    file: ./infrastructure/secrets/pwr_backend_to_n8n_active_hmac
  pwr_backend_to_n8n_previous_hmac:
    file: ./infrastructure/secrets/pwr_backend_to_n8n_previous_hmac
  pwr_n8n_to_backend_active_hmac:
    file: ./infrastructure/secrets/pwr_n8n_to_backend_active_hmac
  pwr_n8n_native_header:
    file: ./infrastructure/secrets/pwr_n8n_native_header
  pwr_n8n_callback_legacy:
    file: ./infrastructure/secrets/pwr_n8n_callback_legacy
  session_throttle_hmac:
    file: ./infrastructure/secrets/session_throttle_hmac
```

  and per service, with the ownership the container actually runs as:

```yaml
  backend:
    secrets:
      - source: pwr_backend_to_n8n_active_hmac
        target: pwr_backend_to_n8n_active_hmac      # → /run/secrets/…
        uid: "1000"
        gid: "1000"
        mode: 0400
```

  The five `/run/secrets/pwr_*` target names are fixed by the Foundation plan (F8). `uid`/`gid` must
  match the container's runtime user — read it, do not guess:
  `docker.exe compose run --rm --no-deps -T backend id -u`. n8n's official image runs as `node`
  (uid 1000); the backend image's uid must be checked the same way.
  `./infrastructure/secrets/` goes into `.gitignore`; only a `README.md` naming the six files is
  committed.

- [ ] **Step 4: Point the env vars at the files.** Replace the direct values at
  `docker-compose.yml:148-151` and `222-224` with their `*_FILE` counterparts.
  `read_secret(direct, file_path)` **raises if both are set** (F8), so leaving the old variables in
  place alongside the new ones fails startup — remove them in the same edit.

### 5c — `RUNTIME_PROFILE` (F8: the gate at `backend/app/config.py:175` is open today)

- [ ] **Step 5: Make it fail closed.** Add to `services.backend.environment`:

```yaml
      RUNTIME_PROFILE: ${RUNTIME_PROFILE:?RUNTIME_PROFILE muss gesetzt sein (production|development)}
```

  and to `.env.example`: `RUNTIME_PROFILE=production`, alongside `MOBILE_HEADER_GRACE_MODE=false`
  (`validate_runtime_security()` rejects grace mode in production, `config.py:~184`).

- [ ] **Step 6: Prove the gate is now closed.**

```bash
RUNTIME_PROFILE= docker.exe compose config   # must fail with the German message
```

  Then with `RUNTIME_PROFILE=production` and a deliberately weak secret, `docker compose up backend`
  must exit non-zero with the message from `validate_runtime_security()`. **A backend that starts
  clean here without any secret configured means the gate is still open** — that is the whole point
  of the step.

- [ ] **Step 7: Commit separately**

```
chore(compose): pin every image, mount secrets as files, fail closed on RUNTIME_PROFILE
```

---

## Task 6: Deploy and verify

**Gate:** Tasks 3-5 committed, Task 4 applied on the operator machine.

**Files:** none (runtime only).

**Interfaces:**
- Consumes: the committed stack.
- Produces: the measured rebuild time that completes Task 7's rollback budget.

- [ ] **Step 1: Bring the new default up, timed**

```bash
time docker.exe compose up -d --build odoo
docker.exe compose logs --tail=80 odoo
```

Expected: the log line reports Odoo **19.0**; `Modules loaded` appears; **no** "database not
initialized" and no `dbfilter` rejection. Record the elapsed time.

- [ ] **Step 2: Prove the addon path resolved**

```bash
docker.exe compose exec -T odoo ls /mnt/extra-addons
```

Expected: `picking_assistant_core  picking_assistant_integration  quality_alert_custom` — i.e. the
mount that Task 3 key 2 repointed is live. This is the direct test of the owner's constraint.

- [ ] **Step 3: Prove `masterfischer` is unreachable from v19**

```bash
curl -sS http://localhost:8069/web/database/list -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","method":"call","params":{}}'
```

Expected: `masterfischer` does **not** appear (`list_db = False` plus the narrowed `dbfilter`,
Task 3). If it appears, stop and fix the config before any user touches the stack.

- [ ] **Step 4: Prove `masterfischer` still exists and is intact**

```bash
docker.exe compose exec -T db psql -U "${POSTGRES_USER:-odoo}" -d masterfischer \
  -c "SELECT latest_version FROM ir_module_module WHERE name='base';"
```

Expected: still `18.0.…` — **unchanged from Task 0 Step 2**. A v19 value here means something opened
and upgraded the live database; that is a rollback trigger and a data-loss event.

- [ ] **Step 5: Application-level verification**

```bash
make verify-code        # backend pytest (Makefile:88-89)
make verify-stack       # infrastructure/scripts/test-api.py (Makefile:103-104)
make verify-workflows   # n8n contract check (Makefile:80-81)
make test-ui            # Playwright confirm-flow, pickings, quality-alert (Makefile:56-57)
```

Expected: all four green. `make verify-stack` is the one that actually exercises the backend against
the new v19 Odoo.

- [ ] **Step 6: Manual smoke** — log into the PWA over `https://${LAN_HOST}`, open a picking, confirm
  a line, and confirm a quality alert reaches n8n. This is the only step that proves end-to-end that
  the picker's job still works.

---

## Task 7: The rollback window, and closing it

**Files:** none until Step 5.

**Interfaces:**
- Consumes: the Task 3 commit SHA, the Task 1 backups, the timings from Task 1 Step 4 and Task 6
  Step 1.
- Produces: either a restored v18 stack or a closed window.

### THE ROLLBACK TRIGGER

Roll back — do not debug in place — if **any** of these is true:

- **R1.** Task 6 Step 4 shows `base.latest_version` in `masterfischer` at `19.0.*`. The live database
  has been touched by v19. **Immediate, non-negotiable.**
- **R2.** Task 6 Step 1 does not reach `Modules loaded` within 15 minutes, or the log shows an
  unresolved module dependency.
- **R3.** Task 6 Step 2 does not list all three modules.
- **R4.** `make verify-stack` fails and the cause is not a configuration typo fixable in under
  30 minutes.
- **R5.** The Task 6 Step 6 manual smoke cannot complete a pick confirmation.
- **R6.** Task 0 Step 3 was skipped or its output was not pasted into the facts file. Rolling back
  from an unverified premise is cheaper than discovering the premise was wrong later.

Anything else — cosmetic bugs, missing seed rows, a slow first request — is not a rollback trigger.

### THE ROLLBACK PROCEDURE (execute under pressure, top to bottom)

Budget: (Task 6 Step 1 rebuild time) + about two minutes. **No database restore is needed in the
normal case**, because `masterfischer` was never opened by v19 (Global Constraint 2) and
`odoo_data`'s `filestore/masterfischer` was never touched (Task 3, key `volumes[0]`).

- [ ] **RB1. Stop the stack. Type this exactly. `-v` is not in it and must never be.**

```bash
cd "/mnt/c/Users/endri/Desktop/Bachelor/Mobile Picking und Voice Assistant"
docker.exe compose down
```

- [ ] **RB2. Revert the cutover commit.** This restores all 24 files under `odoo/addons18/` and every
  Compose and `.conf` key in one operation — that is exactly why they were one commit.

```bash
git revert --no-edit <TASK_3_COMMIT_SHA>
```

  If Task 5 was already committed, revert **only** Task 3's SHA. Task 5's pinning and secrets do not
  depend on the Odoo version and should stay.

- [ ] **RB3. Put `.env` back.** `ODOO_DB=masterfischer`. (Task 4 changed it; the revert cannot,
  because `.env` is not in git — Global Constraint 4.) Restore the `ODOO_INSTANCES_JSON` value too if
  Task 4 Step 2 changed it.

- [ ] **RB4. Rebuild and start the v18 stack.**

```bash
docker.exe compose up -d --build odoo
docker.exe compose logs --tail=80 odoo
```

  Expected: the log reports Odoo **18.0**; `Modules loaded`; the database selector offers
  `masterfischer`.

- [ ] **RB5. Verify the live data is exactly as it was.**

```bash
docker.exe compose exec -T db psql -U "${POSTGRES_USER:-odoo}" -d masterfischer -c \
  "SELECT state, count(*) FROM stock_picking GROUP BY state;"
```

  Expected: **identical to Task 0 Step 3's output.** Then `make verify-stack`.

- [ ] **RB6. Only if RB5 differs — restore from Task 1.** This is the trigger-R1 path.

```bash
docker.exe compose stop odoo backend
docker.exe compose exec -T db psql -U "${POSTGRES_USER:-odoo}" -d postgres \
  -c "ALTER DATABASE masterfischer RENAME TO masterfischer_damaged_$(date +%Y%m%d);"
docker.exe compose exec -T db psql -U "${POSTGRES_USER:-odoo}" -d postgres \
  -c "CREATE DATABASE masterfischer;"
docker.exe compose exec -T db pg_restore -U "${POSTGRES_USER:-odoo}" -d masterfischer \
  < "infrastructure/backups/masterfischer-${STAMP}.dump"
docker.exe run --rm -v odoo_data:/dst -v "$PWD/infrastructure/backups":/in alpine \
  tar xzf "/in/odoo_filestore-${STAMP}.tgz" -C /dst
docker.exe compose up -d odoo backend
```

  **Rename, never `DROP`.** The damaged database is the only evidence of what went wrong.
  The restore duration is the number measured in Task 1 Step 4 — quote it to the owner, do not
  estimate it.

- [ ] **RB7. Record what happened** in this file under a new "Rollback executed" heading: the
  trigger, the timings, and the state of `masterfischer` before and after.

### Closing the window

- [ ] **Step 5 (after the owner declares the window closed — D4):** a follow-up commit removes the
  `volumes.odoo19_trial_data` declaration (Task 3, key 7), drops `masterfischer_o19_trial`, and
  `DROP DATABASE masterfischer` **only** after a final dump is stored off-machine. Until then,
  leaving a dormant v18 database costs a few hundred megabytes and buys an unlimited rollback.

---

## Task 8: What precisely satisfies `wave1-odoo19-handoff`

**This branch cannot create the tag.** F9: the tag is an annotated tag placed by the **integrator**,
on the **integration branch** `codex/integration-bachelor-hardening`, on the merge commit of
`codex/odoo19-cutover` (Foundation plan lines 88-93). `git tag -l "*wave*"` here is empty. What this
branch owes is a mergeable, reviewable state.

**Files:** none.

**Interfaces:**
- Consumes: Tasks 3-6 complete.
- Produces: the "Odoo-19 runtime fact gate" that the Foundation plan requires to be attached to the
  merge review, and the "Odoo-19 service/image/mount facts" Task 15 must preserve.

- [ ] **Step 1: The handoff checklist — every item must be demonstrable, not asserted**

- [ ] H1. `odoo/addons18/` does not exist. `git ls-files | grep addons18` → empty.
- [ ] H2. The `odoo` service builds `odoo:19.0` and mounts `./odoo/addons` — `docker compose config`
      output pasted into the merge review. **These are the "service/image/mount facts" Task 15 is
      instructed to preserve (F9).**
- [ ] H3. No `profiles: [odoo19-trial]` remains anywhere in `docker-compose.yml`.
- [ ] H4. The v19 Odoo test suite passes (Task 2 Step 4) — the eight test modules under
      `odoo/addons/picking_assistant_integration/tests/`.
- [ ] H5. `${NEW_DB}` exists, is seeded, and `picking_assistant_integration` reports
      `19.0.1.0.0 / installed`.
- [ ] H6. `make verify-code`, `verify-stack`, `verify-workflows`, `test-ui` all green (Task 6 Step 5).
- [ ] H7. `masterfischer` is provably still at `base 18.0.*` and still restorable (Task 6 Step 4,
      Task 1 Step 3).
- [ ] H8. `docs/superpowers/plans/2026-07-31-odoo19-cutover-facts.md` has no remaining
      **UNESTABLISHED** marker.

- [ ] **Step 2: Tell the integrator what to do**, verbatim, so the tag lands in the right place:

```bash
cd "$WT/00-integration-bachelor-hardening"
git merge --no-ff codex/odoo19-cutover -m "merge: establish Odoo 19 foundation base"
git tag -a wave1-odoo19-handoff -m "Odoo 19 runtime and addon handoff"
```

- [ ] **Step 3: What unblocks downstream, and what does not.**
  Task 12 (`odoo/addons/picking_assistant_core/**` — `models/idempotency.py`, `data/ir_cron.xml`,
  `migrations/19.0.2.0.0/pre-migrate.py`, `tests/`) becomes startable the moment the tag exists and
  the Foundation branch has rebased onto the integration branch (F9). It needs
  `picking_assistant_integration.group_api_service` resolvable at v19, which H4/H5 demonstrate.
  Task 15 becomes startable at the same moment, and inherits three things this plan deliberately did
  **not** do: removing Odoo `ports:`, splitting `picking-net`, and the `docker-compose.dev.yml`
  override (Global Constraint 5).

---

## Verification Summary — what must be green

| Gate | Command / check | Expected |
|---|---|---|
| Live version | Task 0 Step 2 | `masterfischer` `base` at `18.0.*` |
| Data census | Task 0 Step 3 | consistent with seed-only (F6) |
| Backup restorable | Task 1 Step 3 | `pg_restore` exit 0, row counts match |
| v19 DB seeded | Task 2 Step 3 | non-zero pickings in `${NEW_DB}` |
| v19 addon tests | Task 2 Step 4 | 8 test modules pass |
| Atomicity | Task 3 Step 2 | 24 deletions + 2 repointed mounts in one commit; `grep addons18` empty |
| Compose renders | Task 3 Step 3 | `docker compose config` exit 0, no `odoo19-trial` |
| Runtime version | Task 6 Step 1 | log reports Odoo 19.0 |
| Mount resolved | Task 6 Step 2 | three modules under `/mnt/extra-addons` |
| Live DB isolated | Task 6 Step 3 | `masterfischer` not in the DB list |
| **Live DB intact** | Task 6 Step 4 | `base` still `18.0.*` |
| Application | Task 6 Step 5 | `verify-code`, `verify-stack`, `verify-workflows`, `test-ui` green |
| Human | Task 6 Step 6 | a pick can be confirmed |
| Secrets closed | Task 5 Step 6 | backend refuses to start without `RUNTIME_PROFILE` |
| Handoff | Task 8 Step 1 | H1-H8 all demonstrable |

**Rollback trigger:** R1-R6 in Task 7. R1 (live database touched by v19) is immediate and
non-negotiable.

---

## Decisions owed by the owner

These are not the plan's to make. Each is blocking for the task named.

**D1 — Is the reseed acceptable? (blocks Task 3; the only one that can void the plan)**
F6 could not be verified: Docker was down. Every document in the repository calls `masterfischer` a
demo database, and the seeder's own docstring targets it — but that is circumstantial.
- *Option A — reseed (this plan).* Zero migration cost. **Consequence: everything in `masterfischer`
  since the last seeding is gone from the productive stack** (recoverable from the Task 1 dump, but
  not usable in v19 without a migration that does not exist).
- *Option B — Odoo's paid upgrade service.* `masterfischer` goes to upgrade.odoo.com and comes back
  as v19. **Consequence: money, an external data transfer of the whole database, an unbounded
  schedule, and the custom addons still need porting because the upgrade service does not know
  them.** Nothing in this repository automates it.
- *Option C — reseed plus selective re-entry.* Reseed, then re-enter by hand whatever Task 0 Step 3
  showed was real. **Consequence: manual effort proportional to the census; only viable for a small
  number of records.**
- *Option D — do not cut over.* **Consequence: Foundation Tasks 12, 15, 16, 17 stay blocked
  indefinitely (F9).**
Run Task 0 Step 3 **before** answering.

**D2 — The name of the new v19 database. (blocks Task 2)**
Recommendation `masterfischer_o19`, because `backend/app/config.py:98` and
`docker-compose.yml:158` already pattern on the `masterfischer` prefix. Reusing the name
`masterfischer` for the v19 database is also possible.
- *Consequence of reusing the name:* the rollback window closes immediately — there is no longer a
  v18 database to fall back to, and Task 7's cheap `git revert` path becomes the expensive RB6
  restore path. **The plan recommends against it.**

**D3 — What happens to `odoo-lager-2` and the `second-odoo` profile. (blocks Task 3)**
It mounts `addons18` (`docker-compose.yml:88`) and filters on the v18 databases `lager2`,
`picking2`, `masterfischer2` (`odoo/odoo-lager2.conf:11`). None of them has a v19 counterpart.
- *Option A — bump to v19 with `dbfilter = ^$`.* Profile stays declared, cannot open anything until
  a v19 second-warehouse database exists. **Consequence: the profile is inert but honest.**
- *Option B — delete the service and its volume in the same atomic commit.* **Consequence: the
  second-warehouse feature is gone until someone rebuilds it.**
- *Option C — create v19 counterparts for its three databases now.* **Consequence: triples Task 2.**
The plan assumes A.

**D4 — How long the rollback window stays open. (blocks Task 7 Step 5)**
`masterfischer` and `masterfischer_o19_trial` keep costing disk until dropped.
- *Consequence of a short window (days):* disk freed sooner, and a defect discovered in week three
  can no longer be rolled back — only restored from a dump.
- *Consequence of a long window (weeks):* an unlimited cheap rollback, at the cost of two dormant
  databases on the same cluster (F4).
The plan takes no position; it only refuses to drop anything without an explicit instruction.

**D5 — The `request_body max_size` value and the Caddy pin. (blocks Task 5 Step 2)**
Frozen decision §3.8 could not be read (F0, F7). The plan proposes `16MB` to mirror
`N8N_PAYLOAD_SIZE_MAX: 16` (`docker-compose.yml:258`).
- *Consequence of too low:* legitimate photo or PDF uploads are rejected at the proxy, before any
  application error message can explain why.
- *Consequence of too high:* the limit stops being a limit.
Also confirm the exact Caddy tag; the plan cannot verify from this branch that 2.10 is the first
version with the directive.

**D6 — What happens to the untracked `2026-07-30-odoo19-cutover.md`. (blocks nothing; owed for tidiness)**
An uncommitted 1030-line plan for the same work exists (F0b) and reaches the same conclusion.
- *Option A — commit both, this one as the current plan.* **Consequence: two plans in `plans/`; a
  future reader must be told which is authoritative.**
- *Option B — commit only this one and discard the other.* **Consequence: a session's work is lost,
  including its own independently-derived corrections.**
- *Option C — merge them into one file.* **Consequence: effort now, one artefact later.**
This plan commits itself and its facts file only, and leaves the 07-30 file untracked and
untouched.

---

## What could not be established, and why

| Question | Status | Why |
|---|---|---|
| `odoo --version` inside the live container | not run | Docker daemon down (facts header) |
| `base.latest_version` in `masterfischer` | **UNESTABLISHED** | same — Task 0 Step 2 settles it |
| Whether `masterfischer` holds real business history | **UNESTABLISHED** | same — Task 0 Step 3 settles it; **this one can void the plan (D1)** |
| Frozen decisions §3.4 / §3.8, debt register | not read | `docs/superpowers/parallel/` absent on this branch (F0) |
| Caddy version that introduced `request_body max_size` | not verified | no source on this branch (F7); D5 |
| The `uid`/`gid` the backend container runs as | not read | needs a running container; Task 5 Step 3 reads it rather than guessing |
| Current image digests for pinning | not read | needs a daemon; Task 5 Step 1 reads them from what is running |
