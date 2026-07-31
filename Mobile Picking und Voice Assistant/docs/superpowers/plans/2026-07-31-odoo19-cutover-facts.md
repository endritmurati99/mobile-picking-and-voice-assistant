# Odoo-19 Cutover — Phase 1 Fact List

All facts established at `1e240f5` on branch `codex/odoo19-cutover`, worktree
`/mnt/c/Users/endri/Desktop/Bachelor-wt/odoo19-cutover`. Paths below are relative to
`Mobile Picking und Voice Assistant/` unless stated otherwise.

**Docker was NOT running during the original (Phase 1) investigation.** Every fact below is derived
from files.

> **REVISION 2 — 2026-07-31, Docker Desktop up.** Every fact previously marked **UNESTABLISHED** has
> since been settled by read-only SQL against the live cluster. **The live-probe results are recorded
> in §0.1 of `2026-07-31-odoo19-cutover.md`, which is the authority for them**; the markers below are
> resolved in place and point there. The `docs/superpowers/parallel/` documents named in F0 were also
> located and read — see the F0 revision note.

---

## F0 — Three background documents named in the commission do not exist on this branch

- `docs/superpowers/parallel/` — the whole directory is absent.
  Evidence: `ls docs/superpowers` → `plans/ reviews/ specs/` only.
- Therefore `docs/superpowers/parallel/2026-07-23-program-status.md` and
  `docs/superpowers/parallel/2026-07-29-handoff.md` could not be read. `find . -iname "*program-status*"
  -o -iname "*handoff*"` over the worktree returns only `docs/parallel-chats` and
  `docs/superpowers/specs/2026-07-23-parallel-modernization-program-design.md`.
- `docs/superpowers/plans/2026-07-29-r4-postgres-handoff.md` (the named house-style reference) does
  not exist either. `ls docs/superpowers/plans/` lists 12 files, none of them an R4 handoff.
  House style was therefore taken from `docs/superpowers/plans/2026-07-25-voice-track1-llm-fallback.md`
  and the existing `2026-07-30-odoo19-cutover.md`.

**Consequence:** frozen decisions §3.4 / §3.8 and the debt register could not be read at source.
Where this plan cites them it cites them as *reported by the commission*, not as verified.

> **REVISION 2 — RESOLVED.** The two documents exist in the **main tree** and were read there:
> `/mnt/c/Users/endri/Desktop/Bachelor/Mobile Picking und Voice Assistant/docs/superpowers/parallel/2026-07-23-program-status.md`
> (310 lines; frozen decisions §3, debt register §4, whole-branch gate §5) and `…/2026-07-29-handoff.md`
> (182 lines). They are absent from **this branch** only. §3.4 and §3.8 are now quoted verbatim in
> §0.2 of the plan, and §0.3 records why no step edits the register from this branch — the register
> itself already logged that failure shape once, for R1's exit gate.
> `docs/superpowers/plans/2026-07-29-r4-postgres-handoff.md` still does not exist anywhere; the
> house-style reference remains unavailable and is not needed.

## F0b — An uncommitted cutover plan for the same work already exists

- `git status --short` → `?? "Mobile Picking und Voice Assistant/docs/superpowers/plans/2026-07-30-odoo19-cutover.md"`
- 1030 lines, untracked, no commit touches it (`git log -- <path>` is empty).
- It reaches the same architectural conclusion (reseed, not migration) and records its own
  corrections-of-record section that independently found F0 above.

---

## F1 — What `docker-compose.yml` declares today (9.8 KB, 297 lines)

