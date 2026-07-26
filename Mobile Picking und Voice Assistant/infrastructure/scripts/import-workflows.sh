#!/usr/bin/env bash
# Controlled n8n workflow rollout with explicit backup/import/activate/rollback
# phases. The registry (infrastructure/scripts/workflow_registry.py) is the
# sole source of truth for which files are managed, their activation order,
# their credential bindings, and which ones are test_only -- nothing here is
# hardcoded.
set -euo pipefail

MODE="${1:-}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
COMPOSE_FILE="${COMPOSE_FILE:-$ROOT_DIR/docker-compose.yml}"
WORKFLOW_DIR="${WORKFLOW_DIR:-$ROOT_DIR/n8n/workflows}"
# Overridable so tests can point at a synthetic registry/workflow-dir pair
# without touching the real one; the real script always uses the default.
REGISTRY_PATH="${REGISTRY_PATH:-$ROOT_DIR/n8n/workflow-registry.json}"
BACKUP_ROOT="$ROOT_DIR/n8n/backups"
TMP_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/n8n-import.XXXXXX")"
REGISTRY_PY="$SCRIPT_DIR/workflow_registry.py"
STAGE_PY="$SCRIPT_DIR/stage_workflow.py"
VERIFY_PY="$SCRIPT_DIR/verify-workflows.py"
CREDENTIALS_SH="$SCRIPT_DIR/provision-n8n-credentials.sh"

cleanup() {
  rm -rf "$TMP_ROOT"
}

trap cleanup EXIT

usage() {
  cat <<'EOF'
Usage:
  bash infrastructure/scripts/import-workflows.sh backup
  bash infrastructure/scripts/import-workflows.sh import <backup-dir>
  bash infrastructure/scripts/import-workflows.sh activate <backup-dir> [workflow-file ...]
  bash infrastructure/scripts/import-workflows.sh activate-test <backup-dir> <workflow-file> <run-id>
  bash infrastructure/scripts/import-workflows.sh deactivate-test <backup-dir> <workflow-file> <run-id>
  bash infrastructure/scripts/import-workflows.sh rollback <backup-dir>

Notes:
  - backup          exports every managed=true workflow into a timestamped directory
  - import          verifies contracts and credentials, stages every managed file with
                     metadata-only credential/error-workflow IDs, and imports it inactive
  - activate        publishes managed, production_activation=true workflows in registry
                     order unless explicit workflow files are provided; refuses any
                     workflow that is not production_activation=true, whose credentials
                     are not verified, or that collides with a duplicate n8n workflow name
  - activate-test    activates exactly one test_only=true, production_activation=false
                     workflow for a live smoke run identified by an operator-generated
                     RUN_ID, and writes a 0600 restoration manifest
  - deactivate-test  restores the exact prior active state recorded by the matching
                     activate-test call; a missing or mismatched RUN_ID is a hard failure
  - rollback        restores workflow files and activation state from the backup directory
EOF
}

registry_query() {
  # --registry must come after the subcommand: workflow_registry.py's
  # subparsers each redeclare --registry with their own default via a
  # shared `parents=[common]`, and argparse re-applies that default when
  # parsing the subcommand's own arguments -- silently discarding a
  # --registry given before the subcommand name.
  python "$REGISTRY_PY" "$@" --registry "$REGISTRY_PATH"
}

managed_files() {
  registry_query managed-files | python -c 'import json,sys; print("\n".join(json.load(sys.stdin)))'
}

activation_order_files() {
  registry_query activation-order | python -c 'import json,sys; print("\n".join(json.load(sys.stdin)))'
}

test_only_files() {
  registry_query test-only-files | python -c 'import json,sys; print("\n".join(json.load(sys.stdin)))'
}

credential_bindings_json() {
  local file_name="$1"
  registry_query credential-bindings "$file_name"
}

error_trigger_file() {
  registry_query error-trigger-file | python -c 'import json,sys; print(json.load(sys.stdin))'
}

stage_py() {
  python "$STAGE_PY" "$@"
}

run_verify_workflows() {
  echo "=== Verifying workflow contracts ==="
  (
    cd "$ROOT_DIR"
    python "$VERIFY_PY"
  )
}

