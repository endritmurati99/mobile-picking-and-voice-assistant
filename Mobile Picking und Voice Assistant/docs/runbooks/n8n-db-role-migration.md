# Runbook: n8n / Odoo Database Role Migration

Migrates the shared PostgreSQL superuser role (`odoo`, historically used
by both Odoo and n8n) onto two dedicated, non-superuser application
roles: `odoo_app` and `n8n_app`. Applies to an **existing, populated**
Postgres volume. For a brand-new volume, `init-db-roles.sh` runs
automatically via `docker-entrypoint-initdb.d` and no manual migration
is needed.

**Status:** Task 13 delivers the scripts and this runbook. Wiring the
new roles into the live `docker-compose.yml` / local `.env` contract is Task
15's job — until that lands, do not run `apply` against the real
production volume. `docker-compose.db-migration.yml` and
`clone-postgres-volume.sh` let you rehearse the whole flow safely
against a disposable clone first.

## Prerequisites

- The final Odoo-19 production database name is known and exported as
  `ODOO_DB_NAME`. The scripts refuse to run without it — they never
  guess a database name.
- Password files for the new roles exist on disk, mode `0400` or
  `0600`, and are referenced via:
  - `PWR_DB_ADMIN_PASSWORD_FILE`
  - `ODOO_DB_PASSWORD_FILE`
  - `N8N_DB_PASSWORD_FILE`
- If the existing shared superuser role is not named `odoo`, export
  `LEGACY_DB_SUPERUSER` (must not be `postgres` or `pwr_db_admin`).
- `docker compose` can reach the target stack, and you are authorized
  to stop `n8n` (and, during `apply`/`rollback`, `odoo`) for the
  duration of the migration.
- A full backup destination with enough disk space for a `pg_dumpall
  --roles-only`, a `pg_dump --format=custom` of `n8n`, and two ACL
  reports.

## Rehearse first, on a disposable clone

Before touching the real volume, clone it offline and rehearse the
full backup → apply → verify → rollback cycle against the clone:

```bash
bash infrastructure/scripts/clone-postgres-volume.sh create \
  <production_volume_name> pwr_migration_rehearsal_data /path/to/manifest-dir

# Required entry point: the override YAML cannot itself verify the
# volume it is given is the disposable clone and not the live source
# (or a volume merely renamed/recreated to look like it), so never run
# `docker compose ... up` against docker-compose.db-migration.yml
# directly. Always go through this wrapper, which runs the assert-target
# guard (name AND identity-token check) and only then starts the
# override:
bash infrastructure/scripts/clone-postgres-volume.sh compose-up \
  /path/to/manifest-dir pwr_migration_rehearsal_data pwr_dbrole_rehearsal
```

Run the migration commands below against the `pwr_dbrole_rehearsal`
project. When done:

```bash
docker compose -p pwr_dbrole_rehearsal down
bash infrastructure/scripts/clone-postgres-volume.sh delete \
  pwr_migration_rehearsal_data /path/to/manifest-dir
```

`clone-postgres-volume.sh create` refuses to run while any running
container mounts the source volume, so take it while the stack (or at
minimum the `db` service) is stopped, or clone from a point-in-time
backup instead of the live volume.

## Operator sequence (real migration, after Task 15)

```bash
BACKUP_DIR="n8n/backups/db-role-$(date -u +%Y%m%dT%H%M%SZ)"
install -d -m 0700 "$BACKUP_DIR"
bash infrastructure/scripts/migrate-n8n-db-role.sh backup "$BACKUP_DIR"
bash infrastructure/scripts/migrate-n8n-db-role.sh apply "$BACKUP_DIR"
bash infrastructure/scripts/migrate-n8n-db-role.sh verify
# On failure:
bash infrastructure/scripts/migrate-n8n-db-role.sh rollback "$BACKUP_DIR"
```

### Phase 1: `backup`

