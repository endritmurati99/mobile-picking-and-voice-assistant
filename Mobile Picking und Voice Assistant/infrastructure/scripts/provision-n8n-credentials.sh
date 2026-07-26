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

SECRET_FILES=(
  "/run/secrets/pwr_n8n_native_header"
  "/run/secrets/pwr_backend_to_n8n_active_hmac"
  "/run/secrets/pwr_backend_to_n8n_previous_hmac"
  "/run/secrets/pwr_n8n_to_backend_active_hmac"
  "/run/secrets/pwr_n8n_callback_legacy"
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

check_secret_permissions() {
  local path="$1"
  if [[ ! -e "$path" ]]; then
    # Optional secrets (e.g. the previous HMAC during normal, non-rotation
    # operation) may not exist; the Node module itself enforces which ones
    # are required for which mode.
    return 0
  fi
  local mode
  mode="$(stat -c '%a' "$path" 2>/dev/null || stat -f '%Lp' "$path" 2>/dev/null || echo '')"
  if [[ -n "$mode" && "$mode" != "600" && "$mode" != "400" ]]; then
    echo "ERROR: $path has mode $mode; expected 600 or 400" >&2
    exit 1
  fi
  local owner
  owner="$(stat -c '%U' "$path" 2>/dev/null || stat -f '%Su' "$path" 2>/dev/null || echo '')"
  if [[ -n "$owner" && "$owner" != "root" && "$owner" != "$(id -un)" ]]; then
    echo "WARNING: $path is owned by unexpected user '$owner'" >&2
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

for secret_path in "${SECRET_FILES[@]}"; do
  check_secret_permissions "$secret_path"
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
