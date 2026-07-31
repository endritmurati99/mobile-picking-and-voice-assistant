# R4 — PostgreSQL Bootstrap and Migration Reversibility Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make an empty-volume bring-up work again, and turn the role migration into something that is genuinely reversible and genuinely rehearsed against a real PostgreSQL cluster.

**Architecture:** Task 1 restores a self-sufficient fresh-init for the pre-handoff world and parks the Task-13 hardening SQL behind the handoff. Task 2 splits `apply` so demotion becomes a separately approved step, makes role and ACL rollback automatic, and closes Task 13 with an actual live rehearsal. This lane is **serial**: Task 2's second half is gated on the Odoo-19 handoff.

**Tech Stack:** PostgreSQL 16 (alpine), Docker Compose, bash, pytest with stubbed subprocesses.

## Global Constraints

- Test command: `cd backend && PYTHONPATH=.deps python -m pytest ../infrastructure/tests/test_db_role_scripts.py -q`
- Every shell script must pass `bash -n` before commit.
- `\getenv` requires PostgreSQL >= 10 — fine for `postgres:16-alpine`, but note it if the image ever moves.
- Never pass a password in `argv`; it is readable via `ps`. Read it per invocation from the environment with `\getenv`.
- Never write an identity token into a production volume. The source volume stays identified by name plus `CreatedAt`; only the *copy* carries a sentinel.
- Quote every identifier interpolated into SQL: `:"legacy"` or `format('%I', :'legacy') \gexec`. Five injection sites were already closed once here.
- **Correction of record:** an earlier review claimed Task 13 modified `docker-compose.yml` in violation of the handoff rule. It did not. `git diff --stat foundation-plan-approved-2026-07-23..1e240f5 -- docker-compose.yml` is one inserted line, and it comes from the live bugfix commit `48ebc4b` (session throttle secret), not from Task 13. What Task 13 actually broke is `init-n8n-db.sql`.

---

### Task 1: Make an empty volume bootstrap again

Finding #14 (Important). Before Task 13, `infrastructure/scripts/init-n8n-db.sql` was
self-sufficient:

```sql
CREATE DATABASE n8n;
GRANT ALL PRIVILEGES ON DATABASE n8n TO odoo;
```

Task 13 rewrote that file to assume the `n8n_app` role already exists — created by
`infrastructure/scripts/init-db-roles.sh`, which the compose file does **not** mount. So an empty
`pg_data` volume now aborts during init. Worse, the file is mounted into
`docker-entrypoint-initdb.d` and therefore runs against `POSTGRES_DB=postgres` with no `\connect n8n`,
so its `REVOKE`/`GRANT`/`ALTER SCHEMA public` statements would target the wrong database even if the
role existed.

The role-separated world is correct but belongs **after** the Odoo-19 handoff. Until then, restore
a working bootstrap and park the hardening.

**Files:**
- Modify: `infrastructure/scripts/init-n8n-db.sql` (restore the self-sufficient bootstrap)
- Create: `infrastructure/scripts/init-n8n-db-hardening.sql` (the Task-13 content, not yet mounted)
- Modify: `docs/runbooks/n8n-db-role-migration.md` (state which file is live today)
- Test: `infrastructure/tests/test_db_role_scripts.py` (extend)

**Interfaces:**
- Consumes: nothing new.
- Produces: `infrastructure/scripts/init-n8n-db-hardening.sql`, which becomes mounted in Task 2 Step 6 together with `init-db-roles.sh`. It must begin with `\connect n8n` so it can never again grant in the wrong database.

- [ ] **Step 1: Write the failing tests**

Append to `infrastructure/tests/test_db_role_scripts.py`:

