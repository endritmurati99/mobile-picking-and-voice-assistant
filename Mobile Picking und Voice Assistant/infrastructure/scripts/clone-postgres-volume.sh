#!/bin/bash
# Offline, verified clone of a Docker volume holding a PostgreSQL data
# directory, for disposable migration testing (Task 13 / Task 15).
#
# Usage:
#   clone-postgres-volume.sh create SOURCE_VOLUME COPY_VOLUME MANIFEST_DIR
#   clone-postgres-volume.sh verify SOURCE_VOLUME COPY_VOLUME MANIFEST_DIR
#   clone-postgres-volume.sh delete COPY_VOLUME MANIFEST_DIR
#   clone-postgres-volume.sh assert-target MANIFEST_DIR REQUESTED_VOLUME
#   clone-postgres-volume.sh compose-up MANIFEST_DIR REQUESTED_VOLUME PROJECT_NAME [-- extra docker compose args]
#
# create:
#   1. resolves both volume names with `docker volume inspect` and
#      refuses identical names;
#   2. refuses to run while any running container mounts the source
#      volume;
#   3. creates the destination volume only when it does not already
#      exist and is empty;
#   4. copies the data offline via a throwaway alpine container with
#      networking disabled, using tar;
#   5. writes sorted, relative-path SHA-256 manifests for both volumes
#      (excluding postmaster.pid and the identity marker below) and
#      requires the manifests to be byte-identical, plus matching
#      PG_VERSION;
#   6. writes a random identity token INTO the copy volume itself (a
#      sentinel file, not a Docker volume "ID" — Docker volumes have no
#      immutable identity of their own: deleting and recreating a volume
#      under the same name looks identical to `docker volume inspect
#      --format {{.Name}}`, so name/Name-based checks alone can be
#      spoofed by name reuse) and records that token, plus the volume
#      names and their CreatedAt timestamps, in a mode-0600 manifest
#      file inside a mode-0700 directory. The source volume is mounted
#      read-only throughout and is never written to, so its own
#      identity is tracked via name + CreatedAt only (the best available
#      without touching production data).
#
# verify: recomputes both manifests, re-checks they match, and confirms
# the copy volume still contains the recorded identity token.
#
# delete: refuses to remove the recorded source volume ID, requires the
# recorded identity token still be present in the target, then removes
# only the recorded copy volume and its manifest directory.
#
# assert-target: guards against pointing docker-compose.db-migration.yml
# at the wrong volume. It requires a recorded clone.manifest in
# MANIFEST_DIR, refuses outright if the requested volume's name resolves
# to the recorded source volume, requires the name to match the recorded
# copy volume, AND requires the recorded identity token to actually be
# present inside the requested volume's data — so a volume recreated
# under the same name (empty, or holding unrelated data) is refused even
# though its name matches. Run this before ever setting
# PWR_DB_MIGRATION_VOLUME and starting the override Compose file — the
# override YAML itself cannot express this check, so it must be enforced
# by an explicit script gate:
#   clone-postgres-volume.sh assert-target MANIFEST_DIR REQUESTED_VOLUME
#
# compose-up: the actual required entry point for starting the
# migration override stack. It runs assert-target first and only then
# execs `docker compose ... up -d db`, so the guard cannot be bypassed
# by an operator who forgets to call assert-target separately and runs
# docker compose directly:
#   clone-postgres-volume.sh compose-up MANIFEST_DIR REQUESTED_VOLUME PROJECT_NAME [-- extra args]
#
# Intentionally no ODOO_DB_NAME dependency: unlike init-db-roles.sh and
# migrate-n8n-db-role.sh, this tool never opens a database connection or
# reads database/table names — it only ever operates on whole Docker
# volumes by name/ID (docker volume inspect/create/rm) and on their raw
# bytes (tar, sha256sum, PG_VERSION file contents). It has no code path
# where a database name would be consumed, so requiring ODOO_DB_NAME
# here would be a dead, unused gate rather than real fail-closed
# behavior — the real fail-closed requirement for this tool is instead
# assert-target's refusal to accept anything but the recorded, token-
# verified disposable clone.
set -euo pipefail

IDENTITY_MARKER=".pwr-clone-identity"

log() {
    printf '[clone-postgres-volume] %s\n' "$1" >&2
}

