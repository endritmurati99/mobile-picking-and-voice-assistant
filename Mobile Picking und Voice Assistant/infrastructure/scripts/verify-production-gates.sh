#!/usr/bin/env bash
# "Is this deployment actually in the production posture?" (Foundation Task 15)
#
# Every check here interrogates the RUNNING SYSTEM. None of them greps a file
# for a reassuring string. That distinction is the whole point: this programme
# has already shipped eleven guards that were true of a file and false of the
# machine, including a Caddy snippet that blocked nothing while the test that
# "proved" it only read the Caddyfile.
#
# So:
#   * published ports come from `docker compose ps`, not from the ports: block;
#   * the deny-list is measured by asking the live edge for those URLs;
#   * RUNTIME_PROFILE is read out of the running backend container's
#     environment, not out of .env;
#   * the certificate is the file Caddy is actually serving, checked by
#     fingerprint against the one on disk;
#   * secret file modes are stat'ed where the backend reads them.
#
# Each check prints its own verdict. The script exits nonzero if any FAILs.
# A FAIL is not necessarily a bug in the stack -- on a development box
# RUNTIME_PROFILE is deliberately `development` and the dev overlay publishes
# loopback ports. This script answers one question honestly, and on a dev box
# the honest answer is "no".
#
# Environment overrides (all optional; defaults are the production answer):
#   PWR_DOCKER              path to the docker binary
#   GATE_EDGE_HOST          host:port to probe (default ${LAN_HOST:-localhost})
#   GATE_HEALTH_PATH        expected-200 path (default /api/health/live)
#   GATE_BACKEND_CONTAINER  container to read RUNTIME_PROFILE from
#   GATE_CERT               certificate path (default infrastructure/certs/cert.pem)
#   GATE_SECRET_DIR         host secret dir (default infrastructure/secrets)
#   GATE_SKIP_EDGE=1        skip the checks that need to reach the edge
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$ROOT_DIR"

FAILURES=0
CHECKS=0

pass() { CHECKS=$((CHECKS + 1)); printf 'PASS  %-18s %s\n' "$1:" "$2"; }
fail() {
    CHECKS=$((CHECKS + 1))
    FAILURES=$((FAILURES + 1))
    printf 'FAIL  %-18s %s\n' "$1:" "$2"
}
skip() { CHECKS=$((CHECKS + 1)); printf 'SKIP  %-18s %s\n' "$1:" "$2"; }
note() { printf '      %-18s %s\n' "" "$1"; }

# ── Tooling ───────────────────────────────────────────────────────────────
daemon_reachable() { "$1" version --format '{{.Server.Version}}' >/dev/null 2>&1; }

DOCKER_BIN="${PWR_DOCKER:-}"
if [ -n "$DOCKER_BIN" ]; then
    daemon_reachable "$DOCKER_BIN" || {
        echo "FATAL: PWR_DOCKER=$DOCKER_BIN cannot reach a Docker daemon." >&2
        exit 2
    }
else
    # "Is docker on PATH" is the WRONG question and it cost this script a full
    # false run: WSL with Docker Desktop integration switched off HAS a `docker`
    # on PATH that cannot reach any daemon. Every docker call then fails, and a
    # check written to look at the result of a docker call reads an empty list
    # as "nothing is wrong". So the candidate must answer the daemon.
    for candidate in docker "/mnt/c/Program Files/Docker/Docker/resources/bin/docker.exe"; do
        if command -v "$candidate" >/dev/null 2>&1 || [ -x "$candidate" ]; then
            if daemon_reachable "$candidate"; then
                DOCKER_BIN="$candidate"
                break
            fi
        fi
    done
    if [ -z "$DOCKER_BIN" ]; then
        echo "FATAL: no docker binary on this host reaches a Docker daemon. Set PWR_DOCKER." >&2
        exit 2
    fi
fi
dc() { "$DOCKER_BIN" compose "$@"; }

for tool in jq openssl curl; do
    if ! command -v "$tool" >/dev/null 2>&1; then
        echo "FATAL: $tool not found -- this script cannot measure without it." >&2
        exit 2
    fi
done

