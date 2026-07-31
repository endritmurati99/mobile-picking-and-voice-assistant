# Odoo-19 Cutover Plan

> **For agentic workers:** REQUIRED SUB-SKILL: use `superpowers:executing-plans` (or
> `superpowers:subagent-driven-development`) to work this plan task by task. Steps use `- [ ]`
> checkbox syntax.
>
> **This document is the deliverable of branch `codex/odoo19-cutover`. Writing it is complete when
> it is committed. Executing it is a separate, later decision by the project owner.** No step in
> this file may be executed as a side effect of reviewing it.

**Revision 2 (2026-07-31).** Revision 1 was written with Docker down and with
`docs/superpowers/parallel/` unreadable from this branch. Both conditions are gone. This revision:

- replaces every **UNESTABLISHED** fact with a live read-only probe result (§0.1);
- replaces every "as commissioned, unverified" citation of frozen decisions §3.4 / §3.8 with the
  register's actual words, read from
  `/mnt/c/Users/endri/Desktop/Bachelor/Mobile Picking und Voice Assistant/docs/superpowers/parallel/2026-07-23-program-status.md`
  in the main tree (the file exists only there — see §0.3);
- folds in the owner's decisions D1, D2, D3 and D6, which are no longer open;
- **corrects two errors of its own** — the `dbfilter` safety interlock, which does not hold
  (Global Constraint 2), and the claim that the `picking` database does not exist, which is false;
- supersedes the untracked `2026-07-30-odoo19-cutover.md` and takes eleven findings from it.

**Companion document:** `docs/superpowers/plans/2026-07-31-odoo19-cutover-facts.md` (F0-F10) carries
the file-derived facts. Live-cluster facts are recorded in §0.1 of this file, because they were
established after that file was written.

---

**Goal:** Make Odoo 19 the productive runtime. Delete `odoo/addons18/` in the *same commit* that
repoints Compose at `odoo/addons/`, so neither `odoo` nor `odoo-lager-2` can ever start with an
empty addons mount. Stand up two freshly seeded v19 databases. Leave `codex/odoo19-cutover` in a
state the integrator can merge and tag `wave1-odoo19-handoff`, which unblocks Foundation Tasks 12,
15, 16, 17 and R4 Step 9.

**Architecture:** This is a **reseed, not a migration** (F5), and the owner has confirmed it (D1).
Three facts force it: `masterfischer` is a v18 database served by a v18 container (§0.1); the v19
addon tree carries five models the v18 tree has never had (F3); and the repository contains no
migration tooling of any kind, while it *does* contain a seeder whose docstring reads "Seed-Daten
für Odoo 19 Community" (F5). The cutover therefore creates **new** v19 databases beside the old
ones on the same cluster (F4), and leaves `masterfischer` and `lager2` byte-for-byte untouched.
That is what makes rollback cheap: rollback is a `git revert` plus an image rebuild, not a database
restore.

**Tech Stack:** Docker Compose, `odoo:19.0` Community, PostgreSQL 16, XML-RPC seeding
(`infrastructure/scripts/seed-odoo.py`), Caddy, FastAPI backend, n8n 2.13.3.

---

## 0. Facts and corrections of record

### 0.1 The live cluster — probed read-only on 2026-07-31, Docker Desktop up

CLI: `/mnt/c/Program Files/Docker/Docker/resources/bin/docker.exe` (WSL integration is OFF; run it
from the project directory and convert any path argument with `wslpath -w`). All queries were
`docker.exe compose exec -T db psql -U odoo -d <db> -tAc '<SELECT>'`.

**Databases on the one shared cluster** (`SELECT datname FROM pg_database`):

| Database | Odoo major (`base.latest_version`) | Notes |
|---|---|---|
| `masterfischer` | **18.0.1.3** | the live/productive database |
| `lager2` | **18.0.1.3** | the `second-odoo` warehouse; **no `picking_assistant_*` module installed** |
| `picking` | **18.0.1.3** | exists — **Revision 1 wrongly said it did not** |
| `masterfischer_o19_trial` | 19.0.1.3 | v19; addon *not* installed; carries 45 `done` + 21 `assigned` pickings |
| `masterfischer_o19_foundation_test` | 19.0.1.3 | v19 **with `picking_assistant_integration = 19.0.1.0.0`** |
| `odoo19_smoke_codex` | 19.0.1.3 | v19 smoke database; not declared in Compose or any `.conf` |
| `n8n`, `postgres` | — | not Odoo |

`masterfischer_o19_trial` and `odoo19_smoke_codex` were **not** in the facts file's F4 list; they
are now. `masterfischer_o19_foundation_test` is the standing proof that the v19 addon installs
cleanly on a v19 database — the cutover is not attempting anything unrehearsed.

**`masterfischer` is Odoo 18. Confirmed, not inferred.** `base = 18.0.1.3`, `stock = 18.0.1.1`,
`picking_assistant_integration = 18.0.1.0.0`. **The "already v19, plan collapses" escape hatch is
definitively closed.**

**Modules installed in `masterfischer`** — this is the authoritative `-i` list for the new database:
`picking_assistant_core 18.0.1.0.0`, `picking_assistant_integration 18.0.1.0.0`,
`quality_alert_custom 18.0.1.1.0`, `stock 18.0.1.1`, `stock_picking_batch 18.0.1.0`,
`stock_sms 18.0.1.0`.

**What `masterfischer` actually holds** — this was Revision 1's D1 blocker, and it is answered:

| Table | Rows | Range |
|---|---|---|
| `stock_picking` | **66** (46 `done`, 20 `assigned`) | created 2026-03-22 .. 2026-07-25 |
| `stock_move_line` | 420 | — |
| `res_partner` | 9 | — |
| `product_product` | 54 | — |
| `res_users` | 7 | — |
| `mail_message` | 1558 | 2025-01-13 .. 2026-07-25 |

`sale_order` and `account_move` **do not exist as tables** — the sale and accounting modules were
never installed. So: **not empty seed data, but thesis working data. No customer records, no
accounting, no invoices, no financial history.** That is the finding on which the owner decided D1.

`lager2` holds 9 `assigned` pickings and no completed ones.

### 0.2 What frozen decisions §3.4 and §3.8 actually say

Revision 1 cited both "as commissioned, unverified". They are now quoted at source.

**§3.4 — the Odoo-18 port.** Verbatim:

> **The Odoo-18 port is a narrow, formally approved auth-compatibility port — or it is deleted.**
> `odoo/addons18/picking_assistant_integration` may contain session, auth and throttle only. It
> must carry its own test module. "Keep both addons in sync" is withdrawn as guidance: full parity
> would itself violate the spec, which forbids a Foundation copy under `addons18`. A parity matrix
> listing exactly which models are ported and which are deliberately absent lives in that addon's
> README.

**This plan executes the second branch: deleted.** That is not an interpretation — the register's
own "Decisions still owed by the project owner" (handoff §3.1) frames §3.4 as a binary the owner
must resolve, and the owner has resolved it as Odoo-19-only. The register records what deletion
buys, and it is larger than a tidy-up:

> **`odoo/addons18/` still serves the live stack and still carries the unfixed `_lock_or_create`
> defect.** … Until `addons18` is actually deleted per the Odoo-19-only decision, production is
> running the login path R2 Task 5 proved defective — including the M1 session-revocation hole,
> which was re-severitied to High.

and, separately:

> **The live Odoo-18 stack still carries the expired-lease hole.** The fix landed in `odoo/addons/`;
> `odoo/addons18/` serves the running system and now diverges.

So the cutover is the *remedy* for two standing live-system exposures, not merely a version bump.
Debt-register entry **M1** is `High`, `Verified: yes — pre-image of session.py:214-261`: a revoked
session is silently re-blessed and the caller's requested roles are written onto it. That code is
what production runs today.

**§3.8 — the request body limit.** Verbatim:

> **The request body limit is a Task 15 obligation and needs two layers.** `await request.body()`
> necessarily precedes signature verification, and `Content-Length` is bypassable with chunked
> encoding. Caddy's `request_body max_size` protects the edge only and requires Caddy >= 2.10,
> which is a second reason to pin the image. Direct n8n → backend calls need an ASGI-level
> streaming limit as well.

**Consequence, and it is a correction to Revision 1:** `request_body max_size` is **not this plan's
to set**. §3.8 assigns it to Foundation Task 15, and it needs a *second* layer — an ASGI-level
streaming limit — that this plan is not equipped to add and must not half-add. Revision 1's Task 5
Step 2 proposed a blind `16MB` and raised it as decision **D5**; both are withdrawn. What survives
into this plan is the one half §3.8 explicitly hands to whoever deploys first: **pin the Caddy
image, and pin it at >= 2.10 so Task 15 has the directive available when it arrives.**

Related, §3.5, same owner:

> The real obligations that replace it: pin the Caddy image to an explicit version, and set
> `trusted_proxies` explicitly rather than relying on a default of an unpinned image. Owner: Task 15.

This plan does the **pin** (Task 5) and deliberately does **not** touch `trusted_proxies`, the
`/odoo` redirect, or `request_body`. Those stay Task 15's, whole.

### 0.3 The register lives on one branch only, and this branch is not it

`docs/superpowers/parallel/2026-07-23-program-status.md` exists in the **main tree**
(`/mnt/c/Users/endri/Desktop/Bachelor/…`) and not on `codex/odoo19-cutover`. The register itself
already records this exact shape as a plan defect:

> **Plan defect — R1's exit gate pointed it at a file it never had.** … The register must therefore
> be updated at integration, on the branch that actually carries it. … Recorded so the next plan
> does not repeat the shape.

**Therefore no step in this plan edits the register from this branch.** The register edits this
cutover owes are listed in Task 9 as integration-time work, done on the branch that carries the
file. Do not create a second copy of the status file here; that is how the register got two homes
in the first place.

### 0.4 Corrections to Revision 1