run_verify_credentials() {
  echo "=== Verifying n8n credentials ==="
  bash "$CREDENTIALS_SH" verify >/dev/null
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
  compose_shell \
    "rm -f /tmp/codex-export-all.json && n8n export:workflow --all --output=/tmp/codex-export-all.json >/dev/null && cat /tmp/codex-export-all.json" \
    >"$output_file"
}

export_workflow_by_id() {
  local workflow_id="$1"
  local output_file="$2"
  compose_shell \
    "rm -f /tmp/codex-export-one.json && n8n export:workflow --id='$workflow_id' --output=/tmp/codex-export-one.json >/dev/null && cat /tmp/codex-export-one.json" \
    >"$output_file"
}

create_cli_backup_tar() {
  local output_file="$1"
  if ! compose_shell \
    "rm -rf /tmp/codex-workflow-backup && mkdir -p /tmp/codex-workflow-backup && n8n export:workflow --backup --output=/tmp/codex-workflow-backup >/dev/null && tar -C /tmp -cf - codex-workflow-backup" \
    >"$output_file"; then
    echo "WARNING: Could not create CLI backup tarball." >&2
    rm -f "$output_file"
  fi
}

write_state() {
  local export_file="$1"
  local state_file="$2"
  python - "$export_file" "$state_file" <<PY
import json
import sys
from collections import defaultdict

TARGETS = {}
for file_name in """$(managed_files)""".splitlines():
    if not file_name:
        continue
    TARGETS[file_name] = "$WORKFLOW_DIR/" + file_name

names_by_file = {}
for file_name, path in TARGETS.items():
    with open(path, encoding="utf-8") as handle:
        names_by_file[file_name] = json.load(handle).get("name")

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
for file_name, workflow_name in names_by_file.items():
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

has_duplicate() {
  local state_file="$1"
  local workflow_name="$2"
  python - "$state_file" "$workflow_name" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as handle:
    state = json.load(handle)
print("true" if sys.argv[2] in (state.get("duplicates") or {}) else "false")
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
    echo "  Backing up $file_name ..."
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

# Build the {"logical_name","credential_type"} -> {id,name,type} index from
# the credential-provisioning metadata (see provision-n8n-credentials.sh
# verify), keyed exactly like workflow_registry.py's credential_bindings.
build_credential_index_json() {
  bash "$CREDENTIALS_SH" verify
}

stage_workflow_file() {
  local file_name="$1"
  local state_file="$2"
  local error_workflow_id="$3"
  local credential_metadata_file="$4"
  local output_file="$5"

  python - "$WORKFLOW_DIR/$file_name" "$state_file" "$file_name" \
    "$error_workflow_id" "$credential_metadata_file" "$STAGE_PY" \
    "$REGISTRY_PY" "$output_file" <<'PY'
import json
import subprocess
import sys

(
    source_path, state_path, file_name, error_workflow_id,
    credential_metadata_path, stage_py, registry_py, output_path,
) = sys.argv[1:9]

with open(source_path, encoding="utf-8") as handle:
    source = json.load(handle)
with open(state_path, encoding="utf-8") as handle:
    state = json.load(handle)
with open(credential_metadata_path, encoding="utf-8") as handle:
    credential_metadata = json.load(handle)

bindings = json.loads(
    subprocess.run(
        ["python", registry_py, "credential-bindings", file_name],
        check=True, capture_output=True, text=True,
    ).stdout
)

credentials_by_name_type = {
    (item["name"], item["type"]): item for item in credential_metadata.get("credentials", [])
}
credential_index = [
    {
        "logical_name": binding["logical_name"],
        "credential_type": binding["credential_type"],
        "credential": credentials_by_name_type.get(
            (binding["logical_name"], binding["credential_type"])
        ),
    }
    for binding in bindings
]

existing_id = ((state.get("workflows") or {}).get(file_name) or {}).get("id")

payload = {
    "source": source,
    "bindings": bindings,
    "credential_index": credential_index,
    "existing_workflow_id": existing_id,
    "error_workflow_id": error_workflow_id or None,
}

result = subprocess.run(
    ["python", stage_py, "stage"],
    input=json.dumps(payload), check=True, capture_output=True, text=True,
)

with open(output_path, "w", encoding="utf-8") as handle:
    handle.write(result.stdout)
PY
}

import_staged_workflow() {
  local input_file="$1"
  local container_path="/tmp/$(basename "$input_file")"
  echo "  Importing $(basename "$input_file") ..."
  docker compose -f "$COMPOSE_FILE" exec -T n8n sh -lc \
    "cat > '$container_path' && n8n import:workflow --input='$container_path' >/dev/null" \
    <"$input_file"
}

set_activation_state() {
  local state_file="$1"
  local active_value="$2"
  shift 2

  local file_args=("$@")
  for file_name in "${file_args[@]}"; do
    local workflow_id
    workflow_id="$(state_field "$state_file" "$file_name" "id")"
    if [[ -z "$workflow_id" ]]; then
      continue
    fi
    echo "  Setting $file_name active=$active_value ..."
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
    echo "  Restoring $file_name active=$desired_active ..."
    if [[ "$desired_active" == "true" ]]; then
      compose_exec n8n publish:workflow --id="$workflow_id" >/dev/null </dev/null
    else
      compose_exec n8n unpublish:workflow --id="$workflow_id" >/dev/null </dev/null
    fi
    if [[ "$existed_before" != "true" ]]; then
      echo "  NOTE: $file_name did not exist before. It was deactivated but not deleted." >&2
    fi
  done
}

restart_n8n() {
  echo "=== Restarting n8n ==="
  docker compose -f "$COMPOSE_FILE" restart n8n >/dev/null
}

backup_workflows() {
  wait_for_n8n

  local timestamp backup_dir
  timestamp="$(date +%Y%m%d-%H%M%S)"
  backup_dir="$BACKUP_ROOT/$timestamp"
  mkdir -p "$backup_dir/original"

  echo ""
  echo "=== Exporting current workflow state ==="
  export_all_workflows "$backup_dir/all-workflows.json"
  write_state "$backup_dir/all-workflows.json" "$backup_dir/original-state.json"
  ensure_no_duplicates "$backup_dir/original-state.json"
  create_cli_backup_tar "$backup_dir/cli-backup.tar"
  backup_existing_workflows "$backup_dir/original-state.json" "$backup_dir/original"

  echo ""
  echo "Backup created: $backup_dir"
}

import_workflows() {
  local backup_dir="$1"
  if [[ -z "$backup_dir" || ! -f "$backup_dir/original-state.json" ]]; then
    echo "ERROR: import requires an existing backup directory with original-state.json" >&2
    exit 1
  fi

  run_verify_workflows
  run_verify_credentials
  wait_for_n8n
  mkdir -p "$TMP_ROOT/staged"

  local credential_metadata_file="$TMP_ROOT/credential-metadata.json"
  build_credential_index_json >"$credential_metadata_file"
  chmod 600 "$credential_metadata_file"

  # Resolved from the registry (the single managed authentication=
  # error_trigger_v1 workflow), never a hardcoded filename; fails closed if
  # the registry does not have exactly one such entry.
  local error_trigger
  error_trigger="$(error_trigger_file)"
  if [[ -z "$error_trigger" ]]; then
    echo "ERROR: could not resolve the managed error-trigger workflow from the registry" >&2
    exit 1
  fi

  echo ""
  echo "=== Importing error workflow ($error_trigger) ==="
  stage_workflow_file "$error_trigger" "$backup_dir/original-state.json" "" \
    "$credential_metadata_file" "$TMP_ROOT/staged/$error_trigger"
  import_staged_workflow "$TMP_ROOT/staged/$error_trigger"

  export_all_workflows "$TMP_ROOT/after-error-import.json"
  write_state "$TMP_ROOT/after-error-import.json" "$TMP_ROOT/after-error-state.json"
  ensure_no_duplicates "$TMP_ROOT/after-error-state.json"

  local error_workflow_id
  error_workflow_id="$(state_field "$TMP_ROOT/after-error-state.json" "$error_trigger" "id")"
  if [[ -z "$error_workflow_id" ]]; then
    echo "ERROR: Error Trigger workflow ID could not be resolved after import." >&2
    exit 1
  fi

  echo ""
  echo "=== Importing remaining managed workflows inactive ==="
  while IFS= read -r file_name; do
    if [[ -z "$file_name" || "$file_name" == "$error_trigger" ]]; then
      continue
    fi
    stage_workflow_file "$file_name" "$backup_dir/original-state.json" "$error_workflow_id" \
      "$credential_metadata_file" "$TMP_ROOT/staged/$file_name"
    import_staged_workflow "$TMP_ROOT/staged/$file_name"
  done < <(managed_files)

  export_all_workflows "$backup_dir/imported-workflows.json"
  write_state "$backup_dir/imported-workflows.json" "$backup_dir/imported-state.json"
  ensure_no_duplicates "$backup_dir/imported-state.json"

  echo ""
  echo "=== Ensuring imported workflows stay inactive ==="
  mapfile -t all_managed < <(managed_files)
  set_activation_state "$backup_dir/imported-state.json" "false" "${all_managed[@]}"

  echo ""
  echo "Import completed. Imported workflow manifest: $backup_dir/imported-state.json"
  echo "Next step: bash infrastructure/scripts/import-workflows.sh activate \"$backup_dir\""
}

activate_workflows() {
  local backup_dir="$1"
  shift

  if [[ -z "$backup_dir" || ! -f "$backup_dir/imported-state.json" ]]; then
    echo "ERROR: activate requires an import backup directory with imported-state.json" >&2
    exit 1
  fi

  run_verify_workflows

  local credentials_verified="true"
  if ! run_verify_credentials; then
    credentials_verified="false"
  fi

  wait_for_n8n

  local files_to_activate=()
  if [[ $# -gt 0 ]]; then
    files_to_activate=("$@")
  else
    mapfile -t files_to_activate < <(activation_order_files)
  fi

  for file_name in "${files_to_activate[@]}"; do
    local workflow_name
    workflow_name="$(state_field "$backup_dir/imported-state.json" "$file_name" "name")"
    local duplicate
    duplicate="$(has_duplicate "$backup_dir/imported-state.json" "$workflow_name")"
    local spec_json
    spec_json="$(python - "$file_name" <<PY
import json
from pathlib import Path
import sys
sys.path.insert(0, "$ROOT_DIR")
from infrastructure.scripts.workflow_registry import load_registry
registry = load_registry(Path("$REGISTRY_PATH"))
spec = registry.by_file("$file_name")
print(json.dumps({
    "file": spec.file,
    "production_activation": spec.production_activation,
    "test_only": spec.test_only,
}))
PY
)"
    if ! python "$STAGE_PY" assert-activatable <<PY
{"spec": $spec_json, "credentials_verified": $credentials_verified, "duplicate": $duplicate}
PY
    then
      echo "ERROR: refusing to activate $file_name" >&2
      exit 1
    fi
  done

  echo ""
  echo "=== Activating workflows ==="
  set_activation_state "$backup_dir/imported-state.json" "true" "${files_to_activate[@]}"

  export_all_workflows "$backup_dir/activated-workflows.json"
  write_state "$backup_dir/activated-workflows.json" "$backup_dir/activated-state.json"
  ensure_no_duplicates "$backup_dir/activated-state.json"

  echo ""
  restart_n8n
  echo ""
  echo "Activation completed. Remember to run the documented smoke tests before activating the next workflow."
}

activate_test_workflow() {
  local backup_dir="$1"
  local file_name="$2"
  local run_id="$3"

  if [[ -z "$backup_dir" || -z "$file_name" || -z "$run_id" ]]; then
    usage >&2
    exit 1
  fi

  local registered
  registered="false"
  while IFS= read -r candidate; do
    if [[ "$candidate" == "$file_name" ]]; then
      registered="true"
    fi
  done < <(test_only_files)
  if [[ "$registered" != "true" ]]; then
    echo "ERROR: $file_name is not a registered test_only workflow" >&2
    exit 1
  fi

  local spec_json
  spec_json="$(python - "$file_name" <<PY
import json
from pathlib import Path
import sys
sys.path.insert(0, "$ROOT_DIR")
from infrastructure.scripts.workflow_registry import load_registry
registry = load_registry(Path("$REGISTRY_PATH"))
spec = registry.by_file("$file_name")
print(json.dumps({
    "file": spec.file,
    "production_activation": spec.production_activation,
    "test_only": spec.test_only,
}))
PY
)"
  mapfile -t dependency_files < <(activation_order_files)
  local dependency_files_json
  dependency_files_json="$(printf '%s\n' "${dependency_files[@]}" | python -c 'import json,sys; print(json.dumps([line for line in sys.stdin.read().splitlines() if line]))')"

  if ! python "$STAGE_PY" assert-test-activatable <<PY
{"spec": $spec_json, "run_id": "$run_id", "dependency_files": $dependency_files_json}
PY
  then
    echo "ERROR: refusing activate-test for $file_name" >&2
    exit 1
  fi

  # activate-test must never publish a workflow while contract or credential
  # verification is failing -- run both before touching the live instance,
  # exactly like `import` and `activate` already do.
  run_verify_workflows
  run_verify_credentials

  wait_for_n8n

  export_all_workflows "$TMP_ROOT/pre-activate-test.json"
  write_state "$TMP_ROOT/pre-activate-test.json" "$TMP_ROOT/pre-activate-test-state.json"
  local workflow_id previous_active
  workflow_id="$(state_field "$TMP_ROOT/pre-activate-test-state.json" "$file_name" "id")"
  previous_active="$(state_field "$TMP_ROOT/pre-activate-test-state.json" "$file_name" "active")"
  if [[ -z "$workflow_id" ]]; then
    echo "ERROR: $file_name is not imported; run 'import' first" >&2
    exit 1
  fi

  local manifest_file="$backup_dir/activate-test-$run_id.json"
  python "$STAGE_PY" build-manifest <<PY >"$manifest_file"
{"file_name": "$file_name", "run_id": "$run_id", "workflow_id": "$workflow_id", "previous_active": $previous_active}
PY
  chmod 600 "$manifest_file"

  echo "  Activating $file_name for live smoke run $run_id ..."
  compose_exec n8n publish:workflow --id="$workflow_id" >/dev/null </dev/null
  echo "Restoration manifest written: $manifest_file"
  echo "Remember to call deactivate-test with the same RUN_ID when the smoke run finishes."
}

deactivate_test_workflow() {
  local backup_dir="$1"
  local file_name="$2"
  local run_id="$3"

  if [[ -z "$backup_dir" || -z "$file_name" || -z "$run_id" ]]; then
    usage >&2
    exit 1
  fi

  local manifest_file="$backup_dir/activate-test-$run_id.json"
  if [[ ! -f "$manifest_file" ]]; then
    echo "ERROR: no restoration manifest for $file_name / $run_id at $manifest_file" >&2
    exit 1
  fi

  local manifest_json
  manifest_json="$(cat "$manifest_file")"
  local restored_active
  if ! restored_active="$(python "$STAGE_PY" restore-from-manifest <<PY
{"manifest": $manifest_json, "run_id": "$run_id", "file_name": "$file_name"}
PY
  )"; then
    echo "ERROR: could not restore $file_name for run $run_id (RUN_ID or file mismatch, or missing manifest)" >&2
    exit 1
  fi

  local workflow_id
  workflow_id="$(python -c "import json; print(json.loads('''$manifest_json''')['workflow_id'])")"

  echo "  Restoring $file_name to active=$restored_active for run $run_id ..."
  if [[ "$restored_active" == "true" ]]; then
    compose_exec n8n publish:workflow --id="$workflow_id" >/dev/null </dev/null
  else
    compose_exec n8n unpublish:workflow --id="$workflow_id" >/dev/null </dev/null
  fi
  rm -f "$manifest_file"
}

rollback_workflows() {
  local backup_dir="$1"
  if [[ -z "$backup_dir" || ! -f "$backup_dir/original-state.json" ]]; then
    echo "ERROR: Missing rollback manifest: $backup_dir/original-state.json" >&2
    exit 1
  fi

  wait_for_n8n

  echo ""
  echo "=== Restoring original workflows ==="
  while IFS= read -r file_name; do
    if [[ -n "$file_name" && -f "$backup_dir/original/$file_name" ]]; then
      import_staged_workflow "$backup_dir/original/$file_name"
    fi
  done < <(managed_files)

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
  backup)
    backup_workflows
    ;;
  import)
    import_workflows "${2:-}"
    ;;
  activate)
    if [[ -z "${2:-}" ]]; then
      usage >&2
      exit 1
    fi
    backup_dir="$2"
    shift 2
    activate_workflows "$backup_dir" "$@"
    ;;
  activate-test)
    activate_test_workflow "${2:-}" "${3:-}" "${4:-}"
    ;;
  deactivate-test)
    deactivate_test_workflow "${2:-}" "${3:-}" "${4:-}"
    ;;
  rollback)
    rollback_workflows "${2:-}"
    ;;
  *)
    usage >&2
    exit 1
    ;;
esac