# .env is the operator's file, not this script's input: it is read ONLY to find
# out where the edge lives. Every posture value is read from the machine.
if [ -z "${LAN_HOST:-}" ] && [ -f "$ROOT_DIR/.env" ]; then
    LAN_HOST="$(sed -n 's/^LAN_HOST=//p' "$ROOT_DIR/.env" | tail -n1)"
fi
EDGE_HOST="${GATE_EDGE_HOST:-${LAN_HOST:-localhost}}"
HEALTH_PATH="${GATE_HEALTH_PATH:-/api/health/live}"
CERT="${GATE_CERT:-$ROOT_DIR/infrastructure/certs/cert.pem}"
SECRET_DIR="${GATE_SECRET_DIR:-$ROOT_DIR/infrastructure/secrets}"

echo "=== production gates: $(date -u '+%Y-%m-%dT%H:%M:%SZ') ==="
echo "    edge=$EDGE_HOST  docker=$DOCKER_BIN"
echo ""

# ── 1. Compose file still parses ──────────────────────────────────────────
if out="$(dc config --quiet 2>&1)"; then
    pass "compose-config" "docker compose config parses"
else
    fail "compose-config" "docker compose config failed"
    note "$out"
fi

# ── 2. The edge config the running Caddy holds is valid ───────────────────
if out="$(dc exec -T caddy caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile 2>&1)"; then
    pass "caddy-config" "running caddy validates /etc/caddy/Caddyfile"
else
    fail "caddy-config" "caddy validate failed inside the running container"
    note "$(echo "$out" | tail -n 3)"
fi

# ── 3. Nothing but Caddy publishes a port ─────────────────────────────────
# `ports:` in a file is a claim. This reads what the daemon actually published.
ports_json="$(dc ps --format json 2>/dev/null | jq -s 'if (.[0]|type)=="array" then .[0] else . end')"
container_count="$(echo "$ports_json" | jq 'length' 2>/dev/null || echo 0)"
# An empty list is NOT "nothing is wrong". A stack that is down publishes no
# ports and would sail through every port assertion ever written.
if [ -z "$ports_json" ] || [ "$ports_json" = "null" ] || [ "${container_count:-0}" -eq 0 ]; then
    fail "published-ports" "'docker compose ps' reported no containers -- the stack is not running, so nothing here was measured"
else
    offenders="$(
        echo "$ports_json" | jq -r '
            .[] | . as $c | (.Publishers // [])[]
            | select(.PublishedPort != null and .PublishedPort > 0)
            | "\($c.Service)\t\(.URL)\t\(.PublishedPort)\t\(.TargetPort)"
        ' | grep -v $'^caddy\t' || true
    )"
    if [ -z "$offenders" ]; then
        pass "published-ports" "only caddy publishes ports"
    else
        lan_exposed="$(echo "$offenders" | awk -F'\t' '$2 != "127.0.0.1" && $2 != "::1"' || true)"
        fail "published-ports" "a service other than caddy publishes a port"
        while IFS=$'\t' read -r svc url pub tgt; do
            [ -z "$svc" ] && continue
            if [ "$url" = "127.0.0.1" ] || [ "$url" = "::1" ]; then
                note "$svc publishes $url:$pub -> $tgt (loopback; dev overlay is active)"
            else
                note "$svc publishes $url:$pub -> $tgt  <-- REACHABLE FROM THE LAN"
            fi
        done <<<"$offenders"
        [ -n "$lan_exposed" ] && note "at least one binding is not loopback: this is the production hole, not just a dev overlay"
    fi
fi

# ── 4. The edge serves the certificate we think it serves ─────────────────
if [ "${GATE_SKIP_EDGE:-0}" = "1" ]; then
    skip "edge-tls" "GATE_SKIP_EDGE=1"
elif [ ! -f "$CERT" ]; then
    fail "edge-tls" "no certificate on disk at $CERT"
else
    disk_fp="$(openssl x509 -in "$CERT" -noout -fingerprint -sha256 2>/dev/null | cut -d= -f2)"
    served_fp="$(
        echo | openssl s_client -connect "${EDGE_HOST}:443" -servername "$EDGE_HOST" 2>/dev/null |
            openssl x509 -noout -fingerprint -sha256 2>/dev/null | cut -d= -f2
    )"
    if [ -z "$served_fp" ]; then
        fail "edge-tls" "no TLS handshake with ${EDGE_HOST}:443"
    elif [ "$served_fp" = "$disk_fp" ]; then
        pass "edge-tls" "edge serves the certificate in $CERT"
    else
        fail "edge-tls" "edge serves a DIFFERENT certificate than $CERT"
        note "on disk: $disk_fp"
        note "served : $served_fp"
    fi
