#!/bin/bash
# Backup-verified migration of the existing shared
# superuser database role onto dedicated non-superuser application
# roles (odoo_app, n8n_app), for an already-populated production
# volume (Task 13). See docs/runbooks/n8n-db-role-migration.md for the
# full operator sequence.
#
# Usage:
#   migrate-n8n-db-role.sh backup   "$BACKUP_DIR"
#   migrate-n8n-db-role.sh apply    "$BACKUP_DIR"
#   migrate-n8n-db-role.sh verify
#   migrate-n8n-db-role.sh rollback "$BACKUP_DIR"  # refuses; use offline restore
#
# Required environment (every mode; the tool consumes the final
# Odoo-19 database name unconditionally and fails closed if it is
# unset, rather than guessing it):
#   ODOO_DB_NAME
#     - final Odoo-19 production database name
#   ODOO_LAGER2_DB_NAME - optional second warehouse, migrated before legacy demotion
#   PWR_DB_ADMIN_PASSWORD_FILE, ODOO_DB_PASSWORD_FILE, N8N_DB_PASSWORD_FILE
#     - password files for the new roles, mode 0400 or 0600. apply and
#       verify need all three; rollback fails without changing anything.
#   LEGACY_DB_SUPERUSER
#     - required only if the existing shared role is not named "odoo";
#       must not be "postgres" or "pwr_db_admin"
#
# This script uses `umask 077`, refuses a world-readable backup
# directory, redacts connection URIs in its own logs, and never
# invokes `set -x`. All identifier substitution into SQL (role and
# database names) goes through psql's quoted-identifier (:"var") or
# format('%I', ...) forms, never bare/unquoted interpolation.
set -euo pipefail
umask 077

log() {
    printf '[migrate-n8n-db-role] %s\n' "$1" >&2
}

fail() {
    log "ERROR: $1"
    exit 1
}

require_password_file() {
    local var_name="$1"
    local path="${!var_name:-}"
    [ -n "$path" ] || fail "$var_name is required and must point to a password file"
    [ -f "$path" ] || fail "$var_name points to a missing file: $path"
    local mode
    mode="$(stat -c '%a' "$path" 2>/dev/null || stat -f '%Lp' "$path")"
    if [ "$mode" != "400" ] && [ "$mode" != "600" ]; then
        fail "$var_name ($path) must be mode 0400 or 0600, found $mode"
    fi
}

require_backup_dir_not_world_readable() {
    local dir="$1"
    [ -d "$dir" ] || fail "backup directory does not exist: $dir"
    local mode
    mode="$(stat -c '%a' "$dir" 2>/dev/null || stat -f '%Lp' "$dir")"
    [ "$mode" = "700" ] || fail "backup directory $dir must be mode 0700 (found $mode)"
}

legacy_role() {
    if [ -n "${LEGACY_DB_SUPERUSER:-}" ]; then
        if [ "$LEGACY_DB_SUPERUSER" = "postgres" ] || [ "$LEGACY_DB_SUPERUSER" = "pwr_db_admin" ]; then
            fail "LEGACY_DB_SUPERUSER must not be postgres or pwr_db_admin"
        fi
        echo "$LEGACY_DB_SUPERUSER"
    else
        echo "odoo"
    fi
}

require_odoo_db_name() {
    [ -n "${ODOO_DB_NAME:-}" ] || fail "ODOO_DB_NAME is required (final Odoo-19 production database name); refusing to guess it"
}

# Connection to the pre-migration, still-privileged legacy admin. Only
# used to bootstrap pwr_db_admin itself (ensure_pwr_db_admin) and for
# the read-only backup phase, which runs before pwr_db_admin exists.
# Connects as the resolved legacy role (LEGACY_DB_SUPERUSER, default
# "odoo"), never as an unrelated $POSTGRES_USER value: if the legacy
# superuser isn't literally named "odoo", $POSTGRES_USER would silently
# target the wrong account and the whole migration would run against
# the wrong role.
psql_admin() {
    psql -v ON_ERROR_STOP=1 --username "$(legacy_role)" "$@"
}