| Key | Value | Line |
|---|---|---|
| `caddy.image` | `caddy:2-alpine` — **floating tag** | 4 |
| `caddy.ports` | `443:443`, `80:80` (host-wide, not loopback-bound) | 6-8 |
| `caddy` volumes | Caddyfile, `./infrastructure/certs:/certs:ro`, `caddy_data`, `caddy_config` | 11-15 |
| `db.image` | `postgres:16-alpine` — **floating patch tag** | 21 |
| `db.ports` | `127.0.0.1:${POSTGRES_HOST_PORT:-5433}:5432` | 24 |
| `db` volume | `pg_data:/var/lib/postgresql/data` + `init-n8n-db.sql` initdb hook | 30-31 |
| `db.healthcheck` | `pg_isready -U ${POSTGRES_USER:-odoo}` | 33 |
| `odoo.build.args.ODOO_BASE_IMAGE` | **`odoo:18.0`** | 46 |
| `odoo` — no `profiles:` key | i.e. it is the **default/always-on** service | 41-63 |
| `odoo.ports` | `8069:8069` (host-wide) | 57 |
| `odoo` volumes | `odoo_data:/var/lib/odoo`, `./odoo/odoo.conf:/etc/odoo/odoo.conf:ro`, **`./odoo/addons18:/mnt/extra-addons:ro`** | 58-61 |
| `odoo-lager-2` | `profiles: [second-odoo]`, `ODOO_BASE_IMAGE: odoo:18.0`, mounts **`./odoo/addons18`**, `odoo-lager2.conf`, vol `odoo_lager2_data`, port `${ODOO_LAGER2_PORT:-8070}:8069` | 66-90 |
| `odoo19-trial.build.args.ODOO_BASE_IMAGE` | **`odoo:19.0`** | 98 |
| `odoo19-trial.profiles` | `[odoo19-trial]` | 99-100 |
| `odoo19-trial.ports` | `127.0.0.1:${ODOO19_TRIAL_PORT:-8100}:8069` (loopback-bound) | 111 |
| `odoo19-trial` volumes | `odoo19_trial_data:/var/lib/odoo`, `./odoo/odoo19-trial.conf`, **`./odoo/addons:/mnt/extra-addons:ro`** | 112-115 |
| `backend.environment.ODOO_URL` | `http://odoo:8069` — points at the **service name**, not the image | 131 |
| `backend.environment.ODOO_DB` | `${ODOO_DB:-picking}` | 132 |
| `backend` DEMO_TRACEABILITY_ALLOWED_DBS | `${DEMO_TRACEABILITY_ALLOWED_DBS:-masterfischer_o19_trial}` | 158 |
| `whisper.image` | `onerahmet/openai-whisper-asr-webservice:latest` — **`:latest`, unpinned** | 168 |
| `ollama.image` | `ollama/ollama:latest` — **`:latest`, unpinned** | 189 |
| `n8n.image` | `docker.n8n.io/n8nio/n8n:2.13.3` — **pinned by tag**, no digest | 200 |
| `pwa.image` | `caddy:2-alpine` — **floating tag** (second Caddy) | 275 |
| volumes | `pg_data`, `odoo_data`, `odoo_lager2_data`, `odoo19_trial_data` (explicit `name: odoo19_trial_data`), `caddy_data`, `caddy_config`, `n8n_data`, `ollama_data` | 283-292 |
| networks | single `picking-net`, `driver: bridge` — **no internal/external split** | 295-297 |
| `secrets:` top-level block | **DOES NOT EXIST**. `grep -n secrets docker-compose.yml` → no match. | — |
| `RUNTIME_PROFILE` | **NOT SET by Compose** and absent from `.env.example`. The *backend setting* exists (`backend/app/config.py:69`, default `"development"`) — see F8. Uppercase `RUNTIME_PROFILE` appears only in two docs: the Foundation plan (line 7779) and the untracked 07-30 plan (line 799). | — |

## F2 — Odoo MAJOR VERSION serving live `masterfischer`: **v18** (static evidence, not probed)

- `docker-compose.yml:41-63` — the service literally named `odoo`, with **no profile** (so it is what
  `docker compose up -d` starts), builds from `ODOO_BASE_IMAGE: odoo:18.0` (line 46).
- `odoo/Dockerfile` is a 4-line passthrough: `ARG ODOO_BASE_IMAGE=odoo:18.0` / `FROM ${ODOO_BASE_IMAGE}`
  / `USER root` / `USER odoo`. It adds nothing; the base image tag is the whole story.
- `odoo/odoo.conf` (mounted into `odoo`) has `dbfilter = ^(picking|masterfischer)$` — `masterfischer`
  is served by **this** container, the v18 one.
- `odoo/odoo19-trial.conf` has `dbfilter = ^masterfischer_o19_trial$` — the v19 container can serve
  **only** `masterfischer_o19_trial`, never `masterfischer`.
- The comment at `docker-compose.yml:40` reads `── Odoo 18 Community (Live/Default) ──`.

**So the "already v19, plan collapses" escape hatch does NOT apply.** `masterfischer` is a v18
database served by a v18 container.