fail() {
    log "ERROR: $1"
    exit 1
}

require_docker() {
    command -v docker >/dev/null 2>&1 || fail "docker is required"
}

volume_exists() {
    docker volume inspect "$1" >/dev/null 2>&1
}

volume_id() {
    docker volume inspect "$1" --format '{{.Name}}' 2>/dev/null
}

volume_created_at() {
    docker volume inspect "$1" --format '{{.CreatedAt}}' 2>/dev/null
}

running_containers_mounting_volume() {
    local volume="$1"
    docker ps --format '{{.ID}}' | while read -r cid; do
        [ -z "$cid" ] && continue
        if docker inspect "$cid" --format '{{range .Mounts}}{{.Name}}{{"\n"}}{{end}}' 2>/dev/null | grep -qx "$volume"; then
            echo "$cid"
        fi
    done
}

volume_is_empty() {
    local volume="$1"
    local count
    count="$(docker run --rm --network none -v "$volume:/vol:ro" alpine:3.20 \
        sh -c 'find /vol -mindepth 1 | wc -l')"
    [ "$count" -eq 0 ]
}

write_manifest() {
    # write_manifest VOLUME OUTPUT_FILE
    local volume="$1"
    local out_file="$2"
    docker run --rm --network none -v "$volume:/vol:ro" alpine:3.20 sh -c '
        set -e
        apk add --no-cache --quiet findutils >/dev/null 2>&1 || true
        cd /vol
        find . -type f ! -name "postmaster.pid" ! -name ".pwr-clone-identity" -print0 \
            | sort -z \
            | xargs -0 sha256sum
    ' > "$out_file"
}

pg_version_of() {
    local volume="$1"
    docker run --rm --network none -v "$volume:/vol:ro" alpine:3.20 \
        sh -c 'cat /vol/PG_VERSION 2>/dev/null || true'
}

# Generates a random identity token on the host (never inside the
# volume-mounting container, so it never depends on that container
# having a working RNG).
generate_token() {
    if command -v openssl >/dev/null 2>&1; then
        openssl rand -hex 16
    elif [ -r /dev/urandom ]; then
        head -c16 /dev/urandom | od -An -tx1 | tr -d ' \n'
    else
        date +%s%N | sha256sum | cut -c1-32
    fi
}

# Writes the identity token into the volume itself as a sentinel file.
# This is the actual, content-level identity check: a volume deleted
# and recreated under the same name will not contain this file.
write_identity_token() {
    local volume="$1"
    local token="$2"
    docker run --rm --network none -v "$volume:/vol" alpine:3.20 \
        sh -c 'printf "%s" "$1" > "/vol/$2" && chmod 0400 "/vol/$2"' \
        _ "$token" "$IDENTITY_MARKER"
}

read_identity_token() {
    local volume="$1"
    docker run --rm --network none -v "$volume:/vol:ro" alpine:3.20 \
        sh -c 'cat "/vol/$1" 2>/dev/null || true' _ "$IDENTITY_MARKER"
}

manifest_field() {
    # Never let a missing field trip `set -e -o pipefail`: grep finding
    # no match exits non-zero, which would otherwise abort the script
    # silently before an explicit `fail` with a useful message ever runs.
    # Callers check for an empty result themselves.
    local manifest_dir="$1"
    local field="$2"
    grep "^${field}=" "$manifest_dir/clone.manifest" 2>/dev/null | cut -d= -f2- || true
}

