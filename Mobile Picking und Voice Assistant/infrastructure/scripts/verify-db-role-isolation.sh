#!/bin/bash
# Isolation probe for dedicated PostgreSQL application roles (Task 13).
#
# Runs six checks, three positive and three negative. Any negative
# check that unexpectedly succeeds (i.e. a connection that should fail
# does not fail) is treated as a hard failure. Connection URIs are
# redacted from all log output, and this script never invokes `set -x`
# so passwords are never traced.
#
# Required environment:
#   PGHOST, PGPORT (or docker exec context), POSTGRES_USER (bootstrap admin)
#   ODOO_DB_NAME                - final Odoo-19 production database name
#   ODOO_DB_PASSWORD_FILE       - password file for odoo_app, mode 0400/0600
#   N8N_DB_PASSWORD_FILE        - password file for n8n_app, mode 0400/0600
set -euo pipefail

export PGCONNECT_TIMEOUT=3

log() {
    printf '[verify-db-role-isolation] %s\n' "$1" >&2
}

fail() {
    log "FAIL: $1"
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

require_password_file ODOO_DB_PASSWORD_FILE
require_password_file N8N_DB_PASSWORD_FILE
[ -n "${ODOO_DB_NAME:-}" ] || fail "ODOO_DB_NAME is required; refusing to guess it"

ADMIN_USER="${POSTGRES_USER:-pwr_db_admin}"

psql_as_admin() {
    psql -X -At -v ON_ERROR_STOP=1 --username "$ADMIN_USER" "$@"
}

# --- Check 1: pwr_db_admin is superuser, and application services never
#     authenticate as it (structural: verified via role attributes only,
#     since "application services do not use it" is enforced by Compose
#     wiring checked in migrate-n8n-db-role.sh's apply step). ---
log "Check 1: pwr_db_admin is a superuser"
admin_super="$(psql_as_admin -d postgres -c \
    "SELECT rolsuper FROM pg_roles WHERE rolname = '$ADMIN_USER'")"
[ "$admin_super" = "t" ] || fail "$ADMIN_USER (bootstrap admin) is not rolsuper=true"
log "OK: $ADMIN_USER rolsuper=true"

# --- Check 2: odoo_app is non-superuser, non-createdb, non-createrole. ---
log "Check 2: odoo_app has no elevated attributes"
odoo_flags="$(psql_as_admin -d postgres -c \
    "SELECT rolsuper, rolcreatedb, rolcreaterole FROM pg_roles WHERE rolname = 'odoo_app'")"
[ "$odoo_flags" = "f|f|f" ] || fail "odoo_app has unexpected role flags: $odoo_flags"
log "OK: odoo_app rolsuper=false rolcreatedb=false rolcreaterole=false"

# --- Check 3: n8n_app is non-superuser, non-createdb, non-createrole. ---
log "Check 3: n8n_app has no elevated attributes"
n8n_flags="$(psql_as_admin -d postgres -c \
    "SELECT rolsuper, rolcreatedb, rolcreaterole FROM pg_roles WHERE rolname = 'n8n_app'")"
[ "$n8n_flags" = "f|f|f" ] || fail "n8n_app has unexpected role flags: $n8n_flags"
log "OK: n8n_app rolsuper=false rolcreatedb=false rolcreaterole=false"

N8N_DB_PASSWORD="$(cat "$N8N_DB_PASSWORD_FILE")"
ODOO_DB_PASSWORD="$(cat "$ODOO_DB_PASSWORD_FILE")"

# --- Check 4: n8n_app can connect/create/rollback a temp table in n8n. ---
log "Check 4: n8n_app can connect and create a temp table in n8n (positive)"
if ! PGPASSWORD="$N8N_DB_PASSWORD" psql -X -At -v ON_ERROR_STOP=1 \
    --username n8n_app --dbname n8n -c \
    "BEGIN; CREATE TEMP TABLE pwr_isolation_probe(id int); ROLLBACK;" >/dev/null 2>&1
then
    fail "n8n_app could not connect/create/rollback a temp table in n8n (expected success)"
fi
log "OK: n8n_app connect+create+rollback succeeded in n8n"

# --- Check 5: n8n_app connecting to the Odoo database must fail. ---
log "Check 5: n8n_app connection to the Odoo database (negative)"
if PGPASSWORD="$N8N_DB_PASSWORD" psql -X -At -v ON_ERROR_STOP=1 \
    --username n8n_app --dbname "$ODOO_DB_NAME" -c "SELECT 1" >/dev/null 2>&1
then
    fail "n8n_app unexpectedly connected to the Odoo database (expected connection failure)"
fi
log "OK: n8n_app to Odoo database failed as expected connection failure"

# --- Check 6: odoo_app can read its own schema; connecting to n8n fails. ---
log "Check 6a: odoo_app can connect and read its schema (positive)"
if ! PGPASSWORD="$ODOO_DB_PASSWORD" psql -X -At -v ON_ERROR_STOP=1 \
    --username odoo_app --dbname "$ODOO_DB_NAME" -c \
    "SELECT count(*) FROM information_schema.tables WHERE table_schema = 'public'" >/dev/null 2>&1
then
    fail "odoo_app could not connect/read its own schema (expected success)"
fi
log "OK: odoo_app connect+read succeeded in $ODOO_DB_NAME"

log "Check 6b: odoo_app connection to n8n (negative)"
if PGPASSWORD="$ODOO_DB_PASSWORD" psql -X -At -v ON_ERROR_STOP=1 \
    --username odoo_app --dbname n8n -c "SELECT 1" >/dev/null 2>&1
then
    fail "odoo_app unexpectedly connected to n8n (expected connection failure)"
fi
log "OK: odoo_app to n8n failed as expected connection failure"

log "All six isolation checks passed"