> **REVISION 2 — ESTABLISHED, not inferred.** `SELECT name, latest_version FROM ir_module_module`
> against the live `masterfischer` returns `base = 18.0.1.3`, `stock = 18.0.1.1`,
> `picking_assistant_integration = 18.0.1.0.0`. Installed modules:
> `picking_assistant_core 18.0.1.0.0`, `picking_assistant_integration 18.0.1.0.0`,
> `quality_alert_custom 18.0.1.1.0`, `stock 18.0.1.1`, `stock_picking_batch 18.0.1.0`,
> `stock_sms 18.0.1.0`. The escape hatch is definitively closed. See plan §0.1.

## F3 — v19 vs v18 addon trees

Command: `diff <(cd odoo/addons && find . -type f|sort) <(cd odoo/addons18 && find . -type f|sort)`

Both trees contain the same three modules: `picking_assistant_core`, `picking_assistant_integration`,
`quality_alert_custom`.

**Present in v18 only (1 file):** `odoo/addons18/README.md`.

**Present in v19 only (12 files), all under `picking_assistant_integration`:**
- `models/integration_job.py`
- `models/outbox.py`
- `models/receipts.py`
- `models/resources.py`
- `tests/__init__.py`, `tests/common.py`, `tests/test_crons_retention.py`,
  `tests/test_job_outbox_transaction.py`, `tests/test_receipts_callbacks.py`,
  `tests/test_resources.py`, `tests/test_security.py`, `tests/test_session_throttle.py`

**Models (`_name = …`) present in v19 and ABSENT from v18** — `grep -rn "_name = " …/models/`:
| Model | v19 file:line |
|---|---|
| `picking.assistant.outbox` | `odoo/addons/picking_assistant_integration/models/outbox.py:11` |
| `picking.assistant.integration.job` | `odoo/addons/picking_assistant_integration/models/integration_job.py:38` |
| `picking.assistant.webhook.nonce` | `odoo/addons/picking_assistant_integration/models/receipts.py:30` |
| `picking.assistant.event.receipt` | `odoo/addons/picking_assistant_integration/models/receipts.py:96` |
| `picking.assistant.callback.receipt` | `odoo/addons/picking_assistant_integration/models/receipts.py:275` |

Models present in **both**: `picking.assistant.api.mixin` (`api_security.py:6`),
`picking.assistant.auth.throttle` (`auth_throttle.py:13`), `picking.assistant.session`
(`session.py:11`).

**No model exists in v18 and is absent from v19.** The v18 tree is a strict subset.

Manifest versions: `odoo/addons/picking_assistant_integration/__manifest__.py:3` → `"19.0.1.0.0"`;
`odoo/addons18/…/__manifest__.py:3` → `"18.0.1.0.0"`. Both `"depends": ["base"]`.

**Consequence for the owner's constraint:** the constraint is CORRECT and load-bearing. The live
`odoo` service resolves `picking_assistant_integration` exclusively through
`./odoo/addons18:/mnt/extra-addons:ro` (`docker-compose.yml:61`). Deleting `addons18/` without
changing line 61 in the same commit leaves the live container with an empty addons mount.
A second service has the same dependency: `odoo-lager-2` also mounts `./odoo/addons18`
(`docker-compose.yml:88`) — **the commission does not mention it, and it must be reworked in the
same commit or it breaks too.**

## F4 — ONE PostgreSQL cluster, one volume, shared by both Odoo versions

- There is exactly one Postgres service in `docker-compose.yml`: `db` (line 20), image
  `postgres:16-alpine`, single volume `pg_data:/var/lib/postgresql/data` (line 30).
- `odoo` sets `HOST: db` (line 52). `odoo19-trial` sets `HOST: db` (line 106). `odoo-lager-2` sets
  `HOST: db` (line 79). n8n sets `DB_POSTGRESDB_HOST: db` (line 218).
- Therefore **`masterfischer`, `masterfischer_o19_trial`, `masterfischer_o19_foundation_test`,
  `n8n` and `picking` are all databases inside the SAME cluster on the SAME `pg_data` volume.**

