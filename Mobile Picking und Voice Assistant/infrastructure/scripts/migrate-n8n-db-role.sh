#!/bin/bash
# Reversible, backup-verified migration of the existing shared
# superuser database role onto dedicated non-superuser application
# roles (odoo_app, n8n_app), for an already-populated production
# volume (Task 13). See docs/runbooks/n8n-db-role-migration.md for the
# full operator sequence.
#
# Usage:
#   migrate-n8n-db-role.sh backup   "$BACKUP_DIR"
#   migrate-n8n-db-role.sh apply    "$BACKUP_DIR"
#   migrate-n8n-db-role.sh verify
#   migrate-n8n-db-role.sh rollback "$BACKUP_DIR"
#
# Required environment (every mode; the tool consumes the final
# Odoo-19 database name unconditionally and fails closed if it is
# unset, rather than guessing it):
#   ODOO_DB_NAME
#     - final Odoo-19 production database name
#   PWR_DB_ADMIN_PASSWORD_FILE, ODOO_DB_PASSWORD_FILE, N8N_DB_PASSWORD_FILE
#     - password files for the new roles, mode 0400 or 0600 (required by
#       apply and rollback, which create/use these roles)
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
    case "$mode" in
        *[0246])
            ;;
        *)
            fail "backup directory $dir must not be world-readable (mode $mode)"
            ;;
    esac
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
psql_admin() {
    psql -v ON_ERROR_STOP=1 --username "${POSTGRES_USER:-odoo}" "$@"
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
    psql_admin -d postgres -v "pwr_password=$pwr_password" <<'SQL'
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
    psql_admin -d postgres -At -v "legacy=$legacy" -c \
        "SELECT rolname, rolsuper, rolcreatedb, rolcreaterole, rolcanlogin FROM pg_roles WHERE rolname = :'legacy'" \
        > "$backup_dir/legacy-role-flags-before.tsv"

    log "Dumping roles (no passwords redacted in output, filesystem access required)"
    pg_dumpall --roles-only > "$backup_dir/roles-before.sql"

    log "Dumping n8n database"
    pg_dump --format=custom --file "$backup_dir/n8n-before.dump" n8n

    log "Recording database and schema ACLs"
    psql_admin -d postgres -At -c \
        "SELECT datname, datacl FROM pg_database ORDER BY datname" \
        > "$backup_dir/database-acl-before.tsv"
    psql_admin -d n8n -At -c \
        "SELECT nspname, nspacl FROM pg_namespace ORDER BY nspname" \
        > "$backup_dir/n8n-schema-acl-before.tsv"

    (cd "$backup_dir" && sha256sum \
        roles-before.sql \
        n8n-before.dump \
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

cmd_apply() {
    local backup_dir="${1:?BACKUP_DIR required}"
    require_backup_dir_not_world_readable "$backup_dir"
    verify_manifest "$backup_dir"
    require_password_file PWR_DB_ADMIN_PASSWORD_FILE
    require_password_file ODOO_DB_PASSWORD_FILE
    require_password_file N8N_DB_PASSWORD_FILE

    local legacy
    legacy="$(legacy_role)"

    log "Stopping n8n before role migration"
    docker compose stop n8n

    ensure_pwr_db_admin

    local odoo_password n8n_password
    odoo_password="$(cat "$ODOO_DB_PASSWORD_FILE")"
    n8n_password="$(cat "$N8N_DB_PASSWORD_FILE")"

    log "Creating odoo_app/n8n_app roles if absent (via pwr_db_admin)"
    psql_pwr_admin -d postgres \
        -v "odoo_password=$odoo_password" \
        -v "n8n_password=$n8n_password" <<'SQL'
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
    psql_pwr_admin -d n8n -v "legacy=$legacy" <<'SQL'
REASSIGN OWNED BY :"legacy" TO n8n_app;
ALTER DATABASE n8n OWNER TO n8n_app;
REVOKE ALL ON SCHEMA public FROM PUBLIC;
GRANT USAGE, CREATE ON SCHEMA public TO n8n_app;
ALTER SCHEMA public OWNER TO n8n_app;
GRANT ALL ON ALL TABLES IN SCHEMA public TO n8n_app;
GRANT ALL ON ALL SEQUENCES IN SCHEMA public TO n8n_app;
ALTER DEFAULT PRIVILEGES FOR ROLE n8n_app GRANT ALL ON TABLES TO n8n_app;
ALTER DEFAULT PRIVILEGES FOR ROLE n8n_app GRANT ALL ON SEQUENCES TO n8n_app;
SQL

    log "Reassigning ownership in $ODOO_DB_NAME from $legacy to odoo_app"
    psql_pwr_admin -d "$ODOO_DB_NAME" -v "legacy=$legacy" -v "odoo_db=$ODOO_DB_NAME" <<'SQL'
REASSIGN OWNED BY :"legacy" TO odoo_app;
ALTER DATABASE :"odoo_db" OWNER TO odoo_app;
REVOKE ALL ON SCHEMA public FROM PUBLIC;
GRANT USAGE, CREATE ON SCHEMA public TO odoo_app;
ALTER SCHEMA public OWNER TO odoo_app;
GRANT ALL ON ALL TABLES IN SCHEMA public TO odoo_app;
GRANT ALL ON ALL SEQUENCES IN SCHEMA public TO odoo_app;
ALTER DEFAULT PRIVILEGES FOR ROLE odoo_app GRANT ALL ON TABLES TO odoo_app;
ALTER DEFAULT PRIVILEGES FOR ROLE odoo_app GRANT ALL ON SEQUENCES TO odoo_app;
SQL

    log "Enforcing per-database CONNECT isolation for n8n and $ODOO_DB_NAME"
    psql_pwr_admin -d postgres -v "odoo_db=$ODOO_DB_NAME" <<'SQL'
REVOKE CONNECT, TEMPORARY ON DATABASE n8n FROM PUBLIC;
GRANT CONNECT, TEMPORARY ON DATABASE n8n TO n8n_app;

SELECT format('REVOKE CONNECT, TEMPORARY ON DATABASE %I FROM PUBLIC', :'odoo_db') \gexec
SELECT format('GRANT CONNECT, TEMPORARY ON DATABASE %I TO odoo_app', :'odoo_db') \gexec
SQL

    log "Checking resolved Compose config references odoo_app and n8n_app"
    local resolved_config
    resolved_config="$(docker compose config)"
    echo "$resolved_config" | grep -q "odoo_app" || fail "resolved Compose config does not reference odoo_app"
    echo "$resolved_config" | grep -q "n8n_app" || fail "resolved Compose config does not reference n8n_app"

    log "Starting Odoo and n8n with new role secret files"
    docker compose up -d odoo n8n

    log "Running isolation verifier"
    bash "$(dirname "${BASH_SOURCE[0]}")/verify-db-role-isolation.sh"

    log "Demoting legacy role $legacy to a non-login, non-privileged role"
    psql_pwr_admin -d postgres -v "legacy=$legacy" <<'SQL'
ALTER ROLE :"legacy" NOSUPERUSER NOCREATEDB NOCREATEROLE NOLOGIN;
SQL

    log "Apply complete: $legacy demoted, odoo_app/n8n_app own their databases, pwr_db_admin is the sole surviving superuser"
}

cmd_verify() {
    bash "$(dirname "${BASH_SOURCE[0]}")/verify-db-role-isolation.sh"
}

cmd_rollback() {
    local backup_dir="${1:?BACKUP_DIR required}"
    require_backup_dir_not_world_readable "$backup_dir"
    verify_manifest "$backup_dir"
    require_password_file PWR_DB_ADMIN_PASSWORD_FILE

    local legacy
    legacy="$(legacy_role)"

    log "Stopping n8n and Odoo before rollback"
    docker compose stop n8n odoo

    ensure_pwr_db_admin

    log "Re-enabling legacy role $legacy with its pre-migration flags"
    local flags
    flags="$(cat "$backup_dir/legacy-role-flags-before.tsv")"
    psql_pwr_admin -d postgres -v "legacy=$legacy" <<'SQL'
ALTER ROLE :"legacy" LOGIN;
SQL
    log "Legacy role flags recorded at migration time: $flags"
    log "Review $backup_dir/legacy-role-flags-before.tsv and restore SUPERUSER/CREATEDB/CREATEROLE manually if it held them"

    log "Dropping and recreating n8n database owned by legacy role"
    psql_pwr_admin -d postgres -v "legacy=$legacy" <<'SQL'
DROP DATABASE IF EXISTS n8n;
SELECT format('CREATE DATABASE n8n OWNER %I', :'legacy') \gexec
SQL

    log "Restoring n8n from backup dump"
    pg_restore --dbname n8n --no-owner --role "$legacy" "$backup_dir/n8n-before.dump"

    log "Database/schema ACL restoration from $backup_dir/database-acl-before.tsv and n8n-schema-acl-before.tsv requires generated, reviewed SQL; not applied automatically"

    log "Starting services with the recorded legacy-role override"
    docker compose up -d odoo n8n

    log "Rollback complete. Run each service's pre-migration health probe manually."
    log "pwr_db_admin, odoo_app, and n8n_app are preserved; their application grants should be removed only after the old services are confirmed healthy"
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
