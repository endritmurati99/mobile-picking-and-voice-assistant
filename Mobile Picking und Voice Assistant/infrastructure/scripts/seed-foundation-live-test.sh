#!/usr/bin/env bash
# Host-Seite des Live-Seeds.
#
# Ruft `seed-foundation-live-test.py` SERIELL fuer beide Instanzen in je einem
# Einweg-`odoo shell` auf, holt aus jedem Lauf genau einen
# `PWR_SEED_METADATA=`-Marker und fuehrt die beiden zu einer Datei zusammen.
#
# Warum der Host schreibt und nicht der Container: die Zieldatei liegt in einem
# host-eigenen 0700-Verzeichnis. Schriebe der Container hinein, haenge das Gate
# an der UID des Odoo-Images -- und die aendert sich mit jedem Basisimage.
#
# Warum "genau ein" Marker: Odoo-Logs umgeben die Zeile. Zwei Marker hiessen,
# dass das Seed-Skript zweimal gelaufen ist (und damit doppelt gesaet hat),
# null Marker, dass es gescheitert ist, ohne einen Exit-Code zu setzen.
set -Eeuo pipefail

TARGET="${1:?Usage: seed-foundation-live-test.sh /pfad/zu/seed-metadata.json}"
DOCKER="${DOCKER_BIN:-docker}"
SEED_SCRIPT="infrastructure/scripts/seed-foundation-live-test.py"
PASSWORD_FILE="${ODOO19_LIVE_PASSWORD_FILE:?ODOO19_LIVE_PASSWORD_FILE is required}"
DB_A="${ODOO19_LIVE_DB_A:?ODOO19_LIVE_DB_A is required}"
DB_B="${ODOO19_LIVE_DB_B:?ODOO19_LIVE_DB_B is required}"

if [ "$(stat -c '%a' "${PASSWORD_FILE}")" != "400" ]; then
    echo "FAIL: ${PASSWORD_FILE} must be mode 0400" >&2
    exit 1
fi

WORK="$(mktemp -d)"
chmod 700 "${WORK}"
cleanup_seed() { rm -rf "${WORK}"; }
trap cleanup_seed EXIT

seed_one() {
    # $1 Instanzname, $2 Datenbank, $3 Zieldatei fuer den Marker
    local instance="$1" database="$2" out="$3"
    echo "seeding ${instance} (${database})"
    # Das Passwort reist durch die kurzlebige Prozessumgebung, nicht als
    # Argument: Argumente stehen in `ps`.
    ${DOCKER} compose run --rm --no-deps -T \
        -e "PWR_SEED_INSTANCE=${instance}" \
        -e "PWR_TEST_SERVICE_PASSWORD=$(cat "${PASSWORD_FILE}")" \
        odoo odoo shell --no-http -d "${database}" \
        < "${SEED_SCRIPT}" > "${WORK}/${instance}.log" 2>&1 || {
            echo "FAIL: seeding ${instance} failed; see ${WORK}/${instance}.log" >&2
            exit 1
        }

    local markers
    markers="$(grep -c '^PWR_SEED_METADATA=' "${WORK}/${instance}.log" || true)"
    if [ "${markers}" != "1" ]; then
        echo "FAIL: expected exactly one PWR_SEED_METADATA marker for ${instance}, found ${markers}" >&2
        exit 1
    fi
    grep '^PWR_SEED_METADATA=' "${WORK}/${instance}.log" \
        | sed 's/^PWR_SEED_METADATA=//' > "${out}"
    chmod 600 "${out}"
}

rm -f "${TARGET}"
seed_one "o19-a" "${DB_A}" "${WORK}/a.json"
seed_one "o19-b" "${DB_B}" "${WORK}/b.json"

python3 - "${WORK}/a.json" "${WORK}/b.json" "${TARGET}" <<'PY'
import json
import os
import sys

first, second, target = sys.argv[1:4]
instances = [json.load(open(path, encoding="utf-8")) for path in (first, second)]

problems = []
if instances[0]["aggregate_id"] != instances[1]["aggregate_id"]:
    problems.append(
        "the two databases produced different aggregate ids "
        f"({instances[0]['aggregate_id']} vs {instances[1]['aggregate_id']}); the "
        "isolation gate needs them IDENTICAL, otherwise a routing bug hides "
        "behind an id the wrong database does not know"
    )
if instances[0]["job_id"] == instances[1]["job_id"]:
    problems.append("both databases produced the same job id")
twenty = instances[0]["twenty_event_ids"]
if len(twenty) != 20 or len(set(twenty)) != 20:
    problems.append(f"expected 20 distinct concurrency events, got {len(set(twenty))}")
if instances[1]["twenty_event_ids"]:
    problems.append("the secondary database must carry no concurrency seed")
restart = instances[0]["restart_event"]
for key in ("job_id", "event_id", "fingerprint", "processing_lease_token", "stale_lease_token"):
    if not restart.get(key):
        problems.append(f"restart_event is missing {key}")

if problems:
    for problem in problems:
        print(f"FAIL: {problem}", file=sys.stderr)
    raise SystemExit(1)

# Genau das Schema, das `backend/tests/live/conftest.py` verlangt -- nicht mehr
# und nicht weniger. Ein zusaetzlicher Schluessel hiesse, dass Seed und Gate
# auseinandergelaufen sind, und dann ist unklar, welche Haelfte veraltet ist.
merged = {
    "instances": instances,
    "twenty_event_ids": twenty,
    "restart_event": restart,
}
descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
    json.dump(merged, handle, sort_keys=True)
print(f"seed metadata written to {target}")
PY
