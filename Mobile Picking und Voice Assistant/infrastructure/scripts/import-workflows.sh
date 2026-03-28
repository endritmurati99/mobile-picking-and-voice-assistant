#!/usr/bin/env bash
# Import, activate, and roll back the critical n8n workflows without duplicates.
set -euo pipefail

MODE="${1:-apply}"
ROLLBACK_DIR="${2:-}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
COMPOSE_FILE="${COMPOSE_FILE:-$ROOT_DIR/docker-compose.yml}"
WORKFLOW_DIR="$ROOT_DIR/n8n/workflows"
BACKUP_ROOT="$ROOT_DIR/n8n/backups"
TMP_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/n8n-import.XXXXXX")"

WORKFLOW_FILES=(
  "error-trigger.json"
  "quality-alert-created.json"
  "voice-exception-query.json"
  "shortage-reported.json"
)

cleanup() {
  rm -rf "$TMP_ROOT"
}

trap cleanup EXIT

workflow_name() {
  case "$1" in
    "error-trigger.json") echo "Error Trigger" ;;
    "quality-alert-created.json") echo "Quality Alert Created" ;;
    "voice-exception-query.json") echo "Voice Exception Query" ;;
    "shortage-reported.json") echo "Shortage Reported" ;;
    *)
      echo "Unknown workflow file: $1" >&2
      return 1
      ;;
  esac
}

compose_exec() {
  docker compose -f "$COMPOSE_FILE" exec -T n8n "$@"
}

compose_shell() {
  docker compose -f "$COMPOSE_FILE" exec -T n8n sh -lc "$1"
}

wait_for_n8n() {
  echo "=== Waiting for n8n healthcheck ==="
  for i in $(seq 1 30); do
    if compose_shell "wget -qO- http://localhost:5678/healthz >/dev/null 2>&1"; then
      echo "n8n is healthy."
      return 0
    fi
    echo "  waiting ($i/30)..."
    sleep 2
  done
  echo "ERROR: n8n did not become healthy within 30 attempts." >&2
  return 1
}

export_all_workflows() {
  local output_file="$1"
  compose_shell "rm -f /tmp/codex-export-all.json && n8n export:workflow --all --output=/tmp/codex-export-all.json >/dev/null && cat /tmp/codex-export-all.json" >"$output_file"
}

export_workflow_by_id() {
  local workflow_id="$1"
  local output_file="$2"
  compose_shell "rm -f /tmp/codex-export-one.json && n8n export:workflow --id='$workflow_id' --output=/tmp/codex-export-one.json >/dev/null && cat /tmp/codex-export-one.json" >"$output_file"
}

create_cli_backup_tar() {
  local output_file="$1"
  if ! compose_shell "rm -rf /tmp/codex-workflow-backup && mkdir -p /tmp/codex-workflow-backup && n8n export:workflow --backup --output=/tmp/codex-workflow-backup >/dev/null && tar -C /tmp -cf - codex-workflow-backup" >"$output_file"; then
    echo "WARNING: Could not create CLI backup tarball." >&2
    rm -f "$output_file"
  fi
}

write_state() {
  local export_file="$1"
  local state_file="$2"
  python - "$export_file" "$state_file" <<'PY'
import json
import sys
from collections import defaultdict

TARGETS = {
    "error-trigger.json": "Error Trigger",
    "quality-alert-created.json": "Quality Alert Created",
    "voice-exception-query.json": "Voice Exception Query",
    "shortage-reported.json": "Shortage Reported",
}

export_path, state_path = sys.argv[1:3]
with open(export_path, encoding="utf-8") as handle:
    raw = json.load(handle)

if isinstance(raw, dict):
    if isinstance(raw.get("data"), list):
        workflows = raw["data"]
    elif isinstance(raw.get("workflows"), list):
        workflows = raw["workflows"]
    elif raw.get("name"):
        workflows = [raw]
    else:
        workflows = []
elif isinstance(raw, list):
    workflows = raw
else:
    workflows = []

by_name: dict[str, list[dict]] = defaultdict(list)
for workflow in workflows:
    if isinstance(workflow, dict) and workflow.get("name"):
        by_name[str(workflow["name"])].append(workflow)

state = {"workflows": {}, "duplicates": {}}
for file_name, workflow_name in TARGETS.items():
    matches = by_name.get(workflow_name, [])
    if len(matches) > 1:
        state["duplicates"][workflow_name] = [match.get("id") for match in matches]

    workflow = matches[0] if matches else None
    state["workflows"][file_name] = {
        "name": workflow_name,
        "id": workflow.get("id") if workflow else None,
        "active": bool(workflow.get("active")) if workflow else False,
        "exists": bool(workflow),
    }

with open(state_path, "w", encoding="utf-8") as handle:
    json.dump(state, handle, indent=2)
PY
}