1. **The `dbfilter` safety interlock does not hold, and Revision 1's Global Constraint 2 was
   wrong.** `dbfilter` is applied by `odoo.http.db_list`, i.e. **at the HTTP layer only**. Odoo's
   cron master enumerates databases with `odoo.service.db.list_dbs(force=True)`, which applies no
   filter and returns every database on the cluster. `odoo/odoo.conf:16` sets
   `max_cron_threads = 1`, so the live service **does** run a cron master. A v19 `odoo` service with
   an unfiltered cron master would attach to `masterfischer` — an Odoo 18 database — which is
   precisely the artefact the whole rollback strategy depends on being pristine. The mechanism is
   already documented in this programme: the handoff records that "a concurrently running Odoo
   service with cron threads writes `ir_cron` during module load and kills the run with
   `SerializationFailure`", which is why `--max-cron-threads=0` is load-bearing in the addon test
   command. **The fix is `db_name`, not `dbfilter`** — see Global Constraint 2. Credit: the untracked
   07-30 plan found this first (its risk R1).
2. **The `picking` database exists** (§0.1), at Odoo 18. Revision 1's Task 3 key 8 justified making
   `ODOO_DB` mandatory by claiming the default named a database that does not exist. The change is
   still right, but for the opposite reason: `${ODOO_DB:-picking}` silently defaults a **v19**
   container at a **v18** database. That is worse than pointing at nothing.
3. **`request_body max_size` is Task 15's** (§0.2). Revision 1's D5 is withdrawn.
4. **`RUNTIME_PROFILE` is not absent everywhere — it depends which branch you read.** On *this*
   branch `docker-compose.yml` does not mention it (F1, re-verified: `grep -n RUNTIME_PROFILE
   docker-compose.yml .env.example` → no match). The register describes `docker-compose.yml:155` as
   `${RUNTIME_PROFILE:-development}`; that line exists on the R1 lane branch, where line 155 is the
   `CORS_ORIGINS` → `PWA_ORIGINS` rename the register logged as a bounded exception to the compose
   freeze. On this branch line 155 is still `CORS_ORIGINS: "https://${LAN_HOST:-localhost}"`. **This
   is a guaranteed merge collision** and Task 5 is written to expect it — see Task 5 Step 5.
5. **The register adjudicated the `RUNTIME_PROFILE` hardening once already, and did not reject it:**

   > R1 Task 1 round 1 decided to warn rather than fail and that decision stands. The one-character
   > hardening for a real deployment is `${RUNTIME_PROFILE:?set to production for a real
   > deployment}`. **Belongs with the deployment work.**

   This cutover *is* the deployment work. Task 5 does it, and it is discharging a named obligation
   rather than reopening a closed decision.

### 0.5 The 07-30 plan is superseded

`docs/superpowers/plans/2026-07-30-odoo19-cutover.md` (untracked, 1030 lines, no commit touches it)
is an independently written plan for the same work. It reaches the same architectural conclusion.
**It is superseded by this file.** It is not deleted: Task 9 Step 4 commits it alongside this one
with a superseded banner, so a session's work is not thrown away. Eleven of its findings are folded
in here and attributed: Global Constraint 2 (its R1), Task 3's config-file rewrite (R2), Task 2's
name check against `config.py:97-98` (R3), `ODOO_API_KEY` re-issue (R4), `lager2_o19` and the broken
switcher (R5), the four new crons (R6), `down -v` and finding #14 (R7), register edits at
integration (R8), the project-scoped `odoo19_data` volume (R9), the CRLF note (R10), and
`docs/SETUP.md:40` (R11).

---

## Global Constraints

1. **`masterfischer` is never dropped, renamed, overwritten or opened for write. Neither is
   `lager2`.** This is the owner's decision D1 and it is absolute. **No step in this plan, and no
   step in the rollback, may issue `DROP DATABASE masterfischer`, `DROP DATABASE lager2`, or any
   statement that writes to either.** They stay on the cluster as (a) the rollback path and (b) the
   queryable archive of the 66 pickings and the 1558 mail messages. Task 7 Step 6 and Task 8 RB5
   are written to *prove* they are still there afterwards, not to assume it. The only sanctioned
   rename is RB6's `masterfischer_damaged_<date>` on a database v19 has already corrupted — and even
   that is a rename, never a drop.

   **In the owner's words, for the record:** *the 46 completed pickings will not be visible in the
   new stack, and nothing is destroyed.* The new v19 database starts from seed. The history stays
   readable in `masterfischer` by `psql`, or by a temporary v18 container brought up alongside
   (Task 8, "partial rollback").

2. **Isolation from `masterfischer` is enforced by `db_name`, not by `dbfilter`.** `dbfilter` is an
   HTTP-layer filter and does not constrain the cron master (§0.4.1). The productive v19 config
   therefore sets **`db_name = masterfischer_o19`**, which is the only mechanism Odoo's cron master
   honours, *and* `dbfilter = ^masterfischer_o19$` for the HTTP layer, *and* `list_db = False`.
   All three. Removing any one of them reopens the hole.

3. **Never run `make clean`** during the cutover window. `Makefile:116` is
   `docker compose down -v --rmi local`; `-v` destroys `pg_data`, which holds `masterfischer`,
   `lager2`, `picking`, all three v19 databases and n8n's database on one volume (F4, §0.1).
   Independently: an empty `pg_data` does not come back cleanly today — debt-register finding **#14**
   is that `init-n8n-db.sql` presupposes the `n8n_app` role that the unmounted `init-db-roles.sh`
   would create, and runs against `POSTGRES_DB=postgres`. `down -v` is a reflex command and it
   bricks this stack. (07-30 R7.)

4. **`.env` is not in the repository** (`Makefile:11`, `.gitignore`). Every `.env` change below is an
   **operator action that no commit can carry**. Only `.env.example` is committable (F10).

5. **Do not pre-empt Foundation Task 15.** Task 15 will remove `ports:` from every Odoo service and
   split `picking-net` into `edge-net` / `core-net` / `automation-net` (F9). This plan keeps the
   existing single network and the existing `8069:8069` publication so Task 15 has exactly one
   change to make, not one change plus one revert. Likewise it does **not** touch `trusted_proxies`,
   the Caddy `/odoo` redirect, or `request_body max_size` (§0.2).

6. **Odoo 18 knowledge is deleted, not archived.** `odoo/addons18/README.md` records the one
   substantive porting difference (`res.groups.privilege` in v19 vs `res.groups.category_id` in
   v18). Task 3 moves that sentence into `odoo/addons/` before deleting the file.

7. **The atomic-commit constraint is wider than the commission stated.** *Two* services mount
   `./odoo/addons18`: `odoo` (`docker-compose.yml:61`) and `odoo-lager-2` (`:88`). Both move in the
   commit that deletes the directory.

---

## Task 0: The three facts that still need proving at cutover time

**Revision 2 shrinks this task to almost nothing.** §0.1 settled the version question, the database
inventory and the data census by live probe. What remains is not fact-finding but a *pre-flight
re-check*: the probes in §0.1 were taken on 2026-07-31 and the cutover may run later, after more
picks have been entered.

**Files:** none.

**Interfaces:**
- Consumes: a running Docker daemon; the `db` service.
- Produces: the three numbers that Task 1's restore rehearsal and Task 8's RB5 compare against.

- [ ] **Step 1: Re-take the census immediately before Task 1's dump, and write the numbers down.**

```bash
cd "/mnt/c/Users/endri/Desktop/Bachelor/Mobile Picking und Voice Assistant"
DOCKER="/mnt/c/Program Files/Docker/Docker/resources/bin/docker.exe"
"$DOCKER" compose exec -T db psql -U odoo -d masterfischer -tAc \
  "SELECT state, count(*) FROM stock_picking GROUP BY state ORDER BY 1;"
"$DOCKER" compose exec -T db psql -U odoo -d masterfischer -tAc \
  "SELECT count(*) FROM stock_move_line;"
"$DOCKER" compose exec -T db psql -U odoo -d masterfischer -tAc \
  "SELECT name, latest_version FROM ir_module_module WHERE name='base';"
```

Expected: `base` still `18.0.*`; picking counts at or above 46 `done` / 20 `assigned`. **These
three numbers are the reference values for Task 1 Step 3, Task 7 Step 6 and Task 8 RB5.** Record
them in the commit message of the Task 9 documentation commit, or in this file under a "cutover
run" heading — not in a terminal scrollback.

- [ ] **Step 2: Confirm nothing new appeared on the cluster.**

```bash
"$DOCKER" compose exec -T db psql -U odoo -d postgres -tAc \
  "SELECT datname FROM pg_database ORDER BY 1;"
```

Expected: the §0.1 list. A database named `masterfischer_o19` already present means someone started
Task 2 already — **stop and find out who**, rather than seeding on top of unknown content.

- [ ] **Step 3: Confirm the daemon and the Compose project.**

```bash
"$DOCKER" version --format '{{.Server.Version}}'
"$DOCKER" compose ps --format '{{.Service}}\t{{.State}}'
```

Expected: the daemon answers; `db` is `running`. If `odoo19-trial` is running, **stop it** — the
handoff records that a long-running `odoo19-trial` container kills addon test runs with
`SerializationFailure` (`--max-cron-threads=0` and `run --rm` are load-bearing for exactly this).

---

## Task 1: Pre-cutover backup **with a rehearsed restore**

**Gate:** Task 0 green.

A backup nobody has restored is a rumour. This task takes the backup and then proves it by restoring
it into a disposable copy — using the tool the repository already ships for exactly this
(`infrastructure/scripts/clone-postgres-volume.sh`, F10), which refuses to run while a container
mounts the source volume, verifies with SHA-256 manifests plus matching `PG_VERSION`, and stamps an
identity token into the copy so a rehearsal can never be mistaken for the original.

Note the register's §3.6 on the neighbouring work: Task 13 "closes only after one successful clone →
apply → verify → demote → rollback run against a disposable instance." This task uses the same
instrument on the same volume and its result is worth reporting to R4, but it is **not** that
acceptance run and must not be recorded as one.