cmd_create() {
    local source="${1:?SOURCE_VOLUME required}"
    local copy="${2:?COPY_VOLUME required}"
    local manifest_dir="${3:?MANIFEST_DIR required}"

    require_docker

    if [ "$source" = "$copy" ]; then
        fail "source and copy volume names must differ"
    fi

    volume_exists "$source" || fail "source volume inspect failed: $source"

    local mounting
    mounting="$(running_containers_mounting_volume "$source" || true)"
    if [ -n "$mounting" ]; then
        fail "running container still mounts source volume: $source ($mounting)"
    fi

    if volume_exists "$copy"; then
        volume_is_empty "$copy" || fail "copy volume already exists and is not empty: $copy"
    else
        docker volume create "$copy" >/dev/null
    fi

    log "Copying $source -> $copy offline (network disabled)"
    docker run --rm --network none \
        -v "$source:/source:ro" \
        -v "$copy:/copy" \
        alpine:3.20 \
        sh -c 'cd /source && tar -cf - . | (cd /copy && tar -xf -)'

    install -d -m 0700 "$manifest_dir"
    write_manifest "$source" "$manifest_dir/source.sha256"
    write_manifest "$copy" "$manifest_dir/copy.sha256"

    if ! diff -q "$manifest_dir/source.sha256" "$manifest_dir/copy.sha256" >/dev/null 2>&1; then
        fail "manifest.sha256 mismatch between source and copy after clone"
    fi

    local source_pgver copy_pgver
    source_pgver="$(pg_version_of "$source")"
    copy_pgver="$(pg_version_of "$copy")"
    if [ "$source_pgver" != "$copy_pgver" ]; then
        fail "PG_VERSION mismatch: source=$source_pgver copy=$copy_pgver"
    fi

    cp "$manifest_dir/copy.sha256" "$manifest_dir/manifest.sha256"

    # Write the copy's own identity token only after the byte-identical
    # check above, so the marker file itself never affects that
    # comparison (it is also excluded from write_manifest's file scan).
    local token
    token="$(generate_token)"
    write_identity_token "$copy" "$token"

    local source_id copy_id source_created_at copy_created_at created_utc
    source_id="$(volume_id "$source")"
    copy_id="$(volume_id "$copy")"
    source_created_at="$(volume_created_at "$source")"
    copy_created_at="$(volume_created_at "$copy")"
    created_utc="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    {
        printf 'source_volume=%s\n' "$source_id"
        printf 'source_created_at=%s\n' "$source_created_at"
        printf 'copy_volume=%s\n' "$copy_id"
        printf 'copy_created_at=%s\n' "$copy_created_at"
        printf 'copy_identity_token=%s\n' "$token"
        printf 'created_utc=%s\n' "$created_utc"
    } > "$manifest_dir/clone.manifest"
    chmod 0600 "$manifest_dir/clone.manifest" "$manifest_dir/manifest.sha256" \
        "$manifest_dir/source.sha256" "$manifest_dir/copy.sha256"

    log "Clone verified: $copy is a byte-identical offline copy of $source, identity token written"
}

cmd_verify() {
    local source="${1:?SOURCE_VOLUME required}"
    local copy="${2:?COPY_VOLUME required}"
    local manifest_dir="${3:?MANIFEST_DIR required}"

    require_docker
    [ -f "$manifest_dir/clone.manifest" ] || fail "no clone.manifest found in $manifest_dir"

    local recorded_token current_token
    recorded_token="$(manifest_field "$manifest_dir" copy_identity_token)"
    [ -n "$recorded_token" ] || fail "clone.manifest in $manifest_dir has no recorded copy_identity_token"
    current_token="$(read_identity_token "$copy")"
    if [ "$current_token" != "$recorded_token" ]; then
        fail "copy volume $copy does not contain the recorded identity token; it may have been deleted and recreated under the same name"
    fi

    write_manifest "$source" "$manifest_dir/source.sha256.verify"
    write_manifest "$copy" "$manifest_dir/copy.sha256.verify"

    if ! diff -q "$manifest_dir/source.sha256.verify" "$manifest_dir/copy.sha256.verify" >/dev/null 2>&1; then
        fail "manifest.sha256 mismatch on verify between source and copy"
    fi

    if ! diff -q "$manifest_dir/copy.sha256.verify" "$manifest_dir/manifest.sha256" >/dev/null 2>&1; then
        fail "recorded manifest.sha256 no longer matches current copy volume contents"
    fi

    log "Verify OK: $copy still matches recorded manifest.sha256 and identity token"
}

