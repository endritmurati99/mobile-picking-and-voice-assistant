#!/usr/bin/env bash
# Foundation Task 17: Kill/Restart-Gate.
#
# Die Frage, die nur hier beantwortet wird: ueberlebt genau EINE
# Geschaeftswirkung einen Neustart mitten in der Zustellung? Ein Event, das im
# Moment des Abschusses in `processing` steht, wird nach dem Neustart unter
# einer neuen Generation erneut zugestellt. Wird dabei zweimal etikettiert oder
# zweimal gebucht, ist die ganze Outbox wertlos -- und das sieht man
# ausschliesslich an einer echten Anlage, die man wirklich abschiesst.
#
# Die Reihenfolge des Neustarts ist Teil der Behauptung: erst Backend, dann
# warten, bis der Watchdog das abgelaufene Lease uebernommen hat, DANN n8n.
# Startete n8n zuerst, liefe der Retry noch unter der alten Generation und die
# Pruefung ginge an der Sache vorbei.
#
# ---------------------------------------------------------------------------
# STAND 2026-08-01, BITTE LESEN, BEVOR JEMAND DAS SKRIPT "REPARIERT":
#
# Der Plan beschreibt diesen Ablauf gegen eine Odoo-Oberflaeche, die es NICHT
# GIBT. Gemessen, nicht vermutet:
#
#   * `api_create_smoke_job` existiert in keinem Modul.
#   * `test_delay_seconds` und `artifact_probe` kommen im ganzen Repository
#     nicht vor.
#   * `api_get_job` liefert `state`, `delivery_generation`, `sequence`,
#     `attempt`, `result`, `error`, `metrics` -- aber weder `envelope_sha256`
#     noch `effect_count`, `receipt_count`, `artifact_count` oder
#     `callback_sequences`, also genau die Felder, aus denen dieses Gate seine
#     Behauptungen bildet.
#
# Deshalb prueft `require_probe_surface` unten zuerst, ob die Oberflaeche da
# ist, und bricht sonst mit ihren Namen ab. Ein Skript, das stattdessen eine
# erfundene Methode aufriefe, wuerde mit einem RPC-Fehler sterben, den man als
# Umgebungsproblem missdeutet -- und das ist genau der Weg, auf dem in diesem
# Programm schon dreimal ein Waechter entstanden ist, der nichts bewacht.
#
# Zu tun, bevor dieses Gate laufen kann: die Probe-Oberflaeche in
# `picking_assistant_integration` implementieren (ein `api_create_smoke_job`
# mit kuenstlicher Verzoegerung und ein lesendes `api_get_job_probe`), mit
# Odoo-Modultests, gegen einen laufenden Odoo-19-Container.
# ---------------------------------------------------------------------------
set -Eeuo pipefail

: "${COMPOSE_FILE:=docker-compose.yml:docker-compose.dev.yml}"
export COMPOSE_FILE

DOCKER="${DOCKER_BIN:-docker}"
ODOO_DB="${ODOO19_LIVE_DB_A:?ODOO19_LIVE_DB_A is required}"
WORKFLOW="${FOUNDATION_SMOKE_WORKFLOW:-n8n/workflows/pwr-foundation-smoke-v2.json}"
BACKUP_DIR="${FOUNDATION_WORKFLOW_BACKUP:?FOUNDATION_WORKFLOW_BACKUP is required}"
RUN_ID="restart-$(date -u +%Y%m%dT%H%M%SZ)-$$"
DEADLINE=$(( $(date +%s) + 720 ))   # 12 Minuten gesamt
RPC="infrastructure/scripts/live_rpc.py"

log() { printf '%s  %s\n' "$(date -u +%H:%M:%S)" "$*"; }

odoo_rpc() { python3 "${RPC}" "${ODOO_DB}" "$1" "$2" "$3"; }

job_field() {
    # $1 job_id, $2 Feldname
    odoo_rpc picking.assistant.integration.job api_get_job_probe "[\"$1\"]" \
        | python3 -c "import json,sys; print(json.load(sys.stdin)[\"$2\"])"
}

require_deadline() {
    if [ "$(date +%s)" -ge "${DEADLINE}" ]; then
        echo "FAIL: 12-minute budget exhausted at: $*" >&2
        exit 1
    fi
}

poll_until() {
    # $1 Beschreibung, danach: Kommando, das bei Erfolg 0 liefert
    local description="$1"; shift
    until "$@"; do
        require_deadline "${description}"
        sleep 3
    done
    log "reached: ${description}"
}

require_probe_surface() {
    # Fail closed, MIT Namen. Siehe den Block oben.
    local missing=""
    if ! odoo_rpc ir.model.data check_object_reference \
        '["picking_assistant_integration", "model_picking_assistant_integration_job"]' \
        >/dev/null 2>&1; then
        echo "FAIL: picking_assistant_integration is not installed in ${ODOO_DB}" >&2
        exit 1
    fi
    for method in api_create_smoke_job api_get_job_probe; do
        if ! odoo_rpc picking.assistant.integration.job "${method}" '[]' >/dev/null 2>&1; then
            missing="${missing} ${method}"
        fi
    done
    if [ -n "${missing}" ]; then
        cat >&2 <<EOF
FAIL: the restart gate needs an Odoo probe surface that does not exist yet.

Missing on picking.assistant.integration.job:${missing}

  api_create_smoke_job(test_delay_seconds, artifact_probe)
      creates one job plus outbox event whose processing is slow enough that
      the kill lands mid-delivery, and returns {job_id, event_id}.

  api_get_job_probe(job_id)
      read-only, returns at least:
        state, delivery_generation, envelope_sha256, effect_count,
        receipt_count, artifact_count, callback_sequences, legacy_header_mode

Implement both with Odoo module tests before running this gate. Do not stub
them here: a gate whose measurements come from the gate itself measures
nothing.
EOF
        exit 1
    fi
}