**Files:**
- Create: `infrastructure/backups/` entries (untracked)
- Modify: `.gitignore` — add `infrastructure/backups/`

- [ ] **Step 1: Logical dump of both live databases, custom format**

`lager2` is now in scope: D3 migrates `odoo-lager-2` too, so its database needs the same protection.

```bash
cd "/mnt/c/Users/endri/Desktop/Bachelor/Mobile Picking und Voice Assistant"
DOCKER="/mnt/c/Program Files/Docker/Docker/resources/bin/docker.exe"
mkdir -p infrastructure/backups
STAMP=$(date +%Y%m%d-%H%M%S)
"$DOCKER" compose exec -T db pg_dump -U odoo -Fc masterfischer > "infrastructure/backups/masterfischer-${STAMP}.dump"
"$DOCKER" compose exec -T db pg_dump -U odoo -Fc lager2        > "infrastructure/backups/lager2-${STAMP}.dump"
"$DOCKER" compose exec -T db pg_dumpall -U odoo --globals-only > "infrastructure/backups/globals-${STAMP}.sql"
sha256sum infrastructure/backups/*-${STAMP}.dump | tee "infrastructure/backups/manifest-${STAMP}.sha256"
```

Expected: two non-empty `.dump` files; `pg_restore --list` on the `masterfischer` one names
`stock_picking` and `ir_module_module`.

- [ ] **Step 2: Back up the Odoo filestores**

The database dumps do **not** contain attachments. `odoo_data:/var/lib/odoo`
(`docker-compose.yml:59`) holds `filestore/masterfischer`; `odoo_lager2_data` (`:86`) holds
`filestore/lager2`.

```bash
"$DOCKER" run --rm -v odoo_data:/src:ro -v "$(wslpath -w "$PWD/infrastructure/backups")":/out alpine \
  tar czf "/out/odoo_filestore-${STAMP}.tgz" -C /src .
"$DOCKER" run --rm -v odoo_lager2_data:/src:ro -v "$(wslpath -w "$PWD/infrastructure/backups")":/out alpine \
  tar czf "/out/lager2_filestore-${STAMP}.tgz" -C /src .
```