> **REVISION 2 — the actual inventory, probed.** `SELECT datname FROM pg_database` returns
> `lager2`, `masterfischer`, `masterfischer_o19_foundation_test`, `masterfischer_o19_trial`, `n8n`,
> `odoo19_smoke_codex`, `picking`, `postgres` (+ `template0/1`). **`lager2` and `odoo19_smoke_codex`
> were missing from the list above.** Odoo majors: `masterfischer`/`lager2`/`picking` are all
> `base 18.0.1.3`; `masterfischer_o19_trial`/`masterfischer_o19_foundation_test`/`odoo19_smoke_codex`
> are `base 19.0.1.3`. Only `masterfischer_o19_foundation_test` has
> `picking_assistant_integration 19.0.1.0.0` installed — it is the standing proof the v19 addon
> installs cleanly. `odoo19_smoke_codex` is declared in no Compose file and no `.conf`; nobody has
> claimed it. See plan §0.1.
- `masterfischer_o19_foundation_test` appears only as a Foundation-plan test database
  (`docs/superpowers/plans/2026-07-23-platform-security-event-contracts-foundation.md:2167-2168,
  2412-2413, 3099-3100`, always with `--db-filter '^masterfischer_o19_foundation_test$'`). It is not
  declared in Compose or in any `.conf` file.

**Consequences that matter for the plan:**
1. A single `pg_dumpall` or volume snapshot captures everything; a single volume restore rolls
   everything back — including n8n's database. Rollback granularity is therefore per-database
   (`pg_restore`), not per-volume, unless the operator accepts rolling n8n back too.
2. `docker compose down -v` (which `make clean`, `Makefile:116`, runs as `down -v --rmi local`)
   destroys `pg_data` and therefore **all** of them. `make clean` is a loaded gun during cutover.

## F5 — The real migration path: **there is none in this repository; it is a reseed**

Evidence, both negative and positive:
- No OpenUpgrade, no migration tooling: `odoo/Dockerfile` is 4 lines and installs nothing. There is
  no `migrations/` directory under `odoo/addons18/` and none under `odoo/addons/` at `1e240f5`
  (the full `find odoo/addons* -type f` listing in F3 contains no `migrations` path).
- Odoo Community has no in-place major upgrade; Odoo's upgrade service (upgrade.odoo.com) is the
  vendor path and is external to this repository. Nothing in the repository calls it.
- The repository's actual data-creation path is `infrastructure/scripts/seed-odoo.py` (40.2 KB). Its
  docstring line 2 reads **"Seed-Daten für Odoo 19 Community."** and its documented invocation is
  `python seed-odoo.py --url http://localhost:8069 --db masterfischer --user admin --api-key admin`
  (lines 10-11). It creates `res.users`, `res.partner`, `stock.quant`, `stock.picking(.type)` via
  XML-RPC (lines 206-457) and installs `quality_alert_custom` + `stock_picking_batch`
  (lines 595-599).
- `Makefile:51` wires it: `seed: python infrastructure/scripts/seed-odoo.py --url http://localhost:8069 --db $${ODOO_DB:-picking} …`

**So: `masterfischer` is v18 (F2), v19 cannot simply be pointed at it (v19 would run its own
base-module upgrade, and the addon tree it needs is a different, larger tree — F3), and the
repository contains no migration. The only path the repository supports is: create a NEW v19
database and reseed it with `seed-odoo.py`.** Anything else — Odoo's paid upgrade service, or
hand-written OpenUpgrade scripts — is work that does not exist here and would have to be
commissioned separately.

## F6 — What data actually lives in `masterfischer`: **ESTABLISHED — thesis working data, no business records**

> **REVISION 2 — probed read-only.** `stock_picking` **66** rows (46 `done`, 20 `assigned`), created
> 2026-03-22 .. 2026-07-25. `stock_move_line` 420. `res_partner` 9. `product_product` 54.
> `res_users` 7. `mail_message` 1558, spanning 2025-01-13 .. 2026-07-25. **`sale_order` and
> `account_move` do not exist as tables** — the sale and accounting modules were never installed.
> So the circumstantial "seed-only" reading below was too weak *and* the "real business history"
> fear was too strong: it is **thesis working data — no customer records, no accounting, no
> invoices**. `lager2` holds 9 `assigned` pickings and no completed ones.
>
> **The owner decided on this evidence (D1): reseed, and `masterfischer` is not deleted.** The 46
> completed pickings will not be visible in the new stack; nothing is destroyed. See plan §0.1 and
> Global Constraint 1.

Original Phase-1 reasoning, retained for the record:

