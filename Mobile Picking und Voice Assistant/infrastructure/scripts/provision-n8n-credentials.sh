#!/usr/bin/env bash
# Runs the n8n credential bootstrap (provision-credentials.mjs) inside the
# live n8n container. Reads Docker secrets straight from disk to check their
# ownership/mode before delegating; never turns on shell tracing, since that
# would print resolved secret file paths (not the secrets themselves, but
# still avoided out of caution) to the console.
set -euo pipefail

MODE="${1:-}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
COMPOSE_FILE="${COMPOSE_FILE:-$ROOT_DIR/docker-compose.yml}"
# NOTE: docker-compose.yml is owned by a separate task and must mount
# ./n8n/scripts read-only into the n8n container at this path (or set
# N8N_SCRIPTS_CONTAINER_PATH to wherever it is actually mounted).
CONTAINER_SCRIPT_PATH="${N8N_SCRIPTS_CONTAINER_PATH:-/home/node/scripts/provision-credentials.mjs}"
# The only account allowed to own these secret files. Docker secrets are
# normally root-owned on the host; override only if your deployment
# provisions them under a different, explicitly intended account.
PWR_SECRET_OWNER="${PWR_SECRET_OWNER:-root}"

# Overridable so tests can point at a synthetic secret directory without
# touching the real one; the real script always uses the default. Note that
# this is the HOST path -- inside the container the same files live at the
# same names in a different namespace (see check_secret_permissions).
PWR_SECRET_DIR="${PWR_SECRET_DIR:-/run/secrets}"

# Required for every mode: provision-credentials.mjs refuses to run without
# them, so a missing one here is always a misconfigured host.
REQUIRED_SECRET_FILES=(
  "$PWR_SECRET_DIR/pwr_n8n_native_header"
  "$PWR_SECRET_DIR/pwr_backend_to_n8n_active_hmac"
  "$PWR_SECRET_DIR/pwr_n8n_to_backend_active_hmac"
)

# Legitimately absent outside their own mode: the previous HMAC only exists
# during a rotation (and is added to the required list below for `rotate`),
# and the legacy callback secret is optional by design. "Absent" is a valid
# state for these two -- for everything else it is an error, not a shrug.
OPTIONAL_SECRET_FILES=(
  "$PWR_SECRET_DIR/pwr_backend_to_n8n_previous_hmac"
  "$PWR_SECRET_DIR/pwr_n8n_callback_legacy"
)

usage() {
  cat <<'EOF'
Usage:
  bash infrastructure/scripts/provision-n8n-credentials.sh provision
  bash infrastructure/scripts/provision-n8n-credentials.sh verify
  bash infrastructure/scripts/provision-n8n-credentials.sh rotate

Runs n8n/scripts/provision-credentials.mjs inside the running n8n container.
Only credential metadata (id/name/type) is ever printed; secret values never
leave the container.
EOF
}

# EARLY CONVENIENCE CHECK -- NOT THE SECURITY BOUNDARY.
#
# This inspects paths in the HOST namespace, but provision-credentials.mjs
# reads identically named paths INSIDE the container: same name, different
# file. Passing here therefore says nothing about what will actually be
# read. Its only job is to fail a misconfigured host loudly and early,
# before anything reaches docker. The check that counts sits immediately
# before the read, in n8n/scripts/provision-credentials.mjs, and uses lstat.
#
# A missing file is a hard failure here. It used to return 0, which meant a
# host with no secrets at all sailed straight through to docker; callers
# decide which files are required for the current mode (see below) rather
# than this function shrugging at absence.
check_secret_permissions() {
  local path="$1"
  if [[ -L "$path" ]]; then
    echo "ERROR: $path is a symlink; a secret file must be a regular file" >&2
    exit 1
  fi
  if [[ ! -e "$path" ]]; then
    echo "ERROR: $path does not exist" >&2
    exit 1
  fi
  local mode
  mode="$(stat -c '%a' "$path" 2>/dev/null || stat -f '%Lp' "$path" 2>/dev/null || echo '')"
  if [[ -n "$mode" && "$mode" != "600" && "$mode" != "400" ]]; then
    echo "ERROR: $path has mode $mode; expected 600 or 400" >&2
    exit 1
  fi
  local owner
  owner="$(stat -c '%U' "$path" 2>/dev/null || stat -f '%Su' "$path" 2>/dev/null || echo '')"
  if [[ -n "$owner" && "$owner" != "$PWR_SECRET_OWNER" ]]; then
    echo "ERROR: $path is owned by '$owner', not the permitted owner '$PWR_SECRET_OWNER'" >&2
    exit 1
  fi
}

case "$MODE" in
  provision|verify|rotate)
    ;;
  *)
    usage >&2
    exit 1
    ;;
esac

required_secret_files=("${REQUIRED_SECRET_FILES[@]}")
if [[ "$MODE" == "rotate" ]]; then
  required_secret_files+=("$PWR_SECRET_DIR/pwr_backend_to_n8n_previous_hmac")
fi

for secret_path in "${required_secret_files[@]}"; do
  check_secret_permissions "$secret_path"
done

# The genuinely optional ones are only checked once they exist -- but a
# dangling symlink counts as "present" here, so it is rejected rather than
# silently skipped.
for secret_path in "${OPTIONAL_SECRET_FILES[@]}"; do
  if [[ "$MODE" == "rotate" && "$secret_path" == *"pwr_backend_to_n8n_previous_hmac" ]]; then
    continue  # already checked as required above
  fi
  if [[ -e "$secret_path" || -L "$secret_path" ]]; then
    check_secret_permissions "$secret_path"
  fi
done

metadata_file="$(mktemp "${TMPDIR:-/tmp}/n8n-credentials-metadata.XXXXXX.json")"
chmod 600 "$metadata_file"
cleanup() {
  rm -f "$metadata_file"
}
trap cleanup EXIT

docker compose -f "$COMPOSE_FILE" exec -T n8n \
  node "$CONTAINER_SCRIPT_PATH" "$MODE" \
  >"$metadata_file"

cat "$metadata_file"
