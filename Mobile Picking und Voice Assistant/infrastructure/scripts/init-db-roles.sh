#!/bin/bash
# Fresh-volume bootstrap for dedicated PostgreSQL application roles.
#
# Runs only inside PostgreSQL's fresh-volume initialization directory
# (docker-entrypoint-initdb.d) as the image-created bootstrap superuser
# (pwr_db_admin). It creates two non-superuser application roles,
# odoo_app and n8n_app, each owning exactly one database, and locks
# down cross-database visibility so neither app role can see the
# other's database by default.
#
# Required environment (paths to files, never raw secrets):
#   PWR_DB_ADMIN_PASSWORD_FILE  - password for the pwr_db_admin bootstrap role
#   ODOO_DB_PASSWORD_FILE       - password for the odoo_app role
#   N8N_DB_PASSWORD_FILE        - password for the n8n_app role
#   ODOO_DB_NAME                - final Odoo-19 production database name
#                                  (fail closed: no guessed default)
#
# This script never echoes secret file contents.
set -euo pipefail

log() {
    printf '[init-db-roles] %s\n' "$1" >&2
}

fail() {
    log "ERROR: $1"
    exit 1
}

require_password_file() {
    local var_name="$1"
    local path="${!var_name:-}"
    if [ -z "$path" ]; then
        fail "$var_name is required and must point to a password file"
    fi
    if [ ! -f "$path" ]; then
        fail "$var_name points to a missing file: $path"
    fi
    local mode
    mode="$(stat -c '%a' "$path" 2>/dev/null || stat -f '%Lp' "$path")"
    if [ "$mode" != "400" ] && [ "$mode" != "600" ]; then
        fail "$var_name ($path) must be mode 0400 or 0600, found $mode"
    fi
}

require_password_file PWR_DB_ADMIN_PASSWORD_FILE
require_password_file ODOO_DB_PASSWORD_FILE
require_password_file N8N_DB_PASSWORD_FILE

if [ -z "${ODOO_DB_NAME:-}" ]; then
    fail "ODOO_DB_NAME is required (final Odoo-19 production database name); refusing to guess it"
fi

# This script must run as the image-created bootstrap superuser named
# pwr_db_admin (Task 15 sets POSTGRES_USER=pwr_db_admin for the fresh-
# volume image bootstrap). Fail closed rather than silently creating
# app roles under an arbitrary/unverified admin identity.
if [ "${POSTGRES_USER:-}" != "pwr_db_admin" ]; then
    fail "POSTGRES_USER must be pwr_db_admin (the bootstrap superuser this script runs as); got '${POSTGRES_USER:-<unset>}'"
fi

ODOO_DB_PASSWORD="$(cat "$ODOO_DB_PASSWORD_FILE")"
N8N_DB_PASSWORD="$(cat "$N8N_DB_PASSWORD_FILE")"

log "Bootstrapping roles pwr_db_admin (existing), odoo_app, n8n_app"
log "Odoo database: $ODOO_DB_NAME"

psql -v ON_ERROR_STOP=1 \
    --username "$POSTGRES_USER" \
    --dbname postgres \
    -v "odoo_password=$ODOO_DB_PASSWORD" \
    -v "n8n_password=$N8N_DB_PASSWORD" \
    -v "odoo_db=$ODOO_DB_NAME" <<'SQL'
-- Executed as the image-created pwr_db_admin bootstrap superuser.
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

SELECT format('CREATE DATABASE %I OWNER odoo_app', :'odoo_db')
WHERE NOT EXISTS (SELECT 1 FROM pg_database WHERE datname = :'odoo_db')
\gexec

SELECT 'CREATE DATABASE n8n OWNER n8n_app'
WHERE NOT EXISTS (SELECT 1 FROM pg_database WHERE datname = 'n8n')
\gexec

REVOKE CONNECT, TEMPORARY ON DATABASE n8n FROM PUBLIC;
GRANT CONNECT, TEMPORARY ON DATABASE n8n TO n8n_app;

SELECT format('REVOKE CONNECT, TEMPORARY ON DATABASE %I FROM PUBLIC', :'odoo_db') \gexec
SELECT format('GRANT CONNECT, TEMPORARY ON DATABASE %I TO odoo_app', :'odoo_db') \gexec
SQL

log "Applying schema ownership and default privileges inside n8n"
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname n8n <<'SQL'
REVOKE ALL ON SCHEMA public FROM PUBLIC;
GRANT USAGE, CREATE ON SCHEMA public TO n8n_app;
ALTER SCHEMA public OWNER TO n8n_app;
ALTER DEFAULT PRIVILEGES FOR ROLE n8n_app GRANT ALL ON TABLES TO n8n_app;
ALTER DEFAULT PRIVILEGES FOR ROLE n8n_app GRANT ALL ON SEQUENCES TO n8n_app;
SQL

log "Applying schema ownership and default privileges inside $ODOO_DB_NAME"
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$ODOO_DB_NAME" <<SQL
REVOKE ALL ON SCHEMA public FROM PUBLIC;
GRANT USAGE, CREATE ON SCHEMA public TO odoo_app;
ALTER SCHEMA public OWNER TO odoo_app;
ALTER DEFAULT PRIVILEGES FOR ROLE odoo_app GRANT ALL ON TABLES TO odoo_app;
ALTER DEFAULT PRIVILEGES FOR ROLE odoo_app GRANT ALL ON SEQUENCES TO odoo_app;
SQL

log "Done: odoo_app owns $ODOO_DB_NAME, n8n_app owns n8n, both non-superuser"