fi

# ── 5. The edge really refuses the internal and documentation paths ───────
# Deliberately --insecure: the certificate is a locally-issued mkcert leaf and
# its CA is not on this host. The identity of the served certificate is check 4
# above; THIS check is about routing, and mixing the two would let a trust
# problem masquerade as a routing pass.
BLOCKED_PATHS=(
    /api/internal/ping
    /api/internal/n8n/callback
    /api/obsidian/anything
    /api/demo/anything
    /api/docs
    /api/redoc
    /api/openapi.json
    /docs
    /redoc
    /openapi.json
)
if [ "${GATE_SKIP_EDGE:-0}" = "1" ]; then
    skip "edge-denylist" "GATE_SKIP_EDGE=1"
else
    bad=""
    for path in "${BLOCKED_PATHS[@]}"; do
        headers="$(curl -skI --max-time 10 "https://${EDGE_HOST}${path}" 2>/dev/null || true)"
        code="$(printf '%s' "$headers" | sed -n 's|^HTTP/[0-9.]* \([0-9]\{3\}\).*|\1|p' | tail -n1)"
        [ -z "$code" ] && code=000
        # Status alone is NOT proof. With the deny-list deleted from the
        # Caddyfile, /api/internal/ping still answered 404 -- from uvicorn,
        # because the backend has no such route today. A check that only read
        # the status would have called that a pass and would have gone on
        # passing after Task 16 adds the route. `server:` names the responder:
        # Caddy's own `respond 404` says Caddy, a proxied answer says uvicorn.
        origin="$(printf '%s' "$headers" | sed -n 's/^[Ss]erver: *//p' | tr -d '\r' | tail -n1)"
        if [ "$code" != "404" ]; then
            bad="${bad}${path} -> ${code}"$'\n'
        elif printf '%s' "$origin" | grep -qi 'uvicorn'; then
            bad="${bad}${path} -> 404 but the answer came from the BACKEND (server: ${origin}); the edge did not block it"$'\n'
        fi
    done
    health_code="$(curl -sk -o /dev/null -w '%{http_code}' --max-time 10 "https://${EDGE_HOST}${HEALTH_PATH}" || echo 000)"
    if [ -n "$bad" ]; then
        fail "edge-denylist" "the edge did NOT answer 404 for every blocked path"
        while read -r line; do [ -n "$line" ] && note "$line"; done <<<"$bad"
    elif [ "$health_code" != "200" ]; then
        # A deny-list that answers 404 to everything proves nothing. The health
        # path must still come back, or the "404" above is just a dead edge.
        fail "edge-denylist" "blocked paths are 404 but ${HEALTH_PATH} answered ${health_code}, not 200"
        note "if the health route moved, set GATE_HEALTH_PATH"
    else
        pass "edge-denylist" "${#BLOCKED_PATHS[@]} blocked paths answer 404 FROM THE EDGE, ${HEALTH_PATH} answers 200"
    fi
fi

# ── 6. RUNTIME_PROFILE of the RUNNING backend ─────────────────────────────
backend_cid="${GATE_BACKEND_CONTAINER:-$(dc ps -q backend 2>/dev/null | tr -d '\r')}"
if [ -z "$backend_cid" ]; then
    fail "runtime-profile" "no running backend container"
else
    profile="$(
        "$DOCKER_BIN" inspect --format '{{range .Config.Env}}{{println .}}{{end}}' "$backend_cid" 2>/dev/null |
            sed -n 's/^RUNTIME_PROFILE=//p' | tr -d '\r' | tail -n1
    )"
    if [ "$profile" = "production" ]; then
        pass "runtime-profile" "running backend has RUNTIME_PROFILE=production"
    elif [ -z "$profile" ]; then
        fail "runtime-profile" "running backend has NO RUNTIME_PROFILE at all"
    else
        fail "runtime-profile" "running backend has RUNTIME_PROFILE=$profile, not production"
        note "validate_runtime_security() is skipped for every value but 'production'"
    fi