```python
INITDB_DIR = "/docker-entrypoint-initdb.d"


def _compose_db_volumes():
    document = yaml.safe_load(COMPOSE_PATH.read_text(encoding="utf-8"))
    return document["services"]["db"]["volumes"]


def test_every_mounted_init_script_is_self_sufficient():
    """A file in docker-entrypoint-initdb.d runs on an EMPTY cluster. It may
    not presuppose a role that a script nobody mounts would have created.
    Regression cover for finding #14."""
    mounted = [
        entry.split(":")[0].lstrip("./")
        for entry in _compose_db_volumes()
        if INITDB_DIR in entry
    ]
    assert mounted, "the db service mounts no init script at all"
    for relative in mounted:
        body = (REPO_ROOT / relative).read_text(encoding="utf-8")
        if "n8n_app" in body:
            assert "CREATE ROLE" in body or "CREATE USER" in body, (
                f"{relative} uses n8n_app without creating it"
            )


def test_mounted_init_scripts_do_not_grant_in_the_default_database():
    """POSTGRES_DB is `postgres`. A grant meant for the n8n database must
    connect there first."""
    for entry in _compose_db_volumes():
        if INITDB_DIR not in entry:
            continue
        relative = entry.split(":")[0].lstrip("./")
        body = (REPO_ROOT / relative).read_text(encoding="utf-8")
        touches_n8n_objects = any(
            keyword in body for keyword in ("SCHEMA public", "DEFAULT PRIVILEGES")
        )
        if touches_n8n_objects:
            assert "\\connect n8n" in body, f"{relative} grants without connecting to n8n"


def test_the_hardening_script_exists_and_is_not_mounted_yet():
    """The role-separated bootstrap is correct but belongs after the Odoo-19
    handoff. It must exist, connect explicitly, and stay unmounted until then."""
    hardening = REPO_ROOT / "infrastructure/scripts/init-n8n-db-hardening.sql"
    assert hardening.exists()
    assert hardening.read_text(encoding="utf-8").lstrip().startswith("\\connect n8n")
    assert not any(
        "init-n8n-db-hardening.sql" in entry for entry in _compose_db_volumes()
    )
```

`COMPOSE_PATH`, `REPO_ROOT` and the `yaml` import are already used by that module; reuse them.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && PYTHONPATH=.deps python -m pytest ../infrastructure/tests/test_db_role_scripts.py -q`
Expected: `test_every_mounted_init_script_is_self_sufficient` FAILS — `init-n8n-db.sql` references
`n8n_app` and creates nothing; `test_the_hardening_script_exists_and_is_not_mounted_yet` FAILS on
the missing file.

- [ ] **Step 3: Move the hardening out of the mounted path**

Create `infrastructure/scripts/init-n8n-db-hardening.sql` containing the current content of
`init-n8n-db.sql`, prefixed with an explicit connect and a header:

```sql
-- Role-separated bootstrap for the n8n database.
--
-- NOT mounted yet. It presupposes the n8n_app role, which
-- infrastructure/scripts/init-db-roles.sh creates, and that script is mounted
-- only after the Odoo-19 handoff (see docs/superpowers/parallel/
-- 2026-07-23-program-status.md, decision on Task 13). Mounting this file
-- without init-db-roles.sh aborts the init of an empty volume.
--
-- The \connect is not optional: POSTGRES_DB is `postgres`, so without it every
-- statement below would grant in the wrong database.
\connect n8n

