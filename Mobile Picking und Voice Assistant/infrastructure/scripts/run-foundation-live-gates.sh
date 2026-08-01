#!/usr/bin/env bash
# Foundation Task 17: der serielle Live-Gate-Lauf.
#
# Besitzt fuer seine gesamte Laufzeit die Run-ID-Umgebung und den Cleanup-Trap.
# Seriell und nicht parallel, weil die Gates einander den Zustand kaputtmachen:
# der Nebenlaeufigkeitstest verbraucht die 20 gesaeten Events, und der
# Isolationstest behauptet, dass Datenbank B unberuehrt bleibt -- ein parallel
# laufendes zweites Gate waere genau die Beruehrung.
#
# ---------------------------------------------------------------------------
# STAND 2026-08-01: der Plan sieht hier eine eigene, wegwerfbare Datenbank vor,
# die mit der Rolle `pwr_db_admin` und dem Overlay
# `infrastructure/docker-compose.db-migration.yml` entsteht. **Die Rolle
# `pwr_db_admin` existiert im Repository nicht** -- sie gehoert zu R4, und R4
# ist zweimal abgelehnt und gesperrt (Handoff §4).
#
# Dieses Skript erfindet die Rolle deshalb nicht. Es verlangt eine bereits
# bereitgestellte Datenbankumgebung und sagt, was fehlt. Ein Skript, das die
# Rolle anlegte, waere ein ungeprueftes Stueck R4 an R4s Review vorbei -- und
# R4s erster Critical war exakt, dass sein Compose-Teil versehentlich deploybar
# war.
# ---------------------------------------------------------------------------
set -Eeuo pipefail

RUN_ID="$(date -u +%Y%m%dT%H%M%SZ)-$$"
export COMPOSE_PROJECT_NAME="pwr-foundation-live-${RUN_ID}"
export COMPOSE_FILE="docker-compose.yml:docker-compose.dev.yml"

DOCKER="${DOCKER_BIN:-docker}"
ARTIFACTS="${PWR_LIVE_ARTIFACTS:-.artifacts}"
SEED_METADATA="${ARTIFACTS}/foundation-seed-metadata.json"

log() { printf '%s  [%s] %s\n' "$(date -u +%H:%M:%S)" "${RUN_ID}" "$*"; }

cleanup_foundation_live() {
    local status=$?
    log "cleanup"
    ${DOCKER} compose down --remove-orphans || true
    exit "${status}"
}
trap cleanup_foundation_live EXIT

require_environment() {
    local missing=()
    for name in \
        ODOO19_LIVE_URL ODOO19_LIVE_DB_A ODOO19_LIVE_DB_B ODOO19_LIVE_USER \
        ODOO19_LIVE_PASSWORD_FILE FOUNDATION_API_URL FOUNDATION_CA_FILE \
        FOUNDATION_N2B_KEY_ID FOUNDATION_N2B_SECRET_FILE
    do
        [ -n "${!name:-}" ] || missing+=("${name}")
    done
    if [ "${#missing[@]}" -ne 0 ]; then
        echo "FAIL: live gate requires environment: ${missing[*]}" >&2
        exit 1
    fi
    if [ "${ODOO19_LIVE_DB_A}" = "${ODOO19_LIVE_DB_B}" ]; then
        echo "FAIL: ODOO19_LIVE_DB_A and ODOO19_LIVE_DB_B are the same database" >&2
        exit 1
    fi
}

require_provisioned_databases() {
    # Siehe den Block oben: kein Anlegen von Rollen oder Datenbanken hier.
    for database in "${ODOO19_LIVE_DB_A}" "${ODOO19_LIVE_DB_B}"; do
        if ! python3 infrastructure/scripts/live_rpc.py \
            "${database}" ir.model.data check_object_reference \
            '["picking_assistant_integration", "model_picking_assistant_integration_job"]' \
            >/dev/null 2>&1; then
            cat >&2 <<EOF
FAIL: ${database} is not a usable live-gate database.

Expected: an existing Odoo 19 database with picking_assistant_integration and
picking_assistant_core installed, reachable as ODOO19_LIVE_USER.

This script deliberately does NOT create databases or roles. The plan's setup
uses the role \`pwr_db_admin\`, which does not exist in this repository -- it
belongs to R4, and R4 is rejected and blocked. Provision the two databases with
the existing tooling, or unblock R4 first.
EOF
            exit 1
        fi
    done
}

# --- 1. Umgebung ----------------------------------------------------------
log "checking environment"
require_environment

log "waiting for the database service"
${DOCKER} compose up -d db
until ${DOCKER} compose exec -T db pg_isready -q; do sleep 1; done

log "starting the application services"
${DOCKER} compose up -d backend odoo n8n
require_provisioned_databases

# --- 2. Seed --------------------------------------------------------------
# Die Metadaten gehoeren dem HOST: mode 0700, und kein Container schreibt
# hinein. Sonst haengt das Gate an der UID des Odoo-Images.
log "seeding both instances"
rm -f "${SEED_METADATA}"
mkdir -p "${ARTIFACTS}"
chmod 700 "${ARTIFACTS}"
bash infrastructure/scripts/seed-foundation-live-test.sh "${SEED_METADATA}"

export FOUNDATION_SEED_METADATA="${SEED_METADATA}"

# --- 3. Gates, seriell ----------------------------------------------------
log "gate 1/3: two-database isolation"
( cd backend && PYTHONPATH=".:.deps" python3 -m pytest -p pytest_asyncio \
    -m foundation_live tests/live -q )

log "gate 2/3: real database races"
( cd backend && PYTHONPATH=".:.deps" python3 -m pytest -p pytest_asyncio \
    -m odoo19_live tests/live -q )

log "gate 3/3: kill and restart"
bash infrastructure/scripts/test-foundation-restart.sh

log "all live gates passed"