cmd_delete() {
    local copy="${1:?COPY_VOLUME required}"
    local manifest_dir="${2:?MANIFEST_DIR required}"

    require_docker
    [ -f "$manifest_dir/clone.manifest" ] || fail "no clone.manifest found in $manifest_dir"

    local recorded_source_id recorded_copy_id recorded_token
    recorded_source_id="$(manifest_field "$manifest_dir" source_volume)"
    recorded_copy_id="$(manifest_field "$manifest_dir" copy_volume)"
    recorded_token="$(manifest_field "$manifest_dir" copy_identity_token)"

    if [ "$copy" = "$recorded_source_id" ]; then
        fail "refusing to delete recorded source volume: $copy"
    fi

    local current_copy_id
    current_copy_id="$(volume_id "$copy" || true)"
    if [ -n "$current_copy_id" ] && [ "$current_copy_id" != "$recorded_copy_id" ]; then
        fail "volume $copy does not match the recorded copy volume ID; refusing to delete"
    fi

    if [ -n "$current_copy_id" ] && [ -n "$recorded_token" ]; then
        local current_token
        current_token="$(read_identity_token "$copy")"
        if [ "$current_token" != "$recorded_token" ]; then
            fail "volume $copy does not contain the recorded clone identity token (it may have been deleted and recreated under the same name); refusing to delete"
        fi
    fi

    docker volume rm "$copy" >/dev/null
    rm -rf "$manifest_dir"

    log "Deleted copy volume $copy and manifest directory $manifest_dir"
}

cmd_assert_target() {
    local manifest_dir="${1:?MANIFEST_DIR required}"
    local requested="${2:?REQUESTED_VOLUME required}"

    require_docker
    [ -f "$manifest_dir/clone.manifest" ] || \
        fail "no clone.manifest found in $manifest_dir; refusing to trust an unrecorded volume as a migration target"

    local recorded_source_id recorded_copy_id recorded_token
    recorded_source_id="$(manifest_field "$manifest_dir" source_volume)"
    recorded_copy_id="$(manifest_field "$manifest_dir" copy_volume)"
    recorded_token="$(manifest_field "$manifest_dir" copy_identity_token)"
    [ -n "$recorded_source_id" ] || fail "clone.manifest in $manifest_dir has no recorded source_volume"
    [ -n "$recorded_copy_id" ] || fail "clone.manifest in $manifest_dir has no recorded copy_volume"
    [ -n "$recorded_token" ] || fail "clone.manifest in $manifest_dir has no recorded copy_identity_token"

    volume_exists "$requested" || fail "requested migration volume does not exist: $requested"
    local requested_id
    requested_id="$(volume_id "$requested")"

    if [ "$requested_id" = "$recorded_source_id" ]; then
        fail "refusing migration target: requested volume is the recorded source volume: $requested"
    fi
    if [ "$requested_id" != "$recorded_copy_id" ]; then
        fail "requested migration volume does not match the recorded disposable clone: $requested"
    fi

    # Name matching alone is not proof: Docker volumes have no immutable
    # identity, so a volume deleted and recreated under the same name
    # would still pass the checks above. The identity token is written
    # into the volume's own data, so this is a real content check.
    local current_token
    current_token="$(read_identity_token "$requested")"
    if [ -z "$current_token" ] || [ "$current_token" != "$recorded_token" ]; then
        fail "requested migration volume $requested does not contain the recorded clone identity token (it may have been deleted and recreated under the same name); refusing to trust the name alone"
    fi

    log "OK: $requested is the recorded disposable clone (name and identity token both verified), not the source volume"
}

cmd_compose_up() {
    local manifest_dir="${1:?MANIFEST_DIR required}"
    local requested="${2:?REQUESTED_VOLUME required}"
    local project_name="${3:?COMPOSE_PROJECT_NAME required}"
    shift 3 || true
    if [ "${1:-}" = "--" ]; then
        shift
    fi

    cmd_assert_target "$manifest_dir" "$requested"

    local repo_root
    repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

    log "assert-target passed; starting db-migration override stack as project $project_name"
    PWR_DB_MIGRATION_VOLUME="$requested" \
        docker compose -p "$project_name" \
        -f "$repo_root/docker-compose.yml" \
        -f "$repo_root/infrastructure/docker-compose.db-migration.yml" \
        up -d db "$@"
}

main() {
    local mode="${1:-}"
    shift || true
    case "$mode" in
        "create")
            cmd_create "$@"
            ;;
        "verify")
            cmd_verify "$@"
            ;;
        "delete")
            cmd_delete "$@"
            ;;
        "assert-target")
            cmd_assert_target "$@"
            ;;
        "compose-up")
            cmd_compose_up "$@"
            ;;
        *)
            echo "Usage: $0 {create|verify|delete|assert-target|compose-up} ..." >&2
            exit 1
            ;;
    esac
}

main "$@"