REVOKE ALL ON SCHEMA public FROM PUBLIC;
GRANT USAGE, CREATE ON SCHEMA public TO n8n_app;
ALTER SCHEMA public OWNER TO n8n_app;
ALTER DEFAULT PRIVILEGES FOR ROLE n8n_app GRANT ALL ON TABLES TO n8n_app;
ALTER DEFAULT PRIVILEGES FOR ROLE n8n_app GRANT ALL ON SEQUENCES TO n8n_app;
```

- [ ] **Step 4: Restore the working bootstrap**

Replace `infrastructure/scripts/init-n8n-db.sql` with:

```sql
-- Pre-handoff bootstrap. Self-sufficient by design: this file runs from
-- docker-entrypoint-initdb.d on an EMPTY cluster, so it may not presuppose any
-- role or database that another, unmounted script would have created.
--
-- The role-separated version lives in init-n8n-db-hardening.sql and is mounted
-- together with init-db-roles.sh after the Odoo-19 handoff. Until then the n8n
-- database is owned by the same superuser as Odoo; that is the status quo this
-- branch inherited, not a regression introduced here.
CREATE DATABASE n8n;
GRANT ALL PRIVILEGES ON DATABASE n8n TO :"owner";
```

`:"owner"` must resolve from `POSTGRES_USER`. If `docker-entrypoint-initdb.d` cannot supply a
psql variable in this position, use the literal `odoo` exactly as the pre-Task-13 file did and
add a comment saying the value is pinned to `POSTGRES_USER`'s default — do not invent a
substitution mechanism that has not been tested.

- [ ] **Step 5: Prove it against a real empty volume**

This step is not optional and cannot be stubbed. Findings #14 and #15 both exist because no script
in this area has ever met a real cluster.

```bash
docker compose -p pwr-freshinit down -v
docker compose -p pwr-freshinit up -d db
docker compose -p pwr-freshinit logs db | grep -i "error\|fatal" && echo "FAILED" || echo "clean init"
docker compose -p pwr-freshinit exec db psql -U odoo -l | grep n8n
docker compose -p pwr-freshinit down -v
```

Expected: no error or fatal in the log, and the `n8n` database is listed. Record the output in the
commit message.

- [ ] **Step 6: Run the tests to verify they pass**

Run: `cd backend && PYTHONPATH=.deps python -m pytest ../infrastructure/tests/test_db_role_scripts.py -q`
Expected: green.

- [ ] **Step 7: Commit**

```bash
git add infrastructure/scripts/init-n8n-db.sql infrastructure/scripts/init-n8n-db-hardening.sql infrastructure/tests/test_db_role_scripts.py docs/runbooks/n8n-db-role-migration.md
git commit -m "fix(db): restore a self-sufficient fresh init and park the role hardening"
```

---

### Task 2: Make the migration genuinely reversible and genuinely rehearsed

Finding #15 (Important) plus decision §3.6 of the program status file. `migrate-n8n-db-role.sh:204`
does not harden roles that already exist, checks compose with a global string grep rather than per
service, and demotes the legacy superuser immediately after a verifier that a stub can satisfy —
so the second operator the runbook requires has no window to intervene. Rollback restores `LOGIN`
automatically but leaves role flags, ACLs and compose identities to be repaired by hand.

**Files:**
- Modify: `infrastructure/scripts/migrate-n8n-db-role.sh`
- Modify: `infrastructure/scripts/verify-db-role-isolation.sh`
- Modify: `docs/runbooks/n8n-db-role-migration.md`
- Modify: `docker-compose.yml` (**post-handoff only**, Step 6)
- Test: `infrastructure/tests/test_db_role_scripts.py` (extend)

**Interfaces:**
- Consumes: existing modes of `migrate-n8n-db-role.sh` — `backup`, `apply`, `verify`, `rollback`, `assert-target` — and `psql_admin()`.
- Produces: `apply` no longer demotes. New mode `demote` requires `PWR_DEMOTE_APPROVED_BY` to be set and a prior successful `verify` recorded in the backup manifest. New helper `assert_role_attributes(role, expected)` compares by attribute, never by name.

- [ ] **Step 1: Write the failing tests**

Append to `infrastructure/tests/test_db_role_scripts.py`:

```python
def test_apply_does_not_demote(stub_psql):
    """The runbook promises a second operator a window between verification and
    demotion. Demoting inside apply removes that window.
    Regression cover for finding #15."""
    result = run_migration("apply", stub_psql=stub_psql)

    assert result.returncode == 0
    assert not any("NOSUPERUSER" in statement for statement in stub_psql.statements)


def test_demote_refuses_without_a_recorded_approval(stub_psql):
    result = run_migration("demote", stub_psql=stub_psql, env={})
    assert result.returncode != 0
    assert "PWR_DEMOTE_APPROVED_BY" in result.stderr


def test_demote_refuses_without_a_prior_successful_verify(stub_psql, tmp_manifest):
    tmp_manifest.write_text('{"verified": false}', encoding="utf-8")
    result = run_migration(
        "demote", stub_psql=stub_psql, env={"PWR_DEMOTE_APPROVED_BY": "second-operator"}
    )
    assert result.returncode != 0
    assert "verify" in result.stderr.lower()


def test_existing_roles_are_reset_to_the_exact_expected_attributes(stub_psql):
    """A role that already exists with the wrong flags is the dangerous case:
    the migration used to leave it exactly as it found it."""
    stub_psql.existing_roles = {
        "n8n_app": {"rolsuper": True, "rolcreatedb": True, "rolcanlogin": True}
    }
    run_migration("apply", stub_psql=stub_psql)

    altered = " ".join(stub_psql.statements)
    assert "NOSUPERUSER" in altered
    assert "NOCREATEDB" in altered