# Connection to the dedicated bootstrap superuser. Used for every
# privileged statement once pwr_db_admin has been ensured to exist,
# so the migration never depends on an arbitrary $POSTGRES_USER value
# beyond that one bootstrap step.
psql_pwr_admin() {
    require_password_file PWR_DB_ADMIN_PASSWORD_FILE
    PGPASSWORD="$(cat "$PWR_DB_ADMIN_PASSWORD_FILE")" \
        psql -v ON_ERROR_STOP=1 --username pwr_db_admin "$@"
}

# Creates the pwr_db_admin bootstrap superuser from
# PWR_DB_ADMIN_PASSWORD_FILE if it does not already exist (idempotent),
# using the pre-migration legacy admin connection, then verifies it
# really exists as a superuser. Fails closed if verification fails.
ensure_pwr_db_admin() {
    require_password_file PWR_DB_ADMIN_PASSWORD_FILE
    local pwr_password
    pwr_password="$(cat "$PWR_DB_ADMIN_PASSWORD_FILE")"

    log "Ensuring bootstrap role pwr_db_admin exists"
    # The password reaches psql through the environment of this single
    # invocation (\getenv), never as a `-v name=value` command-line
    # argument, which any local user could read from the process list.
    # (A bare `VAR=val cmd` prefix applies to shell functions too, not
    # just external binaries, so no separate `env` call is needed here.)
    PWR_ADMIN_PASSWORD="$pwr_password" psql_admin -d postgres <<'SQL'
\getenv pwr_password PWR_ADMIN_PASSWORD
SELECT format(
  'CREATE ROLE pwr_db_admin SUPERUSER LOGIN PASSWORD %L',
  :'pwr_password'
)
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'pwr_db_admin')
\gexec
SQL

    local is_super
    is_super="$(psql_admin -X -At -d postgres -c \
        "SELECT rolsuper FROM pg_roles WHERE rolname = 'pwr_db_admin'")"
    [ "$is_super" = "t" ] || fail "pwr_db_admin does not exist as a superuser bootstrap role after ensure_pwr_db_admin"
}