# Der Cleanup ist PFLICHT, nicht Hoeflichkeit: eine aktiv gebliebene
# Test-Workflow-Version liefe in der naechsten echten Ausfuehrung mit.
cleanup_restart_gate() {
    local status=$?
    log "cleanup: deactivating the test workflow for ${RUN_ID}"
    bash infrastructure/scripts/import-workflows.sh \
        deactivate-test "${BACKUP_DIR}" "${WORKFLOW}" "${RUN_ID}" || \
        log "WARNING: deactivate-test failed -- check the workflow state by hand"
    ${DOCKER} compose start backend n8n >/dev/null 2>&1 || true
    exit "${status}"
}

log "run ${RUN_ID}"
require_probe_surface
trap cleanup_restart_gate EXIT
bash infrastructure/scripts/import-workflows.sh \
    activate-test "${BACKUP_DIR}" "${WORKFLOW}" "${RUN_ID}"

# 1. Ein Job mit kuenstlicher Verzoegerung, damit der Abschuss zuverlaessig
#    MITTEN in der Verarbeitung landet und nicht davor oder danach.
log "creating the delayed smoke job"
JOB_JSON="$(odoo_rpc picking.assistant.integration.job api_create_smoke_job '[60, true]')"
JOB_ID="$(printf '%s' "${JOB_JSON}" | python3 -c 'import json,sys; print(json.load(sys.stdin)["job_id"])')"
EVENT_ID="$(printf '%s' "${JOB_JSON}" | python3 -c 'import json,sys; print(json.load(sys.stdin)["event_id"])')"
log "job=${JOB_ID} event=${EVENT_ID}"

# 2./3. Zustand VOR dem Abschuss festhalten, Envelope-Hash inklusive: nach dem
#       Neustart muss exakt derselbe Body erneut zugestellt werden, nur unter
#       neuer Generation.
poll_until "receipt processing" \
    bash -c "[ \"\$(python3 '${RPC}' '${ODOO_DB}' picking.assistant.integration.job api_get_job_probe '[\"${JOB_ID}\"]' | python3 -c 'import json,sys; print(json.load(sys.stdin)[\"state\"])')\" = processing ]"
BEFORE_SHA="$(job_field "${JOB_ID}" envelope_sha256)"
BEFORE_EFFECTS="$(job_field "${JOB_ID}" effect_count)"
log "pre-kill sha256=${BEFORE_SHA} effects=${BEFORE_EFFECTS} generation=1"

# 4. Der Abschuss.
log "stopping backend and n8n"
${DOCKER} compose stop backend n8n

# 5. Backend zuerst, und dann WARTEN: der Watchdog braucht das abgelaufene
#    Lease, bevor die neue Generation entstehen kann.
log "starting backend, waiting for the lease/watchdog transition"
${DOCKER} compose start backend
poll_until "generation rolled over to 2" \
    bash -c "[ \"\$(python3 '${RPC}' '${ODOO_DB}' picking.assistant.integration.job api_get_job_probe '[\"${JOB_ID}\"]' | python3 -c 'import json,sys; print(json.load(sys.stdin)[\"delivery_generation\"])')\" = 2 ]"

# 6. Erst jetzt n8n.
log "starting n8n"
${DOCKER} compose start n8n

# 7. Genau EIN terminaler Callback.
poll_until "terminal succeeded callback" \
    bash -c "[ \"\$(python3 '${RPC}' '${ODOO_DB}' picking.assistant.integration.job api_get_job_probe '[\"${JOB_ID}\"]' | python3 -c 'import json,sys; print(json.load(sys.stdin)[\"state\"])')\" = succeeded ]"

# 8./9./10. Die eigentlichen Behauptungen.
AFTER="$(odoo_rpc picking.assistant.integration.job api_get_job_probe "[\"${JOB_ID}\"]")"
printf '%s' "${AFTER}" | python3 - "${BEFORE_SHA}" "${BEFORE_EFFECTS}" <<'PY'
import json
import sys

after = json.load(sys.stdin)
before_sha, before_effects = sys.argv[1:3]
problems = []

if after["effect_count"] != int(before_effects):
    problems.append(
        f"business effect count moved from {before_effects} to "
        f"{after['effect_count']}; the redelivery must not produce a second "
        "effect -- that duplicate is the failure this gate exists for"
    )
if after["envelope_sha256"] != before_sha:
    problems.append(
        "the redelivered envelope has a different SHA-256; the retry must "
        "resend the SAME bytes under a new generation, not a rebuilt payload"
    )
if after["receipt_count"] != 1:
    problems.append(f"expected one event receipt, found {after['receipt_count']}")
if after["artifact_count"] != 1:
    problems.append(f"expected exactly one zpl artifact, found {after['artifact_count']}")
sequences = after.get("callback_sequences", [])
if sequences != sorted(sequences) or len(set(sequences)) != len(sequences):
    problems.append(f"callback sequences are not strictly increasing: {sequences}")
if after.get("legacy_header_mode"):
    problems.append("a service restarted into legacy header mode")

if problems:
    for problem in problems:
        print(f"FAIL: {problem}", file=sys.stderr)
    raise SystemExit(1)

print(
    "PASS: one job, one effect, one receipt, one artifact, identical envelope "
    f"sha256, sequences {sequences}"
)
PY

log "restart gate passed for job ${JOB_ID}"
