#!/bin/bash
# Offline, verified clone of a Docker volume holding a PostgreSQL data
# directory, for disposable migration testing (Task 13 / Task 15).
#
# Usage:
#   clone-postgres-volume.sh create SOURCE_VOLUME COPY_VOLUME MANIFEST_DIR
#   clone-postgres-volume.sh verify SOURCE_VOLUME COPY_VOLUME MANIFEST_DIR
#   clone-postgres-volume.sh delete COPY_VOLUME MANIFEST_DIR
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
#      (excluding postmaster.pid) and requires the manifests to be
#      byte-identical, plus matching PG_VERSION;
#   6. records source/copy volume IDs and creation UTC in a mode-0600
#      manifest file inside a mode-0700 directory.
#
# verify: recomputes both manifests and re-checks they match.
#
# delete: refuses to remove the recorded source volume ID, removes only
# the recorded copy volume, and removes its manifest directory.
set -euo pipefail

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
        find . -type f ! -name "postmaster.pid" -print0 \
            | sort -z \
            | xargs -0 sha256sum
    ' > "$out_file"
}

pg_version_of() {
    local volume="$1"
    docker run --rm --network none -v "$volume:/vol:ro" alpine:3.20 \
        sh -c 'cat /vol/PG_VERSION 2>/dev/null || true'
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

    local source_id copy_id created_utc
    source_id="$(volume_id "$source")"
    copy_id="$(volume_id "$copy")"
    created_utc="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    {
        printf 'source_volume=%s\n' "$source_id"
        printf 'copy_volume=%s\n' "$copy_id"
        printf 'created_utc=%s\n' "$created_utc"
    } > "$manifest_dir/clone.manifest"
    chmod 0600 "$manifest_dir/clone.manifest" "$manifest_dir/manifest.sha256" \
        "$manifest_dir/source.sha256" "$manifest_dir/copy.sha256"

    log "Clone verified: $copy is a byte-identical offline copy of $source"
}

cmd_verify() {
    local source="${1:?SOURCE_VOLUME required}"
    local copy="${2:?COPY_VOLUME required}"
    local manifest_dir="${3:?MANIFEST_DIR required}"

    require_docker
    [ -f "$manifest_dir/clone.manifest" ] || fail "no clone.manifest found in $manifest_dir"

    write_manifest "$source" "$manifest_dir/source.sha256.verify"
    write_manifest "$copy" "$manifest_dir/copy.sha256.verify"

    if ! diff -q "$manifest_dir/source.sha256.verify" "$manifest_dir/copy.sha256.verify" >/dev/null 2>&1; then
        fail "manifest.sha256 mismatch on verify between source and copy"
    fi

    if ! diff -q "$manifest_dir/copy.sha256.verify" "$manifest_dir/manifest.sha256" >/dev/null 2>&1; then
        fail "recorded manifest.sha256 no longer matches current copy volume contents"
    fi

    log "Verify OK: $copy still matches recorded manifest.sha256"
}

cmd_delete() {
    local copy="${1:?COPY_VOLUME required}"
    local manifest_dir="${2:?MANIFEST_DIR required}"

    require_docker
    [ -f "$manifest_dir/clone.manifest" ] || fail "no clone.manifest found in $manifest_dir"

    local recorded_source_id recorded_copy_id
    recorded_source_id="$(grep '^source_volume=' "$manifest_dir/clone.manifest" | cut -d= -f2-)"
    recorded_copy_id="$(grep '^copy_volume=' "$manifest_dir/clone.manifest" | cut -d= -f2-)"

    if [ "$copy" = "$recorded_source_id" ]; then
        fail "refusing to delete recorded source volume: $copy"
    fi

    local current_copy_id
    current_copy_id="$(volume_id "$copy" || true)"
    if [ -n "$current_copy_id" ] && [ "$current_copy_id" != "$recorded_copy_id" ]; then
        fail "volume $copy does not match the recorded copy volume ID; refusing to delete"
    fi

    docker volume rm "$copy" >/dev/null
    rm -rf "$manifest_dir"

    log "Deleted copy volume $copy and manifest directory $manifest_dir"
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
        *)
            echo "Usage: $0 {create|verify|delete} ..." >&2
            exit 1
            ;;
    esac
}

main "$@"