cmd_backup() {
    local backup_dir="${1:?BACKUP_DIR required}"
    install -d -m 0700 "$backup_dir"
    require_backup_dir_not_world_readable "$backup_dir"

    local legacy
    legacy="$(legacy_role)"

    log "Recording legacy role flags for $legacy"
    psql_admin -d postgres -At -v "legacy=$legacy" \
        > "$backup_dir/legacy-role-flags-before.tsv" <<'SQL'
SELECT rolname, rolsuper, rolcreatedb, rolcreaterole, rolcanlogin FROM pg_roles WHERE rolname = :'legacy';
SQL

    log "Dumping roles (no passwords redacted in output, filesystem access required)"
    pg_dumpall --roles-only --username "$legacy" > "$backup_dir/roles-before.sql"

    log "Dumping n8n database"
    pg_dump --format=custom --username "$legacy" --file "$backup_dir/n8n-before.dump" n8n

    log "Dumping the Odoo databases before ownership changes"
    pg_dump --format=custom --username "$legacy" --file "$backup_dir/odoo-before.dump" "$ODOO_DB_NAME"
    local extra_dumps=()
    if [ -n "${ODOO_LAGER2_DB_NAME:-}" ] && [ "$ODOO_LAGER2_DB_NAME" != "$ODOO_DB_NAME" ]; then
        pg_dump --format=custom --username "$legacy" --file "$backup_dir/odoo-lager2-before.dump" "$ODOO_LAGER2_DB_NAME"
        extra_dumps+=(odoo-lager2-before.dump)
    fi

    log "Recording database and schema ACLs"
    psql_admin -d postgres -At -c \
        "SELECT datname, datacl FROM pg_database ORDER BY datname" \
        > "$backup_dir/database-acl-before.tsv"
    psql_admin -d n8n -At -c \
        "SELECT nspname, nspacl FROM pg_namespace ORDER BY nspname" \
        > "$backup_dir/n8n-schema-acl-before.tsv"

    (cd "$backup_dir" && sha256sum \
        legacy-role-flags-before.tsv \
        roles-before.sql \
        n8n-before.dump \
        odoo-before.dump \
        "${extra_dumps[@]}" \
        database-acl-before.tsv \
        n8n-schema-acl-before.tsv \
        > manifest.sha256)
    chmod 0600 "$backup_dir"/*.sql "$backup_dir"/*.dump "$backup_dir"/*.tsv "$backup_dir/manifest.sha256"

    log "Backup complete in $backup_dir"
}

verify_manifest() {
    local backup_dir="$1"
    [ -f "$backup_dir/manifest.sha256" ] || fail "manifest.sha256 missing in $backup_dir"
    (cd "$backup_dir" && sha256sum -c manifest.sha256 >/dev/null) \
        || fail "manifest.sha256 verification failed in $backup_dir"
}

transfer_public_objects() {
    local database="$1" app_role="$2" legacy="$3"
    # Docker's original POSTGRES_USER owns initdb's system objects too.
    # REASSIGN OWNED refuses that role; on ordinary roles it also transfers
    # shared databases/tablespaces. Move only this application's public objects.
    psql_pwr_admin -d "$database" -v "legacy=$legacy" -v "app_role=$app_role" <<'SQL'
SELECT format('ALTER %s %I.%I OWNER TO %I',
  CASE c.relkind WHEN 'S' THEN 'SEQUENCE' WHEN 'v' THEN 'VIEW'
    WHEN 'm' THEN 'MATERIALIZED VIEW' WHEN 'f' THEN 'FOREIGN TABLE' ELSE 'TABLE' END,
  n.nspname, c.relname, :'app_role')
FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = 'public' AND c.relowner = (SELECT oid FROM pg_roles WHERE rolname = :'legacy')
  AND c.relkind IN ('r', 'p', 'S', 'v', 'm', 'f')
  AND NOT EXISTS (SELECT 1 FROM pg_depend d WHERE d.classid = 'pg_class'::regclass
    AND d.objid = c.oid AND d.deptype = 'e')
ORDER BY c.relkind = 'S', c.oid
\gexec

SELECT format('ALTER ROUTINE %I.%I(%s) OWNER TO %I', n.nspname, p.proname,
  pg_get_function_identity_arguments(p.oid), :'app_role')
FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
WHERE n.nspname = 'public' AND p.proowner = (SELECT oid FROM pg_roles WHERE rolname = :'legacy')
  AND NOT EXISTS (SELECT 1 FROM pg_depend d WHERE d.classid = 'pg_proc'::regclass
    AND d.objid = p.oid AND d.deptype = 'e')
\gexec

SELECT format('ALTER TYPE %I.%I OWNER TO %I', n.nspname, t.typname, :'app_role')
FROM pg_type t JOIN pg_namespace n ON n.oid = t.typnamespace
LEFT JOIN pg_class c ON c.oid = t.typrelid
WHERE n.nspname = 'public' AND t.typowner = (SELECT oid FROM pg_roles WHERE rolname = :'legacy')
  AND (t.typtype IN ('d', 'e', 'r') OR c.relkind = 'c')
  AND NOT EXISTS (SELECT 1 FROM pg_depend d WHERE d.classid = 'pg_type'::regclass
    AND d.objid = t.oid AND d.deptype = 'e')
\gexec
SQL
}

cmd_apply() {
    local backup_dir="${1:?BACKUP_DIR required}"
    require_backup_dir_not_world_readable "$backup_dir"
    verify_manifest "$backup_dir"
    require_password_file PWR_DB_ADMIN_PASSWORD_FILE
    require_password_file ODOO_DB_PASSWORD_FILE
    require_password_file N8N_DB_PASSWORD_FILE
    [ -f "$backup_dir/odoo-before.dump" ] || fail "Odoo backup missing; run backup again before apply"
    if [ -n "${ODOO_LAGER2_DB_NAME:-}" ] && [ "$ODOO_LAGER2_DB_NAME" != "$ODOO_DB_NAME" ]; then
        [ -f "$backup_dir/odoo-lager2-before.dump" ] || fail "second warehouse backup missing; run backup again before apply"
    fi

    local legacy
    legacy="$(legacy_role)"

    local services=(odoo n8n)
    local odoo_databases=("$ODOO_DB_NAME")
    if [ -n "${ODOO_LAGER2_DB_NAME:-}" ] && [ "$ODOO_LAGER2_DB_NAME" != "$ODOO_DB_NAME" ]; then
        services+=(odoo-lager-2)
        odoo_databases+=("$ODOO_LAGER2_DB_NAME")
    fi
    local database unsupported_schemas
    for database in n8n "${odoo_databases[@]}"; do
        unsupported_schemas="$(psql_admin -X -At -d "$database" -c \
            "SELECT nspname FROM pg_namespace WHERE nspname NOT IN ('public', 'information_schema') AND nspname !~ '^pg_' ORDER BY nspname")"
        [ -z "$unsupported_schemas" ] || fail "database $database has additional schemas; review their ownership migration before apply: $unsupported_schemas"
    done

    log "Stopping application writers before role migration"
    docker compose stop backend "${services[@]}"
    ensure_pwr_db_admin

    local odoo_password n8n_password
    odoo_password="$(cat "$ODOO_DB_PASSWORD_FILE")"
    n8n_password="$(cat "$N8N_DB_PASSWORD_FILE")"

    log "Creating odoo_app/n8n_app roles if absent (via pwr_db_admin)"
    # Passwords reach psql through this single invocation's environment
    # (\getenv), never as `-v name=value` argv, which is readable by any
    # local user via the process list.
    ODOO_APP_PASSWORD="$odoo_password" N8N_APP_PASSWORD="$n8n_password" \
        psql_pwr_admin -d postgres <<'SQL'
\getenv odoo_password ODOO_APP_PASSWORD
\getenv n8n_password N8N_APP_PASSWORD

SELECT format(
  'CREATE ROLE odoo_app LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE PASSWORD %L',
  :'odoo_password'
)
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'odoo_app')
\gexec

SELECT format(
  'CREATE ROLE n8n_app LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE PASSWORD %L',
  :'n8n_password'
)
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'n8n_app')
\gexec
SQL

    log "Reassigning ownership in n8n from $legacy to n8n_app"
    transfer_public_objects n8n n8n_app "$legacy"
    psql_pwr_admin -d n8n -v "legacy=$legacy" <<'SQL'
ALTER DATABASE n8n OWNER TO n8n_app;
REVOKE ALL ON SCHEMA public FROM PUBLIC;
GRANT USAGE, CREATE ON SCHEMA public TO n8n_app;
ALTER SCHEMA public OWNER TO n8n_app;
GRANT ALL ON ALL TABLES IN SCHEMA public TO n8n_app;
GRANT ALL ON ALL SEQUENCES IN SCHEMA public TO n8n_app;
ALTER DEFAULT PRIVILEGES FOR ROLE n8n_app GRANT ALL ON TABLES TO n8n_app;
ALTER DEFAULT PRIVILEGES FOR ROLE n8n_app GRANT ALL ON SEQUENCES TO n8n_app;
SQL

    local odoo_database
    for odoo_database in "${odoo_databases[@]}"; do
    log "Reassigning ownership in $odoo_database from $legacy to odoo_app"
    transfer_public_objects "$odoo_database" odoo_app "$legacy"
    psql_pwr_admin -d "$odoo_database" -v "legacy=$legacy" -v "odoo_db=$odoo_database" <<'SQL'
ALTER DATABASE :"odoo_db" OWNER TO odoo_app;
REVOKE ALL ON SCHEMA public FROM PUBLIC;
GRANT USAGE, CREATE ON SCHEMA public TO odoo_app;
ALTER SCHEMA public OWNER TO odoo_app;
GRANT ALL ON ALL TABLES IN SCHEMA public TO odoo_app;
GRANT ALL ON ALL SEQUENCES IN SCHEMA public TO odoo_app;
ALTER DEFAULT PRIVILEGES FOR ROLE odoo_app GRANT ALL ON TABLES TO odoo_app;
ALTER DEFAULT PRIVILEGES FOR ROLE odoo_app GRANT ALL ON SEQUENCES TO odoo_app;
SQL

    log "Enforcing per-database CONNECT isolation for n8n and $odoo_database"
    psql_pwr_admin -d postgres -v "odoo_db=$odoo_database" <<'SQL'
REVOKE CONNECT, TEMPORARY ON DATABASE n8n FROM PUBLIC;
GRANT CONNECT, TEMPORARY ON DATABASE n8n TO n8n_app;

SELECT format('REVOKE CONNECT, TEMPORARY ON DATABASE %I FROM PUBLIC', :'odoo_db') \gexec
SELECT format('GRANT CONNECT, TEMPORARY ON DATABASE %I TO odoo_app', :'odoo_db') \gexec
SQL
    done

    log "Checking resolved Compose config references odoo_app and n8n_app"
    local resolved_config
    resolved_config="$(docker compose config)"
    grep -q "odoo_app" <<< "$resolved_config" || fail "resolved Compose config does not reference odoo_app"
    grep -q "n8n_app" <<< "$resolved_config" || fail "resolved Compose config does not reference n8n_app"

    log "Starting Odoo and n8n with new role secret files"
    docker compose up -d "${services[@]}"

    log "Running isolation verifier"
    # Force the verifier's bootstrap-admin check onto pwr_db_admin itself,
    # regardless of whatever POSTGRES_USER happens to be set to in this
    # shell (the pre-migration legacy role, historically "odoo"), and
    # supply its password via PGPASSWORD so the check actually
    # authenticates under password auth instead of failing to connect.
    POSTGRES_USER=pwr_db_admin PGPASSWORD="$(cat "$PWR_DB_ADMIN_PASSWORD_FILE")" \
        bash "$(dirname "${BASH_SOURCE[0]}")/verify-db-role-isolation.sh"

    log "Disabling the legacy login $legacy"
    psql_pwr_admin -d postgres -v "legacy=$legacy" <<'SQL'
-- PostgreSQL requires initdb's role (OID 10) to remain a superuser.
-- It keeps system ownership but must no longer be an application login.
SELECT format('ALTER ROLE %I %s NOLOGIN', :'legacy',
  CASE WHEN oid = 10 THEN '' ELSE 'NOSUPERUSER NOCREATEDB NOCREATEROLE' END)
FROM pg_roles WHERE rolname = :'legacy'
\gexec
SQL

    docker compose up -d backend

    log "Apply complete: legacy login disabled, odoo_app/n8n_app own their databases; the initdb role retains its required system privileges"
}

cmd_verify() {
    require_password_file PWR_DB_ADMIN_PASSWORD_FILE
    POSTGRES_USER=pwr_db_admin PGPASSWORD="$(cat "$PWR_DB_ADMIN_PASSWORD_FILE")" \
        bash "$(dirname "${BASH_SOURCE[0]}")/verify-db-role-isolation.sh"
}

cmd_rollback() {
    fail "automatic rollback is disabled: restore the verified offline PostgreSQL clone and previous Compose/Odoo configuration; see docs/runbooks/n8n-db-role-migration.md"
}

main() {
    local mode="${1:-}"
    case "$mode" in
        backup|apply|verify|rollback)
            ;;
        *)
            echo "Usage: $0 {backup|apply|verify|rollback} [BACKUP_DIR]" >&2
            exit 1
            ;;
    esac

    # ODOO_DB_NAME is consumed by this tool as a whole (Interfaces:
    # "Consumes: final Odoo-19 database name"), not just by apply, so
    # it is enforced here, before mode dispatch, for every mode.
    require_odoo_db_name

    shift || true
    case "$mode" in
        "backup")
            cmd_backup "$@"
            ;;
        "apply")
            cmd_apply "$@"
            ;;
        "verify")
            cmd_verify "$@"
            ;;
        "rollback")
            cmd_rollback "$@"
            ;;
    esac
}

main "$@"