Circumstantial evidence that it is seed data:
- `seed-odoo.py`'s own documented target database is `masterfischer` (docstring line 11).
- `docs/superpowers/plans/2026-06-24-cluster-picking-abschluss.md:16` calls it
  "Aktive Demo-DB: `masterfischer` (admin/admin), Picker „Max Picker" = uid 7", and line 107 says
  "vorhanden (laut Seed ~16). Falls nötig: `make seed` (mit `ODOO_DB=masterfischer`)".
- `docs/parallel-chats/CHAT-3-cluster-picking.md:31` — "Demo-DB `masterfischer`".
- `backend/tests/test_demo_routes.py:15` monkeypatches `odoo_db` to `"masterfischer"` as the demo DB.

Nothing in the repository describes `masterfischer` as production or as holding customer history.
**But "every document calls it a demo DB" is not the same as "nobody typed real pickings into it
since June."** The verifying query is written into the plan as Task 0 and must be run before the
cutover commit is executed. This is the single fact most able to invalidate the plan.

## F7 — Image pinning status (Task 15 owes a pin)

| Service | Line | Tag | Pinned? |
|---|---|---|---|
| `caddy` | 4 | `caddy:2-alpine` | **NO** — floating major-line tag. Cannot express "at least 2.10". |
| `pwa` | 275 | `caddy:2-alpine` | **NO** — a second, independent Caddy with the same floating tag |
| `db` | 21 | `postgres:16-alpine` | **NO** — floating minor/patch inside 16.x |
| `odoo` | 46 | build arg `odoo:18.0` | major line only; `18.0` is a moving tag |
| `odoo-lager-2` | 71 | build arg `odoo:18.0` | same |
| `odoo19-trial` | 98 | build arg `odoo:19.0` | same — `19.0` is a moving tag |
| `whisper` | 168 | `onerahmet/openai-whisper-asr-webservice:latest` | **NO — `:latest`** |
| `ollama` | 189 | `ollama/ollama:latest` | **NO — `:latest`** |
| `n8n` | 200 | `docker.n8n.io/n8nio/n8n:2.13.3` | tag-pinned, **no digest** |

**No service in the file is digest-pinned.** `grep -c "@sha256" docker-compose.yml` → 0.

**Caddy >= 2.10 / `request_body max_size`: UNVERIFIABLE FROM THIS BRANCH.** Grepping the Foundation
plan for `request_body`, `max_size` and `caddy:2.` returns **no match**, and the frozen-decision
register (§3.8) lives in the missing `docs/superpowers/parallel/` (F0).
`infrastructure/caddy/Caddyfile` (45 lines) contains no `request_body` directive today. The plan
therefore treats "Caddy >= 2.10 for `request_body max_size`" as a **commissioned requirement taken
on trust**, not as a fact re-derived from this branch.

> **REVISION 2 — RESOLVED at source, and the ownership was wrong.** Frozen decision §3.8 reads:
> *"The request body limit is a Task 15 obligation and needs two layers. `await request.body()`
> necessarily precedes signature verification, and `Content-Length` is bypassable with chunked
> encoding. Caddy's `request_body max_size` protects the edge only and requires Caddy >= 2.10,
> which is a second reason to pin the image. Direct n8n → backend calls need an ASGI-level
> streaming limit as well."*
> So `request_body max_size` is **Foundation Task 15's, not the cutover's**, and it needs a second
> ASGI-level layer this plan cannot supply. §3.5 likewise assigns `trusted_proxies` to Task 15 and
> names the **Caddy image pin** as an obligation. The cutover plan therefore does the pin (at a
> >= 2.10 tag) and nothing else on that surface. See plan §0.2. Revision 1's decision **D5** — a
> blind `16MB` value — is withdrawn.

## F8 — `secrets:` and `RUNTIME_PROFILE` — what exists and what does not

**`secrets:`** — `docker-compose.yml` has **no** top-level `secrets:` block and **no** per-service
`secrets:` key (`grep -n secrets docker-compose.yml` → no match). Every credential is passed as a
plain environment variable (lines 148-151, 222-224, 262).
The consuming contract already exists on the backend side in the Foundation plan:
`read_secret(direct, file_path)` rejects a file whose mode has any bit set in `0o077`
(Foundation plan lines 7755-7765), i.e. the file must be `0400`/`0600`. That is the concrete reason a
Compose `secrets:` entry must carry explicit `uid`, `gid`, `mode`: a default-mounted Docker secret
is world-readable `0444` and would fail that check at backend startup. Secret target paths are
`/run/secrets/pwr_*` (Foundation plan lines 7176-7180).