def test_unknown_role_memberships_are_revoked(stub_psql):
    stub_psql.existing_memberships = {"n8n_app": ["pg_read_server_files"]}
    run_migration("apply", stub_psql=stub_psql)
    assert any("REVOKE" in statement for statement in stub_psql.statements)


def test_compose_is_checked_per_service_not_by_global_grep():
    """A global grep passes when the right string appears anywhere in the file,
    including in a comment or in an unrelated service."""
    document = yaml.safe_load(COMPOSE_PATH.read_text(encoding="utf-8"))
    n8n_env = document["services"]["n8n"].get("environment", {})
    assert "n8n_app" in json.dumps(n8n_env), "the n8n service itself must carry the app role"
    odoo_env = document["services"]["odoo"].get("environment", {})
    assert "n8n_app" not in json.dumps(odoo_env), "odoo must not use the n8n role"


def test_rollback_restores_role_flags_and_acls(stub_psql, tmp_manifest):
    run_migration("rollback", stub_psql=stub_psql)

    statements = " ".join(stub_psql.statements)
    assert "SUPERUSER" in statements
    assert "LOGIN" in statements
    assert "GRANT" in statements, "ACLs must be restored, not left to a human"


def test_no_password_is_ever_passed_in_argv(stub_psql):
    run_migration("apply", stub_psql=stub_psql)
    for invocation in stub_psql.argv_history:
        assert not any("PASSWORD" in argument.upper() for argument in invocation)
```

`stub_psql`, `run_migration` and `tmp_manifest` extend the stubbed-subprocess harness that module
already has. `stub_psql` needs two new attributes — `existing_roles` and `existing_memberships` —
so the "role already exists" branches are reachable at all; today they are not.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && PYTHONPATH=.deps python -m pytest ../infrastructure/tests/test_db_role_scripts.py -q`
Expected: `test_apply_does_not_demote` fails (apply demotes), the two `demote` tests fail (no such
mode), and the attribute-reset tests fail (existing roles are left alone).

- [ ] **Step 3: Split apply from demote**

Restructure `migrate-n8n-db-role.sh` so the operator sequence is:

```
backup -> migrate -> start-apps -> verify -> stop
                                        |
                                        v  second approval required
                                     demote
```

`apply` performs everything up to and including `verify` and then stops. `demote` is a separate
mode that refuses unless **both** hold: `PWR_DEMOTE_APPROVED_BY` is set and non-empty, and the
backup manifest records a successful `verify` from this run. Write the verify result into the
manifest; do not infer it from an exit code the operator no longer has.

```bash
# Die Demotion ist der einzige irreversible Schritt dieser Migration. Sie
# lief bisher unmittelbar nach einem Verifier, den ein Stub befriedigen kann --
# der zweite Operator, den das Runbook verlangt, hatte also gar kein Fenster,
# in dem er haette eingreifen koennen. Deshalb ist sie jetzt ein eigener Modus
# mit eigener Freigabe.
```

- [ ] **Step 4: Harden roles by attribute, and revoke unknown memberships**

Add `assert_role_attributes(role, expected)` and call it for every app role whether or not the
role already existed. Compare `rolsuper`, `rolcreatedb`, `rolcreaterole`, `rolcanlogin`,
`rolbypassrls` and `rolreplication` against the expected set and `ALTER ROLE` any that differ.
Enumerate the role's current memberships and revoke everything not on the expected list — an
allowlist, not a denylist.

Identify the admin role by **attribute** (`rolsuper`), never by name; that was already fixed once
here and must not regress.

- [ ] **Step 5: Check compose per service, and verify through real connections**

Replace the global grep with a per-service check: parse `docker-compose.yml`, read the `n8n`
service's environment, and assert it carries `n8n_app`; assert the `odoo` service does not.

In `verify-db-role-isolation.sh`, add a `SELECT current_user` executed **through each application's
own connection settings**, not through the admin connection. A verifier that only the admin
exercises proves nothing about what the apps actually connect as.

- [ ] **Step 6: Make rollback complete**

Rollback must restore role flags and ACLs from the backup automatically, and must start the
applications with a legacy compose override so the old identities are actually in effect. A
rollback that leaves a human to repair ACLs by hand is not a rollback.

- [ ] **Step 7: Run the tests to verify they pass**