Expected: the archives list `./filestore/masterfischer/` and `./filestore/lager2/`.
(`wslpath -w` is required: Docker Desktop's WSL integration is off, so the CLI resolves host paths.)

- [ ] **Step 3: REHEARSE the restore — this is the step that makes Step 1 real**

Stop the stack first (`clone-postgres-volume.sh` refuses to clone a mounted source), clone the
volume, bring the clone up under a **separate Compose project name**, and restore into it.

```bash
"$DOCKER" compose down                        # NOT down -v (Global Constraint 3)
bash infrastructure/scripts/clone-postgres-volume.sh create pg_data pg_data_rehearsal infrastructure/backups/manifests
bash infrastructure/scripts/clone-postgres-volume.sh verify pg_data pg_data_rehearsal infrastructure/backups/manifests
bash infrastructure/scripts/clone-postgres-volume.sh compose-up infrastructure/backups/manifests pg_data_rehearsal cutover-rehearsal
```

Then, **against the rehearsal project only** — note the `-p cutover-rehearsal` on every line; a
missing `-p` here is the single most dangerous typo in this plan:

```bash
"$DOCKER" compose -p cutover-rehearsal exec -T db psql -U odoo -d postgres \
  -c "CREATE DATABASE masterfischer_restore_test;"
"$DOCKER" compose -p cutover-rehearsal exec -T db pg_restore -U odoo -d masterfischer_restore_test \
  < "infrastructure/backups/masterfischer-${STAMP}.dump"
"$DOCKER" compose -p cutover-rehearsal exec -T db psql -U odoo -d masterfischer_restore_test \
  -tAc "SELECT state, count(*) FROM stock_picking GROUP BY state ORDER BY 1;"
```

Expected: `pg_restore` exits 0, and the counts **equal Task 0 Step 1's numbers**. Anything else
means the backup is not restorable and the cutover must not proceed.

- [ ] **Step 4: Time it and tear the rehearsal down**

Record the wall-clock time from "start restore" to "counts match". That number, plus the image
rebuild time measured in Task 7, is the rollback budget quoted in Task 8.

```bash
"$DOCKER" compose -p cutover-rehearsal down
bash infrastructure/scripts/clone-postgres-volume.sh delete pg_data_rehearsal infrastructure/backups/manifests
```

Expected: `docker volume ls` no longer lists `pg_data_rehearsal`; `pg_data` still exists.

- [ ] **Step 5: Keep the backups out of git**

Add `infrastructure/backups/` to `.gitignore` and confirm `git status --short` shows nothing under
it. The dumps contain credential hashes; they must never be committed.

---

## Task 2: Create and seed the two fresh v19 databases *before* the cutover commit

**Gate:** Task 1 green.

Ordering matters. The new databases are created and seeded while the v18 stack is still the default,
using the existing `odoo19-trial` profile — the one invocation pattern the handoff records as safe
(`--profile odoo19-trial run --rm --no-deps -T`, never `exec odoo`, always `--max-cron-threads=0`).
If seeding fails, nothing has been cut over and there is nothing to roll back.

**Decided names (D2, D3):**

| Purpose | v18 database (kept) | v19 database (new) |
|---|---|---|
| Live warehouse | `masterfischer` | **`masterfischer_o19`** |
| Second warehouse (`odoo-lager-2`, profile `second-odoo`) | `lager2` | **`lager2_o19`** |

**Why `masterfischer_o19` and not something else** (07-30 R3, verified here): `backend/app/config.py`
declares `ODOO19_TRIAL_PROFILE_NAMES = {"o19","odoo19","o19-trial","odoo19-trial"}` and
`ODOO19_TRIAL_DB = "masterfischer_o19_trial"` (`config.py:97-98`). Any instance profile keyed with
one of those names whose database is not exactly `masterfischer_o19_trial` is **rejected at backend
startup**, with an error message that points at the instance registry rather than at the cutover.
And in the opposite direction, `DEMO_TRACEABILITY_ALLOWED_DBS` defaults to `masterfischer_o19_trial`
(`docker-compose.yml:158`), so reusing *that* name for production would silently enable demo
traceability. `masterfischer_o19` under a profile key that is not in the trial set avoids both.
Task 2 Step 5 checks it rather than assuming it.

**Why `lager2_o19` is seeded by the same script:** `docs/SETUP.md:78` is the only documented
provisioning path for the second warehouse — *"Fuer eine frische `lager2`-DB: Custom-Module
installieren und dann `seed-odoo.py --url http://localhost:8070 --db lager2 --user admin --api-key
<key>` ausfuehren."* There is no Makefile target and no second seeder; `seed-odoo.py` is
database-agnostic and takes `--url`/`--db`. `Makefile:51`'s `seed` target hardcodes port 8069, so
the second warehouse is seeded by invoking the script directly against port 8070, exactly as
SETUP.md says. Note also from §0.1 that `lager2` has **no `picking_assistant_*` module installed
today** — so `lager2_o19` will be strictly more capable than the database it replaces, not less.

**Files:**
- Modify: `odoo/odoo19-trial.conf` — `dbfilter` must admit the new names during Task 2 only

**Interfaces:**
- Consumes: `odoo19-trial` service (`docker-compose.yml:93-117`), `./odoo/addons` mount (line 115),
  `infrastructure/scripts/seed-odoo.py`.
- Produces: two populated v19 databases with `picking_assistant_core`,
  `picking_assistant_integration` and `quality_alert_custom` installed.

- [ ] **Step 1: Widen the trial dbfilter, temporarily**

`odoo/odoo19-trial.conf:11` is `dbfilter = ^masterfischer_o19_trial$`. Change to
`dbfilter = ^(masterfischer_o19(_trial)?|lager2_o19)$` for the duration of Task 2. Leave
`list_db = False` (line 12) alone. Task 3 removes this service entirely, so the widening does not
survive the cutover commit.

- [ ] **Step 2: Create and initialise `masterfischer_o19`**

The module list is taken from what `masterfischer` actually has installed (§0.1), not from a guess.
`stock_sms` is pulled in as a dependency of `stock`; it is not listed explicitly.

```bash
"$DOCKER" compose --profile odoo19-trial run --rm --no-deps -T odoo19-trial \
  odoo --no-http --stop-after-init --workers=0 --max-cron-threads=0 \
  -d masterfischer_o19 --without-demo=all \
  -i base,mail,stock,stock_picking_batch,picking_assistant_core,picking_assistant_integration,quality_alert_custom
```

Every flag is load-bearing (handoff §2). Expected: exit 0; the container is gone (`--rm`).
Then confirm from `db`:

```bash
"$DOCKER" compose exec -T db psql -U odoo -d masterfischer_o19 -tAc \
  "SELECT name, latest_version, state FROM ir_module_module WHERE state='installed' AND (name LIKE 'picking%' OR name='quality_alert_custom') ORDER BY name;"
```

Expected: `picking_assistant_integration` at `19.0.1.0.0`, state `installed` (F3) — matching what
`masterfischer_o19_foundation_test` already demonstrates (§0.1).

- [ ] **Step 3: Issue a fresh `ODOO_API_KEY` against `masterfischer_o19`**

**API keys are per-database** (07-30 R4). The live `.env` carries a key issued against
`masterfischer`; it is meaningless in the new database. A cutover that changes `ODOO_DB` but not
`ODOO_API_KEY` produces a backend that starts cleanly and then 401s on every JSON-RPC call — a
failure that looks like a network problem. Bring the trial service up, log in as `admin`, create a
new API key, and **keep the old key** in a scratch note: Task 8 RB3 needs it to restore.

- [ ] **Step 4: Seed it**

`seed-odoo.py` speaks XML-RPC, so the service must be listening. Start it, seed, **stop it again** —
never leave `odoo19-trial` running (handoff §2).

```bash
"$DOCKER" compose --profile odoo19-trial up -d odoo19-trial
python infrastructure/scripts/seed-odoo.py \
  --url http://localhost:8100 --db masterfischer_o19 --user admin --api-key "${NEW_ODOO_API_KEY}"
"$DOCKER" compose --profile odoo19-trial stop odoo19-trial
"$DOCKER" compose --profile odoo19-trial rm -f odoo19-trial
```

Port `8100` is `docker-compose.yml:111` (`127.0.0.1:${ODOO19_TRIAL_PORT:-8100}:8069`), loopback-only.

Expected: the seeder reports created locations, products and pickings; a repeat run is idempotent
(`find_or_create`). Confirm:

```bash
"$DOCKER" compose exec -T db psql -U odoo -d masterfischer_o19 -tAc \
  "SELECT state, count(*) FROM stock_picking GROUP BY state ORDER BY 1;"
```

Expected: a non-zero count in `assigned`/`confirmed`. For calibration, `masterfischer_o19_trial` —
seeded the same way — carries 21 `assigned` + 45 `done` (§0.1). **The count will not match
`masterfischer`'s 66, and it is not supposed to: this is a reseed and the completed picks do not
come across.** That is D1, decided.

- [ ] **Step 5: Prove the name does not trip the instance registry**

```bash
grep -n "ODOO19_TRIAL_PROFILE_NAMES\|ODOO19_TRIAL_DB" backend/app/config.py
cd backend && PYTHONPATH=.deps python -m pytest -p pytest_asyncio tests/test_instance_registry.py -v
```

Expected: green, and no profile key in the planned `ODOO_INSTANCES_JSON` is one of `o19`, `odoo19`,
`o19-trial`, `odoo19-trial` (07-30 R3). In a worktree, point `PYTHONPATH` at the main tree's
`backend/.deps` — pytest is vendored there and does not exist in worktrees (handoff §2).

- [ ] **Step 6: Create and seed `lager2_o19` (D3)**

Same shape, against the second warehouse's service. This can also run under `odoo19-trial` for the
`-i` step, since the database name is what matters and both services mount the same v19 addon tree
after Task 3 — but before Task 3, `odoo-lager-2` is still v18, so use the trial service:

```bash
"$DOCKER" compose --profile odoo19-trial run --rm --no-deps -T odoo19-trial \
  odoo --no-http --stop-after-init --workers=0 --max-cron-threads=0 \
  -d lager2_o19 --without-demo=all \
  -i base,mail,stock,stock_picking_batch,picking_assistant_core,picking_assistant_integration,quality_alert_custom
```

Then issue an API key on `lager2_o19` and seed it. Because the *second warehouse* service is not up
as v19 until Task 3, seeding `lager2_o19` over XML-RPC needs a listener that can serve it — bring
`odoo19-trial` up with the Step 1 widened `dbfilter` and seed through port 8100 with
`--db lager2_o19`. Stop it afterwards.

**Consequence to state plainly (07-30 R5): the PWA *Lagerumschalter* is broken between Task 3 and
the moment `.env`'s `ODOO_INSTANCES_JSON` points at `lager2_o19` (Task 4 Step 3).** The instance
switcher is a demonstrated thesis feature with its own plan
(`docs/superpowers/plans/2026-06-27-odoo-instance-switch.md`). Do not discover this during a
demonstration.

- [ ] **Step 7: Run the v19 addon test suite against a throwaway, not against either new database**

```bash
"$DOCKER" compose --profile odoo19-trial run --rm --no-deps -T odoo19-trial \
  odoo --no-http --test-enable --stop-after-init --workers=0 --max-cron-threads=0 \
  -d masterfischer_o19_foundation_test -u picking_assistant_integration
```

This is the handoff's verbatim command and it reuses the database that already exists for it
(§0.1). Expected: the eight test modules under
`odoo/addons/picking_assistant_integration/tests/` (F3) pass, with **no other Odoo container
running** — a concurrent cron master causes `SerializationFailure` before a single test executes.

---

## Task 3: THE ATOMIC COMMIT — delete `addons18/` and rework Compose

**Gate:** Tasks 0-2 green. This is the only irreversible-looking step, and it is reversible by
`git revert` (Task 8) precisely because Task 2 left `masterfischer` and `lager2` untouched.

**Files:**
- Delete: `odoo/addons18/` — all 24 files (23 code/asset files + `README.md`, F3)
- Modify: `docker-compose.yml`
- Modify: `odoo/Dockerfile`
- Create: `odoo/odoo19.conf`, `odoo/odoo19-lager2.conf` (see "why new files" below)
- Delete: `odoo/odoo.conf`, `odoo/odoo-lager2.conf`, `odoo/odoo19-trial.conf`
- Create: `odoo/addons/README.md` (carries the porting note forward, Global Constraint 6)
- Modify: `.env.example`

**Interfaces:**
- Consumes: the v19 tree at `odoo/addons/` (F3), the two databases from Task 2.
- Produces: a stack whose default `odoo` service is v19; the Odoo-19 service/image/mount facts that
  Foundation Task 15 is required to preserve (F9).

### Why new config files rather than edited ones (07-30 R2)

`odoo/odoo.conf` has `list_db = True` and the `odoo` service publishes `"8069:8069"` on **all**
interfaces — i.e. the Odoo database manager is on the LAN. The trial config already made the safer
choice on both counts (`list_db = False`). The obvious implementation of "point `odoo` at v19" is to
keep `odoo.conf` and change only the mount, which promotes the v19 *addon* while retaining the v18
*posture*. Writing new files instead makes the posture an explicit, reviewable diff, and it means a
`git revert` of this commit restores the old files verbatim with no merge risk.

The port stays public (Global Constraint 5 — Task 15 removes it): Caddy's `/odoo` redirect sends
admins there and the thesis demo needs it. `list_db = False` is what makes that acceptable.

**`odoo/odoo19.conf`** — derived from `odoo19-trial.conf`, with the three isolation keys:

```
dbfilter = ^masterfischer_o19$
db_name = masterfischer_o19
list_db = False
```

`db_name` is the load-bearing one (Global Constraint 2): it is the only key Odoo's cron master
honours, and without it the v19 cron master enumerates and attaches to `masterfischer`.
**`odoo/odoo19-lager2.conf`** is the same file with `masterfischer_o19` → `lager2_o19`.

### Exactly which Compose keys change

| # | Key | From | To | Why |
|---|---|---|---|---|
| 1 | `services.odoo.build.args.ODOO_BASE_IMAGE` (line 46) | `odoo:18.0` | `odoo:19.0` | the version decision |
| 2 | `services.odoo.volumes[2]` (line 61) | `./odoo/addons18:/mnt/extra-addons:ro` | `./odoo/addons:/mnt/extra-addons:ro` | **the constraint** — without this in the same commit the container starts with an empty addons path |
| 3 | `services.odoo.volumes[1]` (line 60) | `./odoo/odoo.conf:/etc/odoo/odoo.conf:ro` | `./odoo/odoo19.conf:/etc/odoo/odoo.conf:ro` | the new posture (see above) |
| 4 | `services.odoo` comment (line 40) | `── Odoo 18 Community (Live/Default) ──` | `── Odoo 19 Community (Live/Default) ──` | the comment is the first thing a reader trusts |
| 5 | `services.odoo-lager-2.build.args.ODOO_BASE_IMAGE` (line 71) | `odoo:18.0` | `odoo:19.0` | **D3** — the second warehouse migrates in the same commit |
| 6 | `services.odoo-lager-2.volumes[2]` (line 88) | `./odoo/addons18:/mnt/extra-addons:ro` | `./odoo/addons:/mnt/extra-addons:ro` | **the constraint, second occurrence — the commission missed this one** |
| 7 | `services.odoo-lager-2.volumes[1]` (line 87) | `./odoo/odoo-lager2.conf:…` | `./odoo/odoo19-lager2.conf:…` | same posture, second service |
| 8 | `services.odoo19-trial` (lines 92-117) | whole service, incl. `profiles: [odoo19-trial]` | **removed** | the profile gating disappears; v19 is no longer a trial |
| 9 | `volumes.odoo19_trial_data` (lines 287-288) | declared with a global `name:` | **kept, with a comment** | see the note below |
| 10 | `services.backend.environment.ODOO_DB` (line 132) | `${ODOO_DB:-picking}` | `${ODOO_DB:?ODOO_DB muss gesetzt sein und eine v19-Datenbank benennen}` | `picking` **exists and is Odoo 18** (§0.1, §0.4.2). A v19 backend silently defaulting at a v18 database is worse than defaulting at nothing |

**Keys that deliberately do NOT change**, so Foundation Task 15 has one clean edit (Global
Constraint 5): `services.odoo.ports` stays `8069:8069`; `networks` stays the single `picking-net`;
`services.backend.environment.ODOO_URL` stays `http://odoo:8069` (it names the *service*, and the
service keeps its name — that is why the backend, Caddy and n8n need no change at all).

`services.odoo.volumes[0]` (`odoo_data:/var/lib/odoo`, line 59) also does not change. The filestore
is per-database (`/var/lib/odoo/filestore/<db>`), so `masterfischer_o19` gets a fresh subdirectory
and `filestore/masterfischer` stays intact for rollback. Same for `odoo_lager2_data`.

**On key 9 (07-30 R9):** `odoo19_trial_data` is declared with an explicit global
`name: odoo19_trial_data`, so it is **not project-scoped** — any other Compose project on the host
addressing that name gets the same volume. Do not reuse it for production. Keeping the declaration
(with a comment) during the rollback window preserves the paper trail; delete it in the follow-up
commit after the window closes (Task 8, "Closing the window").

### Other file changes in the same commit

- `odoo/Dockerfile` line 1: `ARG ODOO_BASE_IMAGE=odoo:18.0` → `ARG ODOO_BASE_IMAGE=odoo:19.0`.
  Compose passes the arg explicitly, so this only fixes the default for anyone building the
  directory by hand — but leaving it at 18.0 after `addons18/` is gone is a trap.
- `odoo/addons/README.md` (new): carry over the porting note from `odoo/addons18/README.md` —
  "Odoo 19 security XML uses `res.groups.privilege`, Odoo 18 used `res.groups.category_id`" — plus a
  line recording that `addons18/` was deleted in this commit, recoverable from git history, and that
  the deletion executes frozen decision §3.4's "or it is deleted" branch.
- `.env.example` line 10: `ODOO_DB=picking` → `ODOO_DB=masterfischer_o19`; line 19's commented
  `ODOO_INSTANCES_JSON` example `"db":"lager2"` → `"db":"lager2_o19"`.

**Do NOT normalise line endings in this commit (07-30 R10).** `quality_alert_custom/models/quality_alert.py`
survives as the CRLF copy and `git diff --check` will warn on future edits, exactly as it already
does for `backend/app/main.py`. A whole-file line-ending diff inside the one commit that most needs
to be readable is a bad trade.

- [ ] **Step 1: Make every change above in one working tree, commit nothing yet**

- [ ] **Step 2: Prove the deletion and the repoint are in the same change set**

```bash
git add -A
git diff --cached --stat -- "Mobile Picking und Voice Assistant/odoo/addons18" \
  "Mobile Picking und Voice Assistant/docker-compose.yml"
git diff --cached -- "Mobile Picking und Voice Assistant/docker-compose.yml" | grep -E '^\+.*addons'
grep -rn "addons18\|odoo:18.0" "Mobile Picking und Voice Assistant/" --exclude-dir=docs \
  --exclude-dir=graphify-out --exclude-dir=.code-review-graph
```

Expected: the stat shows 24 deletions under `addons18/`; the compose diff shows **two** added
`./odoo/addons:/mnt/extra-addons:ro` lines (`odoo` and `odoo-lager-2`); the grep returns **nothing**.
(Under `docs/` the strings survive in historical plans; that is correct. The two analysis caches are
excluded here and handled in Task 6 Step 4.)

- [ ] **Step 3: Prove the isolation keys are present in both new configs**

```bash
grep -n "db_name\|dbfilter\|list_db" "Mobile Picking und Voice Assistant/odoo/odoo19.conf" \
  "Mobile Picking und Voice Assistant/odoo/odoo19-lager2.conf"
```

Expected: `db_name`, `dbfilter` and `list_db = False` in **both**. A missing `db_name` is Global
Constraint 2 violated and is a hard stop.

- [ ] **Step 4: Validate the file before committing**

```bash
cd "Mobile Picking und Voice Assistant" && "$DOCKER" compose config >/dev/null
```

Expected: exit 0 and no `odoo19-trial` in the rendered output. `compose config` will fail on the new
`${ODOO_DB:?…}` unless `.env` already carries it — that failure is the feature working; set `.env`
first (Task 4 Step 1) or export it inline for the check.

- [ ] **Step 5: Commit**

```
feat(odoo)!: make Odoo 19 the productive runtime and delete the v18 addon tree

Executes frozen decision §3.4's "or it is deleted" branch. Both services that
mounted odoo/addons18 (odoo and odoo-lager-2) are repointed at odoo/addons in
this commit; the odoo19-trial profile is removed. New odoo19.conf and
odoo19-lager2.conf set db_name (not just dbfilter), which is the only key the
Odoo cron master honours.

BREAKING CHANGE: ODOO_DB must be set explicitly and must name a v19 database.
The live v18 databases masterfischer and lager2 are untouched, are never
dropped, and remain the rollback path — see
docs/superpowers/plans/2026-07-31-odoo19-cutover.md Task 8.
```

---

## Task 4: Operator-side switch (`.env`) — not carried by any commit

**Gate:** Task 3 committed but **not yet deployed**.

`.env` lives only in the operator's checkout at `Desktop/Bachelor/` and is git-ignored (F10, Global
Constraint 4). These are hand edits. **Keep a copy of the pre-cutover `.env` — Task 8 RB3 needs it.**