**`RUNTIME_PROFILE`** — the *backend setting exists*: `backend/app/config.py:69`
`runtime_profile: str = "development"`. Its enforcement gate is `backend/app/config.py:175`:
`if candidate.runtime_profile != "production": return` — i.e. the entire
`validate_runtime_security()` body (HTTPS-only origins, no header-grace mode, mandatory Odoo
credentials, >=32-byte n8n secrets, base64 secret validation) is **skipped whenever the variable is
unset**. `docker-compose.yml` never sets it, so the deployed backend today runs with all of that
disabled. `.env.example` does not contain it either; the Foundation plan's target `.env.example`
does (Foundation plan line 7779, `RUNTIME_PROFILE=production`). This is exactly the
`${RUNTIME_PROFILE:?…}` fail-closed hardening the register asked for.

## F9 — Task 12 / Task 15 / `wave1-odoo19-handoff`: what the gate actually says

- The tag is created **not on this branch**. Foundation plan lines 88-93:
  ```
  cd "$WT/00-integration-bachelor-hardening"
  git merge --no-ff codex/odoo19-cutover -m "merge: establish Odoo 19 foundation base"
  git tag -a wave1-odoo19-handoff -m "Odoo 19 runtime and addon handoff"
  ```
  So `wave1-odoo19-handoff` is an **annotated tag placed by the integrator on the integration
  branch, on the merge commit of `codex/odoo19-cutover`**. This branch cannot create it; it can only
  become mergeable and reviewable.
- `git tag -l "*wave*"` in this worktree → empty. The only tag present is
  `foundation-plan-approved-2026-07-23`.
- Task 12 gate (Foundation plan line 6103): "Start this task only after `wave1-odoo19-handoff` exists
  and the Foundation branch has rebased onto the integration branch."
- Task 15 gate (Foundation plan line 7332): "Start Compose edits only after `wave1-odoo19-handoff`.
  Rebase first and **preserve the Odoo-19 service/image/mount facts delivered by that branch**."
- Task 12 writes into `odoo/addons/picking_assistant_core/` — `models/idempotency.py`,
  `data/ir_cron.xml`, `migrations/19.0.2.0.0/pre-migrate.py`, `tests/` — i.e. **the v19 tree only**
  (Foundation plan lines 6105-6116). It needs `addons/` to be the productive tree and needs
  `picking_assistant_integration.group_api_service` resolvable at v19 (Foundation plan lines 6135-6140).
- Task 15 will later **remove `ports:` from every Odoo service** and split `picking-net` into
  `edge-net` / `core-net` (internal) / `automation-net` (internal) (Foundation plan lines 7660-7700
  and 7790). The cutover must not create Odoo Compose facts that Task 15 then has to undo.

## F10 — Tooling that already exists and that the cutover should reuse

- `infrastructure/scripts/clone-postgres-volume.sh` — "Offline, verified clone of a Docker volume
  holding a PostgreSQL data directory, for disposable migration testing (Task 13 / Task 15)".
  Subcommands `create|verify|delete|assert-target|compose-up`. It refuses to run while a running
  container mounts the source volume, verifies with sorted SHA-256 manifests plus matching
  `PG_VERSION`, and writes an identity token into the copy. **This is the pre-built
  restore-rehearsal instrument — the plan does not need to invent one.**
- `infrastructure/scripts/init-db-roles.sh`, `verify-db-role-isolation.sh`,
  `migrate-n8n-db-role.sh` — database-role work already scripted (Foundation Task 13 territory).
- `infrastructure/scripts/setup-certs.sh`; `infrastructure/scripts/test-api.py` reached through
  `make verify-stack` (`Makefile:103-104`).
- `Makefile:118-122` — `shell-odoo` and `shell-db` hardcode `docker compose exec odoo …` and
  `exec db …`. After the rename `shell-odoo` targets the v19 container automatically, which is
  correct, but `$${ODOO_DB:-picking}` still defaults to `picking`.
- `Makefile:11` — `make setup` refuses to proceed if `.env` is missing; `.env` itself is **not in
  the repository** (`.gitignore`), so every `.env` change in this plan is an operator action that
  no commit can carry. Only `.env.example` is committable.