Run: `cd backend && PYTHONPATH=.deps python -m pytest ../infrastructure/tests/test_db_role_scripts.py -q`
Expected: green.

Run `bash -n` on every modified script. Expected: silent.

- [ ] **Step 8: Rehearse against a real disposable cluster**

**This is the step that closes Task 13.** Everything above still rests on stubs. Per decision §3.6
of the program status file, Task 13 stays "statically complete, live acceptance open" until this
run succeeds and its output is recorded in `docs/runbooks/n8n-db-role-migration.md`.

```bash
# 1. Clone the volume into a throwaway project
bash infrastructure/scripts/clone-postgres-volume.sh --target pwr-rehearsal
docker compose -p pwr-rehearsal up -d db

# 2. Full sequence
bash infrastructure/scripts/migrate-n8n-db-role.sh backup   --project pwr-rehearsal
bash infrastructure/scripts/migrate-n8n-db-role.sh apply    --project pwr-rehearsal
bash infrastructure/scripts/verify-db-role-isolation.sh     --project pwr-rehearsal
PWR_DEMOTE_APPROVED_BY="rehearsal" \
  bash infrastructure/scripts/migrate-n8n-db-role.sh demote --project pwr-rehearsal

# 3. Prove isolation actually holds after demotion
docker compose -p pwr-rehearsal exec db psql -U n8n_app -d n8n -c "SELECT current_user"
docker compose -p pwr-rehearsal exec db psql -U n8n_app -d postgres -c "SELECT 1" && echo "LEAK" || echo "isolated"

# 4. Roll all the way back and prove the apps still run
bash infrastructure/scripts/migrate-n8n-db-role.sh rollback --project pwr-rehearsal
docker compose -p pwr-rehearsal up -d
docker compose -p pwr-rehearsal ps

# 5. Destroy the rehearsal
docker compose -p pwr-rehearsal down -v
```

Every command's outcome goes into the runbook's "Verification limits" section, which is then
rewritten from "no script has run against a real cluster" to what was actually proven, including
what still was not.

- [ ] **Step 9: Wire the role-separated bootstrap — POST-HANDOFF ONLY**

Do **not** perform this step before the Odoo-19 handoff tag `wave1-odoo19-handoff` exists. When it
does, change the `db` service in `docker-compose.yml` atomically, in one commit:

- `POSTGRES_USER: pwr_db_admin`
- mount `./infrastructure/scripts/init-db-roles.sh` into `/docker-entrypoint-initdb.d/`
- mount `./infrastructure/scripts/init-n8n-db-hardening.sql` into `/docker-entrypoint-initdb.d/`
  with a numeric prefix that orders it **after** the role script
- set all three `*_PASSWORD_FILE` variables
- remove the pre-handoff `init-n8n-db.sql` mount
- re-run Task 1 Step 5's empty-volume probe against the new configuration

Splitting this across commits leaves a window in which an empty volume is broken again.

- [ ] **Step 10: Commit**

```bash
git add infrastructure/scripts/migrate-n8n-db-role.sh infrastructure/scripts/verify-db-role-isolation.sh infrastructure/tests/test_db_role_scripts.py docs/runbooks/n8n-db-role-migration.md
git commit -m "fix(db): separate demotion from apply and make rollback complete"
```

---

## Lane exit gate

- [ ] `cd backend && PYTHONPATH=.deps python -m pytest ../infrastructure/tests/ -q` — green
- [ ] `bash -n` passes on every modified script
- [ ] The empty-volume probe from Task 1 Step 5 ran and its output is in the commit message
- [ ] The live rehearsal from Task 2 Step 8 ran end to end against a disposable cluster, and the runbook's "Verification limits" section reflects what was actually proven
- [ ] Step 9 is **not** done, and the reason (no `wave1-odoo19-handoff` tag) is recorded
- [ ] Adversarial review: `codex exec --sandbox read-only "<diff brief>"`, focused on: can demotion still happen without a second approval; is any identifier interpolated unquoted; is any password reachable via `ps`; does rollback leave anything for a human; can an empty volume still abort
- [ ] Update the debt register in `docs/superpowers/parallel/2026-07-23-program-status.md` — mark #14 closed and #15 closed, and change Task 13's state from "statically complete, live acceptance open" to "complete" only if Step 8 succeeded