fi

# ── 7. Certificate lifetime ───────────────────────────────────────────────
CHECKS=$((CHECKS + 1))
if expiry_out="$(CERT_PATH="$CERT" bash "$SCRIPT_DIR/check-certificate-expiry.sh" 2>&1)"; then
    printf '%s\n' "$expiry_out"
else
    FAILURES=$((FAILURES + 1))
    printf '%s\n' "$expiry_out"
fi

# ── 8. Secret files carry no group/other bits ─────────────────────────────
# Two halves, because a secret can be configured in two places and both are
# real: the paths the backend is actually pointed at (authoritative), and the
# provisioned files on the host (what the next `up` would mount).
secret_problems=""
secret_seen=0
if [ -n "$backend_cid" ]; then
    while IFS= read -r line; do
        [ -z "$line" ] && continue
        var="${line%%=*}"
        path="${line#*=}"
        [ -z "$path" ] && continue
        secret_seen=$((secret_seen + 1))
        mode="$("$DOCKER_BIN" exec "$backend_cid" stat -c '%a' "$path" 2>/dev/null | tr -d '\r')"
        if [ -z "$mode" ]; then
            secret_problems="${secret_problems}${var} -> ${path} does not exist inside the backend container"$'\n'
        elif [ $((8#$mode & 8#077)) -ne 0 ]; then
            secret_problems="${secret_problems}${var} -> ${path} is ${mode}; group/other must have no access"$'\n'
        fi
    done < <(
        "$DOCKER_BIN" inspect --format '{{range .Config.Env}}{{println .}}{{end}}' "$backend_cid" 2>/dev/null |
            tr -d '\r' | grep -E '^[A-Z0-9_]+_SECRET_FILE=.' || true
    )
fi
if [ -d "$SECRET_DIR" ]; then
    while IFS= read -r f; do
        [ -z "$f" ] && continue
        secret_seen=$((secret_seen + 1))
        mode="$(stat -c '%a' "$f" 2>/dev/null)"
        if [ -n "$mode" ] && [ $((8#$mode & 8#077)) -ne 0 ]; then
            secret_problems="${secret_problems}${f} is ${mode} on the host; group/other must have no access"$'\n'
        fi
    done < <(find "$SECRET_DIR" -maxdepth 1 -type f ! -name '.gitignore' ! -name '.gitkeep' 2>/dev/null)
fi
if [ "$secret_seen" -eq 0 ]; then
    skip "secret-modes" "no *_SECRET_FILE configured and no files in $SECRET_DIR"
elif [ -n "$secret_problems" ]; then
    fail "secret-modes" "a secret file is readable by group or other"
    while read -r line; do [ -n "$line" ] && note "$line"; done <<<"$secret_problems"
else
    pass "secret-modes" "$secret_seen secret file(s), none readable by group or other"
fi

# ── Remote probe, for the evidence a second host must produce ─────────────
echo ""
echo "Run this from a SECOND host on the warehouse LAN -- everything above was"
echo "measured on the Docker host itself, where a loopback binding is invisible"
echo "as a hole and a firewall rule is untested:"
echo ""
echo "  for p in 8000 5432 5433 5678 8069 8100 9000 5500 11434; do"
echo "    nc -z -w2 ${EDGE_HOST} \$p && echo \"OPEN \$p  <-- must be closed\" || echo \"closed \$p\""
echo "  done"
echo "  curl -sk -o /dev/null -w '%{http_code}\\n' https://${EDGE_HOST}${HEALTH_PATH}   # expect 200"
echo "  curl -sk -o /dev/null -w '%{http_code}\\n' https://${EDGE_HOST}/api/docs        # expect 404"
echo ""
echo "Port 80 is a redirect listener only. The firewall evidence must show that"
echo "clients are allowed TCP 443 and nothing else."
echo ""

if [ "$FAILURES" -ne 0 ]; then
    echo "=== $FAILURES of $CHECKS checks FAILED: this deployment is NOT in the production posture ==="
    exit 1
fi
echo "=== all $CHECKS checks passed ==="