- [ ] **Step 1: `ODOO_DB=masterfischer_o19`.** Without it, Task 3 key 10 makes the stack refuse to
  start — deliberately.
- [ ] **Step 2: `ODOO_API_KEY=` the key issued in Task 2 Step 3.** Keys are per-database (07-30 R4).
  Getting this wrong gives a backend that starts clean and 401s on every call.
- [ ] **Step 3: `ODOO_INSTANCES_JSON`** — the `lager-2` entry's `"db"` becomes `"lager2_o19"` with
  its own new API key. If the value carries an `o19-trial` entry pointing at
  `http://odoo19-trial:8069`, that service no longer exists (Task 3 key 8): remove the entry.
  `backend/tests/test_instance_registry.py` shows the registry rejects a mismatched db name, so a
  stale entry fails loudly rather than silently — and no profile key may be one of
  `o19`/`odoo19`/`o19-trial`/`odoo19-trial` (Task 2 Step 5).
- [ ] **Step 4: `RUNTIME_PROFILE=production`** — required from the moment Task 5 lands (Task 5
  Step 5). Set it now so the two tasks do not have to be deployed in lockstep.
- [ ] **Step 5: Leave `DEMO_TRACEABILITY_ALLOWED_DBS` alone.** Its default
  `masterfischer_o19_trial` (`docker-compose.yml:158`) does not match the new production database,
  which is exactly what is wanted: demo traceability stays off in production.
- [ ] **Step 6: Verify** `"$DOCKER" compose config | grep -E "ODOO_DB|RUNTIME_PROFILE"` renders the
  new values.

---

## Task 5: Image pinning, the `secrets:` block, and `RUNTIME_PROFILE`

**Gate:** Task 3 committed. **Separate commit, deliberately.** These changes are independent of the
`addons18` constraint, and folding them into the atomic commit would make the cutover revert
(Task 8) also revert the security hardening. One rollback, one concern.

**Files:** `docker-compose.yml`, `.env.example`, `.gitignore`,
`infrastructure/secrets/README.md` (new).

**Interfaces:**
- Consumes: the two permission contracts quoted below; `backend/app/config.py:69,175`.
- Produces: reproducible image resolution; file-based secrets at `/run/secrets/pwr_*`; a fail-closed
  runtime profile. Foundation Task 15 consumes all three.