What it does: writes `roles-before.sql` (`pg_dumpall --roles-only`),
`n8n-before.dump` (`pg_dump --format=custom` of `n8n`),
`database-acl-before.tsv`, `n8n-schema-acl-before.tsv`, and the legacy
role's `pg_roles` flags, then a `manifest.sha256` covering all four
backup files. `umask 077` is set for the whole script and the backup
directory itself must not be world-readable.

Expected output: one log line per artifact and a final "Backup
complete in $BACKUP_DIR" line. No stack downtime — this phase only
reads.

Stop/start impact: none.

### Phase 2: `apply`

What it does, in order:

1. verifies `manifest.sha256` from the backup phase;
2. stops `n8n` (`docker compose stop n8n`);
3. creates `pwr_db_admin`, `odoo_app`, `n8n_app` if they don't exist,
   using the password files;
4. in `n8n`: `REASSIGN OWNED BY <legacy> TO n8n_app`, then reassigns
   database/schema ownership, tables, sequences, and default
   privileges to `n8n_app`;
5. in the Odoo-19 database: the same reassignment sequence, onto
   `odoo_app`;
6. checks the resolved `docker compose config` output references both
   `odoo_app` and `n8n_app` before starting anything;
7. starts Odoo and n8n with the new role secret files;
8. runs `verify-db-role-isolation.sh`;
9. only if every check in step 8 passes, demotes the legacy role with
   `ALTER ROLE <legacy> NOSUPERUSER NOCREATEDB NOCREATEROLE NOLOGIN`.

Expected output: a log line per step, ending in "Apply complete:
<legacy> demoted, odoo_app/n8n_app own their databases".

Stop/start impact: `n8n` is stopped for the whole phase; `odoo` is
restarted once during step 7. Expect a short outage window for both
services, sized to how long steps 3–8 take on your data volume.

**Second-operator review gate:** step 9 (demoting the legacy
superuser) is irreversible in practice — reversing it requires the
`rollback` phase, not a quick toggle. A second operator must review
and approve the isolation-verifier output (step 8) before step 9 runs
unattended in production. Do not run `apply` unattended the first time
against real data; watch it complete through step 8, get a second
sign-off, then let step 9 proceed.

### Phase 3: `verify`

What it does: runs `verify-db-role-isolation.sh` standalone. Six
checks, three positive and three negative:

1. `pwr_db_admin`: `rolsuper=true`; application services never
   authenticate as it.
2. `odoo_app`: `rolsuper=false`, `rolcreatedb=false`,
   `rolcreaterole=false`.
3. `n8n_app`: `rolsuper=false`, `rolcreatedb=false`,
   `rolcreaterole=false`.
4. `n8n_app` can connect, create, and roll back a temp table in `n8n`.
5. `n8n_app` connecting to the Odoo database fails (expected
   connection failure).
6. `odoo_app` can connect and read its own schema; connecting to `n8n`
   fails (expected connection failure).

Expected output: "OK: ..." per check, ending in "All six isolation
checks passed". Any negative check that unexpectedly succeeds is a
hard failure and stops the script immediately. Uses
`PGCONNECT_TIMEOUT=3`; never invokes `set -x`; redacts connection URIs
in log output.

Stop/start impact: none — read-only probes plus one temp-table
create/rollback in `n8n`.

### Phase 4: `rollback` (only on failure)

**Rollback decision point:** run this if `apply` fails at any step
before step 9 (legacy-role demotion), or if the `verify` phase (step 8
or standalone) reports any failed check. Once step 9 has completed
successfully and `verify` has passed clean, prefer forward-fixing over
rollback — the legacy role is already demoted and a rollback re-adds a
login superuser to the cluster.

What it does:

1. stops `n8n` and `odoo`;
2. re-enables the legacy role's `LOGIN` attribute (the script logs the
   pre-migration flags from `legacy-role-flags-before.tsv` for manual
   review — `SUPERUSER`/`CREATEDB`/`CREATEROLE` are not auto-restored
   and must be re-applied by hand if the legacy role held them);
3. drops and recreates `n8n`, owned by the legacy role, then restores
   it from `n8n-before.dump` via `pg_restore --no-owner --role
   <legacy>`;