ensure_no_duplicates() {
  local state_file="$1"
  python - "$state_file" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as handle:
    state = json.load(handle)

duplicates = state.get("duplicates") or {}
if duplicates:
    for workflow_name, workflow_ids in sorted(duplicates.items()):
        print(
            f"ERROR: duplicate workflow name detected for '{workflow_name}': "
            f"{', '.join(str(workflow_id) for workflow_id in workflow_ids)}",
            file=sys.stderr,
        )
    raise SystemExit(1)
PY
}

state_field() {
  local state_file="$1"
  local file_name="$2"
  local field_name="$3"
  python - "$state_file" "$file_name" "$field_name" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as handle:
    state = json.load(handle)

workflow = (state.get("workflows") or {}).get(sys.argv[2], {})
value = workflow.get(sys.argv[3])
if value is None:
    print("")
elif isinstance(value, bool):
    print("true" if value else "false")
else:
    print(value)
PY
}

backup_existing_workflows() {
  local state_file="$1"
  local backup_dir="$2"
  mkdir -p "$backup_dir"

  while IFS=$'\t' read -r file_name workflow_id exists; do
    if [[ "$exists" != "true" ]]; then
      continue
    fi
    echo "  Backing up $(workflow_name "$file_name") ..."
    export_workflow_by_id "$workflow_id" "$backup_dir/$file_name"
  done < <(
    python - "$state_file" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as handle:
    state = json.load(handle)

for file_name, workflow in (state.get("workflows") or {}).items():
    print(f"{file_name}\t{workflow.get('id') or ''}\t{'true' if workflow.get('exists') else 'false'}")
PY
  )
}

stage_workflow() {
  local file_name="$1"
  local state_file="$2"
  local error_workflow_id="${3:-}"
  local output_file="$4"

  python - "$WORKFLOW_DIR/$file_name" "$state_file" "$file_name" "$error_workflow_id" "$output_file" <<'PY'
import json
import sys
from uuid import uuid4

source_path, state_path, file_name, error_workflow_id, output_path = sys.argv[1:6]

with open(source_path, encoding="utf-8") as handle:
    workflow = json.load(handle)
with open(state_path, encoding="utf-8") as handle:
    state = json.load(handle)

existing_id = ((state.get("workflows") or {}).get(file_name) or {}).get("id")
if existing_id:
    workflow["id"] = existing_id
else:
    workflow["id"] = workflow.get("id") or uuid4().hex

if file_name != "error-trigger.json" and error_workflow_id:
    settings = workflow.setdefault("settings", {})
    settings["errorWorkflow"] = error_workflow_id

with open(output_path, "w", encoding="utf-8") as handle:
    json.dump(workflow, handle, indent=2)
PY
}

import_staged_workflow() {
  local input_file="$1"
  local container_path="/tmp/$(basename "$input_file")"
  echo "  Importing $(basename "$input_file") ..."
  docker compose -f "$COMPOSE_FILE" exec -T n8n sh -lc "cat > '$container_path' && n8n import:workflow --input='$container_path' >/dev/null" <"$input_file"
}

activate_from_state() {
  local state_file="$1"
  local active_value="$2"
  local workflow_rows=()
  mapfile -t workflow_rows < <(
    python - "$state_file" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as handle:
    state = json.load(handle)

for file_name, workflow in (state.get("workflows") or {}).items():
    workflow_id = workflow.get("id")
    if workflow_id:
        print(f"{file_name}\t{workflow_id}")
PY
  )

  for row in "${workflow_rows[@]}"; do
    IFS=$'\t' read -r file_name workflow_id <<<"$row"
    if [[ -z "$workflow_id" ]]; then
      continue
    fi
    echo "  Setting $(workflow_name "$file_name") active=$active_value ..."
    if [[ "$active_value" == "true" ]]; then
      compose_exec n8n publish:workflow --id="$workflow_id" >/dev/null </dev/null
    else
      compose_exec n8n unpublish:workflow --id="$workflow_id" >/dev/null </dev/null
    fi
  done
}

restore_activation_state() {
  local original_state_file="$1"
  local current_state_file="$2"
  local workflow_rows=()
  mapfile -t workflow_rows < <(
    python - "$original_state_file" "$current_state_file" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as handle:
    original_state = json.load(handle)
with open(sys.argv[2], encoding="utf-8") as handle:
    current_state = json.load(handle)

for file_name, original in (original_state.get("workflows") or {}).items():
    current = (current_state.get("workflows") or {}).get(file_name, {})
    workflow_id = current.get("id")
    if not workflow_id:
        continue

    desired_active = original.get("active", False) if original.get("exists") else False
    print(
        f"{file_name}\t{workflow_id}\t"
        f"{'true' if desired_active else 'false'}\t"
        f"{'true' if original.get('exists') else 'false'}"
    )
PY
  )

  for row in "${workflow_rows[@]}"; do
    IFS=$'\t' read -r file_name workflow_id desired_active existed_before <<<"$row"
    if [[ -z "$workflow_id" ]]; then
      continue
    fi
    echo "  Restoring $(workflow_name "$file_name") active=$desired_active ..."
    if [[ "$desired_active" == "true" ]]; then
      compose_exec n8n publish:workflow --id="$workflow_id" >/dev/null </dev/null
    else
      compose_exec n8n unpublish:workflow --id="$workflow_id" >/dev/null </dev/null
    fi
    if [[ "$existed_before" != "true" ]]; then
      echo "  NOTE: $(workflow_name "$file_name") did not exist before. It was deactivated but not deleted." >&2
    fi
  done
}