> **Merge-collision warning (§0.4.4).** The R1 lane already edited `docker-compose.yml` — the
> register logged it as a "bounded exception to the compose freeze": `CORS_ORIGINS` renamed to
> `PWA_ORIGINS`, and `RUNTIME_PROFILE` introduced at line 155 as `${RUNTIME_PROFILE:-development}`.
> On *this* branch line 155 is still `CORS_ORIGINS`. Expect a conflict in exactly that region at
> integration, and resolve it as: `PWA_ORIGINS` (R1's rename) **plus** `${RUNTIME_PROFILE:?…}`
> (this task's hardening). Neither side is wrong; they are the same three lines.

### 5a — Pinning (F7: **no service in the file is digest-pinned today**)

- [ ] **Step 1: Pin every floating tag.**

| Service | Line | Today | Action |
|---|---|---|---|
| `caddy` | 4 | `caddy:2-alpine` | pin to a concrete **>= 2.10** tag, then append `@sha256:…` — §3.5 names the pin as an obligation and §3.8 gives the version floor |
| `pwa` | 275 | `caddy:2-alpine` | **same pin as `caddy`** — two Caddies drifting apart is worse than one unpinned |
| `db` | 21 | `postgres:16-alpine` | pin the patch plus digest. **Never bump the major** — that would silently require a `pg_upgrade` of `pg_data`, which holds every database in §0.1 |
| `whisper` | 168 | `…:latest` | pin to the digest currently running; `:latest` has no recoverable version |
| `ollama` | 189 | `…:latest` | same |
| `n8n` | 200 | `…:2.13.3` | append `@sha256:…`; the tag is already right |
| `odoo` / `odoo-lager-2` | 46 / 71 (post-Task 3) | `odoo:19.0` | `19.0` is a moving tag. Pin the digest in the build arg |

Resolve digests from what is actually running, not from the registry's current `latest`:

```bash
"$DOCKER" image inspect caddy:2-alpine --format '{{index .RepoDigests 0}}'
```

- [ ] **Step 2: Confirm the pinned Caddy really carries the directive Task 15 will need.**

```bash
"$DOCKER" run --rm caddy:<pinned-tag> caddy version
```

**This task does not add `request_body max_size`, does not add `trusted_proxies`, and does not touch
the `/odoo` redirect.** §3.8 assigns the body limit to Task 15 and requires a *second*, ASGI-level
layer that this plan cannot supply; §3.5 assigns `trusted_proxies` to Task 15 as well (§0.2). The
pin is the half that has to exist first, and it is the only half this task does.

### 5b — The `secrets:` block (F8: none exists today)

Two independent permission contracts have to be satisfied by one block. Quoting both, because they
differ:

- **Backend (Foundation plan, F8):** `read_secret(direct, file_path)` rejects a file whose mode has
  any bit set in `0o077` — i.e. it must be `0400` or `0600`. It also **raises if both the direct
  value and the file path are set.**
- **n8n / Node (register, R3 deployment obligation), verbatim:**

  > **Compose `secrets:` must set `uid`, `gid` and `mode`.** R3 Task 3 moved the credential-file
  > permission check into the container, immediately before the read, using `lstat`. It requires
  > the mounted secret to be a regular file, mode `0400`, owned by the `node` runtime user.
  > `docker-compose.yml` currently declares **no `secrets:` block at all**, and Docker's default for
  > mounted secrets is root-owned `0444` — which the new check rejects on both counts. Whoever
  > wires the compose `secrets:` block (Task 15, or whoever deploys first) must set `uid`, `gid` and
  > `mode` explicitly, **or credential provisioning will refuse to start.** This is a deliberate
  > fail-closed choice, not an oversight.

  "Whoever deploys first" is this plan. `mode: 0400` is therefore **mandatory, not stylistic**.

- [ ] **Step 3: Add the top-level block.**

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

  The five `/run/secrets/pwr_*` target names are fixed by the Foundation plan (F8). **Read the uids,
  do not guess them:** `"$DOCKER" compose run --rm --no-deps -T backend id -u` and the same for
  `n8n`. The n8n official image runs as `node`; the register requires that exact owner.
  `./infrastructure/secrets/` goes into `.gitignore`; only a `README.md` naming the six files is
  committed.

- [ ] **Step 4: Point the env vars at the files and remove the direct ones.**
  Replace the values at `docker-compose.yml:148-151` and `222-224` with their `*_FILE` counterparts.
  `read_secret` **raises if both are set**, so leaving the old variables alongside the new ones is a
  startup failure, not a redundancy — remove them in the same edit.

### 5c — `RUNTIME_PROFILE` (F8: the gate at `backend/app/config.py:175` is open today)

The register's words on this are quoted in §0.4.5: the one-character hardening
`${RUNTIME_PROFILE:?…}` "belongs with the deployment work". This is it.

- [ ] **Step 5: Make it fail closed.** Add to `services.backend.environment`:

```yaml
      RUNTIME_PROFILE: ${RUNTIME_PROFILE:?RUNTIME_PROFILE muss gesetzt sein (production|development)}
```

  and to `.env.example`: `RUNTIME_PROFILE=production`, alongside `MOBILE_HEADER_GRACE_MODE=false`
  (`validate_runtime_security()` rejects grace mode in production). Note that on the R1 lane
  `runtime_profile` is already an **enum**, not a bare `str` (register, finding #1 closed by
  `1943b1c..9208866`) — so after integration a typo is rejected by the type, and this Compose
  hardening closes the remaining hole, which is the variable being *absent*.

- [ ] **Step 6: Prove the gate is now closed.**

```bash
RUNTIME_PROFILE= "$DOCKER" compose config   # must fail with the German message
```

  Then with `RUNTIME_PROFILE=production` and a deliberately weak secret, `compose up backend` must
  exit non-zero with the message from `validate_runtime_security()`. **A backend that starts clean
  here with no secret configured means the gate is still open** — that is the whole point of the
  step. (Register pattern: "Make the guard fail before believing it.")

- [ ] **Step 7: Commit separately**

```
chore(compose): pin every image, mount secrets as files, fail closed on RUNTIME_PROFILE

Discharges the R3 deployment obligation (uid/gid/mode 0400 on every secret) and
the RUNTIME_PROFILE residual the register assigned to "the deployment work".
The Caddy pin is §3.5's half; request_body max_size, the ASGI streaming limit
and trusted_proxies remain Foundation Task 15's per §3.8 and §3.5.
```

---

## Task 6: Defaults, documentation and the stale analysis caches

**Gate:** Task 3 committed. Small, mechanical, entirely reviewable — and deliberately *after* the
databases exist, so every default it changes points at something real. (Taken from the 07-30 plan's
Task 5 and Task 6.)

**Files:** `infrastructure/scripts/seed-odoo.py`, `Makefile`, `docs/SETUP.md`,
`backend/app/services/cluster_service.py` (comment only), `e2e/cluster.live.js` (comment only),
`graphify-out/`, `.code-review-graph/`.

- [ ] **Step 1: `seed-odoo.py`** — the `--db` default `masterfischer` → `masterfischer_o19`. Leave
  the `--url` default at `http://localhost:8069`; it is correct, because the `odoo` service kept
  port 8069. Update the two usage examples in the module docstring, which already say "Odoo 19" but
  name the old database.
- [ ] **Step 2: `Makefile:51`** — `--db $${ODOO_DB:-picking}` still defaults at the v18 `picking`
  database (§0.1). Change the fallback to `masterfischer_o19`, or drop the fallback entirely so the
  target fails loudly. Same for `shell-odoo` and `shell-db` (`Makefile:118-122`).
- [ ] **Step 3: `docs/SETUP.md`** — six regions: the database-manager URL at line 40 (now
  unreachable, `list_db = False`; replace with the CLI creation command from Task 2 Step 2), the
  API-key step at line 46 (add "keys are per-database; re-issue after cutover"), the `second-odoo`
  section at lines 56-78 (`lager2` → `lager2_o19`, port 8070 unchanged, and a note that Task 2
  Step 6 must run before the switcher works), lines 129-130 (`--db masterfischer` →
  `masterfischer_o19`), line 139, and lines 142-145 — the "do not blindly start Odoo-18 databases
  with the Odoo-19 container" warning, which this cutover is the sanctioned way of doing: rewrite it
  to point here, and to Global Constraint 2's `db_name`.
- [ ] **Step 4: The two analysis caches.** `graphify-out/` and `.code-review-graph/` hold roughly 465
  references to `addons18` and to files that no longer exist. They are generated artefacts. A stale
  code graph is worse than none: the next agent that asks "where is `_lock_or_create`" gets two
  answers, one of them a deleted file. Regenerate with whatever produced them; if the generator is
  unavailable, delete the caches rather than leave them. Check `.gitignore` first — if they are
  ignored, this is local hygiene with no commit.
- [ ] **Step 5: Two comments.** `backend/app/services/cluster_service.py:12` cites
  `2026-06-23-odoo18-batch-api-facts.md`. **Do not delete the citation** — that document records
  verified API facts and remains historically true; add the v19 note alongside it.
  `e2e/cluster.live.js:5` names `masterfischer`; change to `masterfischer_o19`.
- [ ] **Step 6: Verify and commit**

```bash
grep -rn "masterfischer\b" --include="*.py" --include="*.js" --include="*.md" \
  infrastructure/ backend/app/ e2e/ docs/SETUP.md Makefile | grep -v "_o19"
```

Expected: the only bare `masterfischer` hits are under `docs/superpowers/` history and in this
plan's rollback text, which are meant to say it.

---

## Task 7: Deploy and verify

**Gate:** Tasks 3, 5, 6 committed; Task 4 applied on the operator machine.

**Files:** none (runtime only).

- [ ] **Step 1: Bring the new default up, timed**

```bash
time "$DOCKER" compose up -d --build odoo
"$DOCKER" compose logs --tail=80 odoo
```

Expected: the log reports Odoo **19.0**; `Modules loaded`; **no** "database not initialized" and no
`dbfilter` rejection. Record the elapsed time — it is half the rollback budget in Task 8.

- [ ] **Step 2: Prove the addon path resolved**

```bash
"$DOCKER" compose exec -T odoo ls /mnt/extra-addons
```

Expected: `picking_assistant_core  picking_assistant_integration  quality_alert_custom` — the direct
test of the owner's atomic-commit constraint.

- [ ] **Step 3: Prove the database manager is closed**

```bash
curl -sS http://localhost:8069/web/database/list -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","method":"call","params":{}}'
```

Expected: `masterfischer` does **not** appear (`list_db = False` plus the narrowed `dbfilter`).

- [ ] **Step 4: Prove the CRON MASTER is confined — this is the step `dbfilter` cannot pass**

Global Constraint 2's real test. `dbfilter` would pass Step 3 and still fail this.

```bash
"$DOCKER" compose exec -T odoo grep -E "db_name|dbfilter|list_db" /etc/odoo/odoo.conf
"$DOCKER" compose logs odoo | grep -iE "masterfischer($|[^_])" | head
```

Expected: `db_name = masterfischer_o19` present in the running container's config, and **no log line
naming the bare `masterfischer` database.** Any registry-load or cron line mentioning
`masterfischer` without the `_o19` suffix is rollback trigger R1.

- [ ] **Step 5: Watch the four new crons for fifteen minutes (07-30 R6)**

The v19 tree has **six** `ir.cron` records against the v18 tree's **two** (verified:
`odoo/addons/picking_assistant_integration/data/ir_cron.xml` vs
`odoo/addons18/.../ir_cron.xml`). The four new ones are `recover_stalled_jobs` (**1 minute**),
`cleanup_ephemeral` (10 minutes), `cleanup_audit` (daily) and `cleanup_job_resources` (daily).
Until now they have only ever executed inside `--test-enable` runs; on the live service they become
continuous background load against real data. A one-minute cron that raises does so ~1400 times a
day.

```bash
"$DOCKER" compose logs -f --tail=0 odoo | grep -iE "cron|traceback|ERROR"
```

Expected: fifteen minutes with no traceback. **Note the standing risk:** debt-register finding
**#11** — *"Retention deletes delivered/dead outbox rows regardless of job state; the watchdog then
tolerates a missing outbox"* — is `Important`, owner R2, `Verified: no`, and is **open**. It is the
retention cron that this step puts on a daily schedule against production data. That is the concrete
argument for the sequencing decision in "Decisions owed", D-SEQ.

- [ ] **Step 6: Prove `masterfischer` and `lager2` still exist and are untouched — Global Constraint 1**

```bash
"$DOCKER" compose exec -T db psql -U odoo -d postgres -tAc \
  "SELECT datname FROM pg_database WHERE datname IN ('masterfischer','lager2') ORDER BY 1;"
"$DOCKER" compose exec -T db psql -U odoo -d masterfischer -tAc \
  "SELECT latest_version FROM ir_module_module WHERE name='base';"
"$DOCKER" compose exec -T db psql -U odoo -d masterfischer -tAc \
  "SELECT state, count(*) FROM stock_picking GROUP BY state ORDER BY 1;"
"$DOCKER" compose exec -T db psql -U odoo -d lager2 -tAc \
  "SELECT latest_version FROM ir_module_module WHERE name='base';"
```

Expected: **both databases present**; `base` still `18.0.*` in both; the picking counts **identical
to Task 0 Step 1's**. A v19 value, a changed count, or a missing database is a data-loss event and
an immediate rollback trigger. This is the verification the owner asked for by name: the plan proves
`masterfischer` still exists after cutover rather than assuming it.

- [ ] **Step 7: Application-level verification**

```bash
make verify-code        # backend pytest (Makefile:88-89)
make verify-stack       # infrastructure/scripts/test-api.py (Makefile:103-104)
make verify-workflows   # n8n contract check (Makefile:80-81)
make test-ui            # Playwright confirm-flow, pickings, quality-alert (Makefile:56-57)
```

Expected: all four green. `make verify-stack` is the one that actually exercises the backend against
the new v19 Odoo.

> **`make verify-workflows` exiting 0 proves nothing about v2 today, and must not be quoted as if it
> did.** All eight workflows in `n8n/workflow-registry.json` are `"generation": "v1"` (verified by
> direct grep at this HEAD); `verify-workflows.py` skips everything that is not exactly `v2`
> (register finding #12's mechanism, closed as a *field-validation* fix, not as a coverage fix). The
> v2 verifier is therefore **dormant**. A green `verify-workflows` here means "the v1 contract still
> holds", nothing more. Record it that way in the merge review.

- [ ] **Step 8: Manual smoke** — log into the PWA over `https://${LAN_HOST}`, open a picking, confirm
  a line, confirm a quality alert with a photo reaches n8n, and switch to Lager 2 and back. This is
  the only step that proves end-to-end that the picker's job still works, and the instance switch is
  the only step that exercises D3's second half.

---

## Task 8: The rollback window, and closing it

**Files:** none until "Closing the window".

### THE ROLLBACK TRIGGER

Roll back — do not debug in place — if **any** of these is true:

- **R1.** Task 7 Step 4 or Step 6 shows the v19 process has touched `masterfischer` (a log line
  naming it, `base.latest_version` at `19.0.*`, or a changed picking count). **Immediate,
  non-negotiable.**
- **R2.** Task 7 Step 1 does not reach `Modules loaded` within 15 minutes, or the log shows an
  unresolved module dependency.
- **R3.** Task 7 Step 2 does not list all three modules.
- **R4.** Task 7 Step 5 shows a repeating cron traceback.
- **R5.** `make verify-stack` fails and the cause is not a configuration typo fixable in under
  30 minutes.
- **R6.** The Task 7 Step 8 manual smoke cannot complete a pick confirmation.
- **R7.** Task 0 was skipped, so there are no reference numbers to compare against. Rolling back
  from an unverified premise is cheaper than discovering the premise was wrong later.

Anything else — cosmetic bugs, missing seed rows, a slow first request, the Lager-2 switcher not yet
pointing at `lager2_o19` — is **not** a rollback trigger.

### THE ROLLBACK PROCEDURE (execute under pressure, top to bottom)

Budget: (Task 7 Step 1 rebuild time) + about two minutes. **No database restore is needed in the
normal case**, because `masterfischer` was never opened by v19 (Global Constraint 2) and
`odoo_data`'s `filestore/masterfischer` was never touched (Task 3, `volumes[0]` unchanged).

- [ ] **RB1. Stop the stack. Type this exactly. `-v` is not in it and must never be.**

```bash
cd "/mnt/c/Users/endri/Desktop/Bachelor/Mobile Picking und Voice Assistant"
"$DOCKER" compose down
```

- [ ] **RB2. Revert the cutover commit.** This restores all 24 files under `odoo/addons18/`, both
  `.conf` files and every Compose key in one operation — that is exactly why they were one commit.

```bash
git revert --no-edit <TASK_3_COMMIT_SHA>
```

  If Tasks 5 and 6 already landed, revert **only** Task 3's SHA. Task 5's pinning, secrets and
  `RUNTIME_PROFILE` do not depend on the Odoo version and should stay. Task 6 is defaults and docs;
  revert it only if it confuses the operator.

- [ ] **RB3. Put `.env` back — three values, and the second one is the one people forget.**

  1. `ODOO_DB=masterfischer`
  2. **`ODOO_API_KEY=` the pre-cutover key** (kept per Task 2 Step 3). Keys are per-database; the
     new key is invalid against `masterfischer` and the restored stack will boot clean and then 401
     on every JSON-RPC call.
  3. `ODOO_INSTANCES_JSON` → `"db":"lager2"` with its old key.

  The revert cannot do any of this: `.env` is not in git (Global Constraint 4).

- [ ] **RB4. Rebuild and start the v18 stack.**

```bash
"$DOCKER" compose up -d --build odoo
"$DOCKER" compose logs --tail=80 odoo
```

  Expected: the log reports Odoo **18.0**; `Modules loaded`; the database selector offers
  `masterfischer`.

- [ ] **RB5. Verify the live data is exactly as it was.**

```bash
"$DOCKER" compose exec -T db psql -U odoo -d masterfischer -tAc \
  "SELECT state, count(*) FROM stock_picking GROUP BY state ORDER BY 1;"
```

  Expected: **identical to Task 0 Step 1's output.** Then `make verify-stack`.

- [ ] **RB6. Only if RB5 differs — restore from Task 1.** This is the trigger-R1 path, and it is the
  only path in this plan that renames a database.

```bash
"$DOCKER" compose stop odoo backend
"$DOCKER" compose exec -T db psql -U odoo -d postgres \
  -c "ALTER DATABASE masterfischer RENAME TO masterfischer_damaged_$(date +%Y%m%d);"
"$DOCKER" compose exec -T db psql -U odoo -d postgres -c "CREATE DATABASE masterfischer;"
"$DOCKER" compose exec -T db pg_restore -U odoo -d masterfischer \
  < "infrastructure/backups/masterfischer-${STAMP}.dump"
"$DOCKER" run --rm -v odoo_data:/dst -v "$(wslpath -w "$PWD/infrastructure/backups")":/in alpine \
  tar xzf "/in/odoo_filestore-${STAMP}.tgz" -C /dst
"$DOCKER" compose up -d odoo backend
```

  **Rename, never `DROP` (Global Constraint 1).** The damaged database is the only evidence of what
  went wrong. The restore duration is the number measured in Task 1 Step 4 — quote it, do not
  estimate it.

- [ ] **RB7. Record what happened** in this file under a new "Rollback executed" heading: the
  trigger, the timings, and `masterfischer`'s state before and after.

### Partial rollback — usually the better move (07-30)

Because the v18 tree exists as a `git revert` away and the v18 *database* is untouched, a v18
container can be brought up **alongside** the v19 one on a spare port for comparison, without
reverting anything: a temporary service using `odoo:18.0`, `./odoo/addons18` restored from
`git show <SHA>^:…`, `odoo_data`, and a config with `db_name = masterfischer`. Prefer this for
diagnosing a suspected regression; it does not disturb the v19 stack. **It is also how the owner
reads the 46 completed pickings after the cutover** if a `psql` query is not enough.

### What rollback does NOT recover

**Anything created in `masterfischer_o19` after the cutover is lost on rollback** — picks, quality
alerts, photos, integration jobs. This is why the window is measured in days of *running*: the
longer the v19 stack is used, the more a rollback costs, until fixing forward is cheaper than
rolling back. That crossover is a judgement the owner makes; this plan's job is to make sure it is
made rather than stumbled into. See D4.

### Closing the window

- [ ] **After the owner declares the window closed (D4):** a follow-up commit removes the
  `volumes.odoo19_trial_data` declaration (Task 3, key 9) and drops `masterfischer_o19_trial` and
  `odoo19_smoke_codex`, which are scratch databases nothing depends on.
  **`masterfischer` and `lager2` are NOT dropped — not then, not ever, per Global Constraint 1 and
  the owner's D1.** They are the queryable archive. They cost a few hundred megabytes on a volume
  that already holds eight databases.

---

## Task 9: What precisely satisfies `wave1-odoo19-handoff`

**This branch cannot create the tag.** F9: it is an annotated tag placed by the **integrator**, on
the **integration branch** `codex/integration-bachelor-hardening`, on the merge commit of
`codex/odoo19-cutover` (Foundation plan lines 88-93). `git tag -l "*wave*"` here is empty. What this
branch owes is a mergeable, reviewable state.

- [ ] **Step 1: The handoff checklist — every item demonstrable, not asserted**

- [ ] H1. `odoo/addons18/` does not exist. `git ls-files | grep addons18` → empty.
- [ ] H2. The `odoo` service builds `odoo:19.0` and mounts `./odoo/addons` — `docker compose config`
      output pasted into the merge review. **These are the "service/image/mount facts" Task 15 is
      instructed to preserve (F9).** So are the two new `.conf` files and their `db_name` keys.
- [ ] H3. No `profiles: [odoo19-trial]` remains anywhere in `docker-compose.yml`.
- [ ] H4. The v19 addon suite passes (Task 2 Step 7), with no other Odoo container running.
- [ ] H5. `masterfischer_o19` and `lager2_o19` exist, are seeded, and report
      `picking_assistant_integration 19.0.1.0.0 / installed`.
- [ ] H6. `make verify-code`, `verify-stack`, `test-ui` green; `verify-workflows` green **with the
      v1-only caveat recorded** (Task 7 Step 7).
- [ ] H7. `masterfischer` and `lager2` are provably still present, still `base 18.0.*`, still at
      their Task 0 row counts, and still restorable (Task 7 Step 6, Task 1 Step 3).
- [ ] H8. Both `odoo19.conf` and `odoo19-lager2.conf` carry `db_name` (Task 3 Step 3).

- [ ] **Step 2: Register edits — at integration, on the branch that carries the file (§0.3)**

These do **not** happen here. Hand them to the integrator as part of the merge review:

- [ ] G1. **Frozen decision §3.4** is amended from "narrow approved port — or deleted" to the
      executed answer: **deleted**, with Task 3's commit SHA as evidence.
- [ ] G2. The two "Raised during remediation" entries — *"The live Odoo-18 stack still carries the
      expired-lease hole"* and *"`odoo/addons18/` still serves the live stack and still carries the
      unfixed `_lock_or_create` defect"* — are marked **resolved by execution**. This is the
      cutover's largest security dividend: it takes production off the code carrying the **High**
      M1 session-revocation hole.
- [ ] G3. The whole-branch gate line *"the v18 auth-port suite, if that port survives decision
      §3.4"* is **struck** — the port did not survive, so that gate item is void, not pending.
- [ ] G4. Task 12's state changes from *"blocked — no `codex/odoo19-cutover`, no cutover plan, so no
      `wave1-odoo19-handoff` tag"* to unblocked once the tag lands.
- [ ] G5. The lease-token log-sink obligation is recorded as **accepted** or **redacted** per D-LOG
      below, rather than left inherited.

- [ ] **Step 3: Tell the integrator what to do**, verbatim, so the tag lands in the right place:

```bash
cd "$WT/00-integration-bachelor-hardening"
git merge --no-ff codex/odoo19-cutover -m "merge: establish Odoo 19 foundation base"
git tag -a wave1-odoo19-handoff -m "Odoo 19 runtime and addon handoff"
```

- [ ] **Step 4: Commit the superseded 07-30 plan with a banner (D6)**

Add at the top of `docs/superpowers/plans/2026-07-30-odoo19-cutover.md`:

```
> **SUPERSEDED on 2026-07-31 by `2026-07-31-odoo19-cutover.md`.** Kept for the record.
> Eleven of its findings are folded into the successor and attributed there (§0.5).
> Do not execute this file.
```

then commit it. **Do not delete it** — it is a session's independently derived work and its risk
section found the cron-master hole this plan's Revision 1 missed.

- [ ] **Step 5: What unblocks downstream, and what does not.**
  **Task 12** (`odoo/addons/picking_assistant_core/**`) becomes startable the moment the tag exists
  and the Foundation branch has rebased onto the integration branch (F9). It needs
  `picking_assistant_integration.group_api_service` resolvable at v19, which H4/H5 demonstrate.
  **Task 15** becomes startable at the same moment and inherits four things this plan deliberately
  did **not** do: removing Odoo `ports:`, splitting `picking-net`, `trusted_proxies`, and the
  `request_body max_size` + ASGI streaming limit pair from §3.8. **Task 16** stays blocked behind
  both (§3.7). **R4 Step 9** unblocks, whose own exit gate currently requires recording that Step 9
  is *not* done for lack of this tag.

  **Task 15 also owes something this plan discovered and cannot supply: the n8n half of the
  lease-token contract does not exist.** R2 Task 8 closed finding #5b's Odoo half by carrying
  `processing_lease_token` as a signed path segment —
  `GET /instances/{i}/jobs/{j}/leases/{token}/media/{m}` and
  `POST .../leases/{token}/events/{e}/artifacts/{k}`. **No workflow and no node anywhere in this
  repository builds that URL** (verified: `grep -rn "leases/" n8n/ infrastructure/` → no match).
  The register already warns that *"the R2 Odoo half cannot ship without the backend half … it is a
  total outage of those two routes until both halves ship together"*; the same argument extends one
  hop further to n8n. **Foundation Task 15 owes the n8n workflow change.** Record it in the merge
  review so it is not discovered when the first media fetch 401s.

---

## Verification Summary — what must be green

| Gate | Command / check | Expected |
|---|---|---|
| Reference numbers taken | Task 0 Step 1 | `base 18.0.*`; picking counts recorded |
| Backup restorable | Task 1 Step 3 | `pg_restore` exit 0, counts match Task 0 |
| v19 DBs seeded | Task 2 Steps 4, 6 | non-zero pickings in `masterfischer_o19` and `lager2_o19` |
| Name safe for the registry | Task 2 Step 5 | `test_instance_registry.py` green |
| v19 addon tests | Task 2 Step 7 | 8 test modules pass, no other Odoo running |
| Atomicity | Task 3 Step 2 | 24 deletions + 2 repointed mounts in one commit; grep for `addons18`/`odoo:18.0` empty |
| **Cron confinement** | Task 3 Step 3, Task 7 Step 4 | `db_name` in both configs and in the running container |
| Compose renders | Task 3 Step 4 | `compose config` exit 0, no `odoo19-trial` |
| Runtime version | Task 7 Step 1 | log reports Odoo 19.0 |
| Mount resolved | Task 7 Step 2 | three modules under `/mnt/extra-addons` |
| DB manager closed | Task 7 Step 3 | `masterfischer` not in the DB list |
| Crons quiet | Task 7 Step 5 | 15 minutes, no traceback |
| **Live DBs intact and PRESENT** | Task 7 Step 6 | `masterfischer` **and** `lager2` exist, `base 18.0.*`, counts unchanged |
| Application | Task 7 Step 7 | `verify-code`, `verify-stack`, `test-ui` green; `verify-workflows` green **v1-only** |
| Human | Task 7 Step 8 | a pick can be confirmed and the instance switch works |
| Secrets closed | Task 5 Step 6 | backend refuses to start without `RUNTIME_PROFILE` |
| Handoff | Task 9 Step 1 | H1-H8 demonstrable |

**Rollback trigger:** R1-R7 in Task 8. R1 (live database touched by v19) is immediate and
non-negotiable.

---

## Decisions owed by the owner

D1, D2, D3 and D6 are **decided** and folded in above; they are no longer listed here. What follows
is genuinely still open.

**D4 — When the rollback window closes. (blocks Task 8's "Closing the window")**
Note what the window costs in each direction: while it is open, `masterfischer_o19` accumulates
picks that a rollback discards (Task 8, "What rollback does NOT recover"); once it is closed, a
defect found later can only be fixed forward.
- *Option A — a fixed number of green running days (the 07-30 plan proposed 14).* **Consequence:**
  bounded by an explicit act rather than a timer, so it cannot lapse by accident.
- *Option B — until the thesis demo is done.* **Consequence:** ties a technical window to an
  external date; simple to communicate.
- *Consequence either way:* the only things ever dropped are `masterfischer_o19_trial` and
  `odoo19_smoke_codex`. `masterfischer` and `lager2` are **never** dropped (D1, Global Constraint 1).

**D-LOG — Accept or redact lease tokens in the three log sinks. (blocks Task 9 Step 2 G5)**
This is a register obligation created by remediation lane R2, quoted so the decision is made on its
own words and not on a paraphrase:

> **Lease tokens now appear in access logs and in n8n execution data.** … The token is genuinely
> inside the signed bytes … and no application code logs it. But a URL path is logged where a JSON
> body was not, at three concrete sinks in this repo: Caddy's server-level `log { output stdout }`
> covering `handle /api/*` (`infrastructure/caddy/Caddyfile:4-6`, `34-37`), uvicorn's access log at
> `--log-level info` (`docker-compose.yml:162`), and n8n's persisted execution data, which stores
> the built URL. … The blast radius is bounded: the token is a lease-scoped, expiring capability,
> useless without the HMAC key, and it never reaches a browser. **The obligation is to decide
> explicitly rather than inherit it silently.**

- *Option A — accept.* **Consequence:** zero work. Lease tokens sit in three log sinks; anyone with
  log access holds an expiring capability that is still useless without the HMAC key. Write the
  acceptance into the register so the next reviewer does not re-raise it.
- *Option B — redact.* **Consequence:** a Caddy log path filter, uvicorn's access log turned down or
  filtered, and a cap on n8n execution-data retention. Three edits in three systems, two of which
  (`Caddyfile`, `docker-compose.yml:162`) are inside Foundation Task 15's frozen surface — so
  Option B most likely becomes a Task 15 item rather than a cutover item.
This plan takes no position and does not implement either. It flags that the deployment which makes
those routes live is **this one**.

**D-SEQ — Does the cutover run before or after R1/R2/R3 merge? (blocks Task 7)**
The register's §2 sequencing is `R1/R2/R3 → whole-branch gate → Odoo-19 handoff → 12 → 15 → 16 → 17`,
and it states: *"No Foundation task numbered 12 or higher starts before the whole-branch gate is
green again."* The cutover is not a Foundation task, so it is not literally covered — but it
*deploys* the code those lanes are fixing.
- *Option A — cut over after the lanes merge and the whole-branch gate is green.* **Consequence:**
  production gets the fixed v19 addon. The four new crons — including the retention cron that is the
  subject of open finding **#11**, `Verified: no` — run against real data only after that finding is
  closed. Costs schedule.
- *Option B — cut over now.* **Consequence:** production comes off the **High** M1 session-
  revocation hole and the unfixed `_lock_or_create` throttle defect immediately, which is the larger
  live exposure — but puts an unfixed daily retention cron on production data, and the `odoo/addons`
  tree deployed is whatever this branch carries at `1e240f5`, not the remediated one.
This is a genuine trade between two live exposures and the plan will not choose it. Note that
Option B does **not** block the tag: the tag is placed on the merge, and the merge can precede the
deploy.

---

## What still cannot be established

| Question | Status | Why |
|---|---|---|
| Whether the v19 cron master really honours `db_name` on this Odoo build | **not empirically proven** | Argued from Odoo's `list_dbs(force=True)` vs `odoo.http.db_list` and from the programme's own `SerializationFailure` experience. Task 7 Step 4 is written to *detect* the failure at cutover time rather than assume the argument holds |
| The `uid`/`gid` the `backend` and `n8n` containers run as | not read | Task 5 Step 3 reads them from the running containers rather than guessing; the register fixes the n8n answer as the `node` user |
| Current image digests for pinning | not read | Task 5 Step 1 reads them from what is running |
| Whether `verify-workflows` would pass under v2 | **cannot be established today** | All eight registry workflows are `generation: v1`; the v2 verifier is dormant (Task 7 Step 7) |
| Which n8n workflow will build the `/leases/{token}/…` URLs | **does not exist** | No such node or workflow is in the repository; Foundation Task 15 owes it (Task 9 Step 5) |
| What `odoo19_smoke_codex` was created by | not established | It is a v19 database on the shared cluster, declared in no Compose file and no `.conf`. It is harmless and this plan does not touch it, but nobody has claimed it |
| Whether `masterfischer`'s 1558 `mail_message` rows carry anything the thesis needs | not assessed | They span 2025-01-13 .. 2026-07-25 and stay readable in `masterfischer` forever (Global Constraint 1). If any of it is needed *in v19*, that is manual re-entry, not a migration |