4. database/schema ACL restoration from the two `*-acl-before.tsv`
   reports is **not** applied automatically — generate and review SQL
   from those reports by hand before applying;
5. starts `odoo` and `n8n` with the legacy-role override;
6. instructs the operator to run each service's pre-migration health
   probe manually.

`rollback` never drops `pwr_db_admin`, `odoo_app`, or `n8n_app`. Their
application grants should only be removed after the legacy-role
services are confirmed healthy again, preserving an auditable recovery
path for a second migration attempt.

## Backup retention

Keep the timestamped `n8n/backups/db-role-<UTC timestamp>/` directory
until `verify` has passed in production and stayed green for at least
one full operational cycle (e.g. one business day) after `apply`.
Backups contain the pre-migration role dump, the full `n8n` database
dump, and ACL reports — treat the directory as sensitive and keep its
`0700`/`0600` permissions intact wherever it is archived.

## Known deferred gates

- `docker-compose.yml` and the local `.env` contract are not modified by Task 13.
  The Compose-level contract test
  (`test_no_app_uses_cluster_bootstrap_role_in_compose`) stays red
  until Task 15 wires `DB_POSTGRESDB_USER: ${N8N_DB_USER:-n8n_app}` and
  `USER: ${ODOO_DB_USER:-odoo_app}` into the real service definitions.
  This is expected, not a defect in Task 13's scripts.
- The real production Odoo-19 database name was not established when
  these scripts were written (no `wave1-odoo19-handoff` branch existed
  yet). Every script takes `ODOO_DB_NAME` as a required input and fails
  closed rather than guessing it.

## Verification limits

`infrastructure/tests/test_db_role_scripts.py` proves what it can
without a real PostgreSQL cluster: `bash -n` syntax validity; that
every mode fails closed on a missing `ODOO_DB_NAME`; that
`init-db-roles.sh` refuses to run under any `POSTGRES_USER` other than
`pwr_db_admin`; and, via subprocess tests against stubbed `psql`/
`docker` binaries on `PATH`, that a real `apply` run's actual SQL
invocations (not just the script text) create `odoo_app`/`n8n_app` as
`NOSUPERUSER NOCREATEDB NOCREATEROLE`, create `pwr_db_admin` itself,
substitute the legacy role name only through psql's quoted-identifier
form, and emit the `PUBLIC` CONNECT/TEMPORARY and schema revokes for
both databases. It also proves `clone-postgres-volume.sh`'s `delete`
and `assert-target` refuse the recorded source volume, and that
`assert-target` requires the recorded identity token to be present
inside the target volume's data.

What these tests **cannot** prove, because the stubbed `psql` never
runs real SQL against a real server:

- That the generated SQL is syntactically valid PostgreSQL and executes
  without error (only `bash -n` is checked; the SQL text itself is
  exercised but not compiled by a real server).
- That the isolation verifier's six checks actually pass against a real
  cluster: the stub answers a fixed set of expected query shapes and
  simulates the two negative-check connection failures by pattern
  match, not by real `pg_hba.conf`/role-membership enforcement.
- That `pg_dump`/`pg_dumpall`/`pg_restore` produce restorable output, or
  that `REASSIGN OWNED`/`ALTER DEFAULT PRIVILEGES` behave as intended
  against a database with real, non-trivial object ownership.
- That the offline volume clone (`tar` through a throwaway container),
  the SHA-256 manifest comparison, and the identity-token file survive
  a real PostgreSQL data directory's size and permission bits.
- Anything about performance, timing, or behavior under concurrent
  access (e.g. another connection open on `n8n` when `apply` reassigns
  ownership).

These gaps are exactly what the **required live rehearsal** (see
"Rehearse first, on a disposable clone" above) exists to close before
Task 15 runs `apply` against the real production volume. Do not treat
a green test run as evidence the migration works against a live
cluster — treat it as evidence the scripts are internally consistent
and fail closed on the inputs tests can control.