restart_n8n() {
  echo "=== Restarting n8n ==="
  docker compose -f "$COMPOSE_FILE" restart n8n >/dev/null
}

apply_workflows() {
  local timestamp backup_dir error_state_file error_workflow_id

  wait_for_n8n

  timestamp="$(date +%Y%m%d-%H%M%S)"
  backup_dir="$BACKUP_ROOT/$timestamp"
  mkdir -p "$backup_dir/original" "$TMP_ROOT/staged"

  echo ""
  echo "=== Exporting current workflow state ==="
  export_all_workflows "$backup_dir/all-workflows.json"
  write_state "$backup_dir/all-workflows.json" "$backup_dir/original-state.json"
  ensure_no_duplicates "$backup_dir/original-state.json"
  create_cli_backup_tar "$backup_dir/cli-backup.tar"
  backup_existing_workflows "$backup_dir/original-state.json" "$backup_dir/original"

  echo ""
  echo "=== Importing error workflow ==="
  stage_workflow "error-trigger.json" "$backup_dir/original-state.json" "" "$TMP_ROOT/staged/error-trigger.json"
  import_staged_workflow "$TMP_ROOT/staged/error-trigger.json"

  export_all_workflows "$TMP_ROOT/after-error-import.json"
  error_state_file="$TMP_ROOT/after-error-state.json"
  write_state "$TMP_ROOT/after-error-import.json" "$error_state_file"
  ensure_no_duplicates "$error_state_file"
  error_workflow_id="$(state_field "$error_state_file" "error-trigger.json" "id")"
  if [[ -z "$error_workflow_id" ]]; then
    echo "ERROR: Error Trigger workflow ID could not be resolved after import." >&2
    exit 1
  fi

  echo ""
  echo "=== Importing primary workflows ==="
  for file_name in "quality-alert-created.json" "voice-exception-query.json" "shortage-reported.json"; do
    stage_workflow "$file_name" "$backup_dir/original-state.json" "$error_workflow_id" "$TMP_ROOT/staged/$file_name"
    import_staged_workflow "$TMP_ROOT/staged/$file_name"
  done

  echo ""
  echo "=== Resolving workflow IDs and activating ==="
  export_all_workflows "$backup_dir/deployed-workflows.json"
  write_state "$backup_dir/deployed-workflows.json" "$backup_dir/deployed-state.json"
  ensure_no_duplicates "$backup_dir/deployed-state.json"
  activate_from_state "$backup_dir/deployed-state.json" "true"

  echo ""
  restart_n8n
  echo ""
  echo "Done. Backups saved in: $backup_dir"
  echo "Rollback command: bash infrastructure/scripts/import-workflows.sh rollback \"$backup_dir\""
}

rollback_workflows() {
  local backup_dir="$1"
  if [[ -z "$backup_dir" ]]; then
    echo "Usage: bash infrastructure/scripts/import-workflows.sh rollback <backup-dir>" >&2
    exit 1
  fi
  if [[ ! -f "$backup_dir/original-state.json" ]]; then
    echo "ERROR: Missing rollback manifest: $backup_dir/original-state.json" >&2
    exit 1
  fi

  wait_for_n8n

  echo ""
  echo "=== Restoring original workflows ==="
  for file_name in "${WORKFLOW_FILES[@]}"; do
    if [[ -f "$backup_dir/original/$file_name" ]]; then
      import_staged_workflow "$backup_dir/original/$file_name"
    fi
  done

  export_all_workflows "$TMP_ROOT/post-rollback.json"
  write_state "$TMP_ROOT/post-rollback.json" "$TMP_ROOT/post-rollback-state.json"
  ensure_no_duplicates "$TMP_ROOT/post-rollback-state.json"

  echo ""
  echo "=== Restoring activation state ==="
  restore_activation_state "$backup_dir/original-state.json" "$TMP_ROOT/post-rollback-state.json"

  echo ""
  restart_n8n
  echo ""
  echo "Rollback completed. Verify the workflows in the n8n UI at https://<LAN-IP>/n8n/"
}

case "$MODE" in
  apply)
    apply_workflows
    ;;
  rollback)
    rollback_workflows "$ROLLBACK_DIR"
    ;;
  *)
    echo "Usage: bash infrastructure/scripts/import-workflows.sh [apply|rollback <backup-dir>]" >&2
    exit 1
    ;;
esac
