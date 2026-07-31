#!/usr/bin/env bash
# Live signing smoke for the n8n -> backend direction (Foundation Task 15).
#
# It proves two things against the RUNNING backend:
#   1. a correctly signed request gets PAST signature verification;
#   2. a tampered one does not.
#
# Exit codes -- and the third one is the point of this script:
#   0  both halves proven
#   1  a signing assertion FAILED (a tampered request was accepted, or a valid
#      one was rejected). This is a security finding.
#   3  CANNOT RUN. The v2 credentials or the backend are not there. This is
#      NOT a pass. A smoke test that silently skips is worse than no smoke
#      test, because the pipeline it runs in reports green either way.
#
# How "accepted" is measured, and why it is not a guess: the backend verifies
# the signature BEFORE it parses the body (app/routers/n8n_v2.py -> _parse runs
# on verified.raw_body). So a correctly signed request carrying a body that
# cannot possibly validate must come back 422 -- schema rejected, signature
# accepted -- while the same body with a broken signature must come back 401.
# The pair is decisive and it never touches Odoo, so it cannot pass or fail for
# a reason that has nothing to do with signing.
#
# No secret is ever passed in argv. The signing key is handed to python3 in the
# environment of that single command; `ps` shows argv, not that.
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"

BACKEND_URL="${PWR_BACKEND_URL:-http://127.0.0.1:8000}"
TARGET_PATH="/api/internal/n8n/v2/events/accept"
SECRET_DIR="${PWR_SECRET_DIR_HOST:-$ROOT_DIR/infrastructure/secrets}"

CANNOT_RUN=3
FAILURES=0

say() { printf '%s\n' "$*"; }
pass() { printf 'PASS  %s\n' "$*"; }
fail() {
    FAILURES=$((FAILURES + 1))
    printf 'FAIL  %s\n' "$*"
}

cannot_run() {
    say ""
    say "CANNOT RUN -- $1"
    shift
    for line in "$@"; do say "  $line"; done
    say ""
    say "This is exit ${CANNOT_RUN}, deliberately NOT 0. Nothing about the signing"
    say "path was verified by this run."
    exit "$CANNOT_RUN"
}

for tool in python3 curl; do
    command -v "$tool" >/dev/null 2>&1 || cannot_run "$tool is not installed."
done

# ── 1. Credentials ────────────────────────────────────────────────────────
# Three sources, in the order a real deployment would have them. The secret is
# only ever held in a shell variable and handed on through the environment.
KEY_ID="${PWR_N8N_TO_BACKEND_ACTIVE_KEY_ID:-}"
SECRET_B64="${PWR_N8N_TO_BACKEND_ACTIVE_SECRET_B64:-}"
SOURCE="process environment"

if [ -z "$KEY_ID" ] || [ -z "$SECRET_B64" ]; then
    if [ -f "$ROOT_DIR/.env" ]; then
        [ -z "$KEY_ID" ] && KEY_ID="$(sed -n 's/^PWR_N8N_TO_BACKEND_ACTIVE_KEY_ID=//p' "$ROOT_DIR/.env" | tail -n1)"
        [ -z "$SECRET_B64" ] && SECRET_B64="$(sed -n 's/^PWR_N8N_TO_BACKEND_ACTIVE_SECRET_B64=//p' "$ROOT_DIR/.env" | tail -n1)"
        [ -n "$KEY_ID" ] && [ -n "$SECRET_B64" ] && SOURCE=".env"
    fi
fi

if [ -z "$SECRET_B64" ] && [ -f "$SECRET_DIR/pwr_n8n_to_backend_active_hmac" ]; then
    SECRET_B64="$(tr -d '\r\n' <"$SECRET_DIR/pwr_n8n_to_backend_active_hmac")"
    SOURCE="$SECRET_DIR/pwr_n8n_to_backend_active_hmac"
fi

if [ -z "$KEY_ID" ] || [ -z "$SECRET_B64" ]; then
    missing=""
    [ -z "$KEY_ID" ] && missing="${missing}PWR_N8N_TO_BACKEND_ACTIVE_KEY_ID "
    [ -z "$SECRET_B64" ] && missing="${missing}PWR_N8N_TO_BACKEND_ACTIVE_SECRET_B64 "
    cannot_run "the v2 signing credentials do not exist on this machine." \
        "missing: $missing" \
        "looked in: process environment, $ROOT_DIR/.env," \
        "           $SECRET_DIR/pwr_n8n_to_backend_active_hmac" \
        "" \
        "Provision them first:" \
        "  openssl rand -base64 32 > infrastructure/secrets/pwr_n8n_to_backend_active_hmac" \
        "  openssl rand -base64 32 > infrastructure/secrets/pwr_backend_to_n8n_active_hmac" \
        "  openssl rand -hex 32    > infrastructure/secrets/pwr_n8n_native_header" \
        "  chmod 0600 infrastructure/secrets/*" \
        "  # then set PWR_N8N_TO_BACKEND_ACTIVE_KEY_ID in .env and" \
        "  bash infrastructure/scripts/provision-n8n-credentials.sh provision"
fi

# ── 2. Backend reachable, and it is the SIGNED route we can reach ─────────
health="$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 "${BACKEND_URL}/api/health/live" 2>/dev/null || echo 000)"
if [ "$health" != "200" ]; then
    cannot_run "the backend is not reachable at ${BACKEND_URL} (health said ${health})." \
        "The signed routes live under /api/internal/*, which the EDGE answers 404 by" \
        "design -- so this smoke must talk to the backend directly, not through Caddy." \
        "Bring up the dev overlay, or point PWR_BACKEND_URL at the backend:" \
        "  docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d backend"
fi

say "=== pwr n8n->backend signing smoke ==="
say "    backend=${BACKEND_URL}"
say "    target=${TARGET_PATH}"
say "    key id from: ${SOURCE}"
say ""

# ── 3. Sign ───────────────────────────────────────────────────────────────
# Mirrors app/services/hmac_signing.py canonical_signature_input():
#   method \n target \n generation \n timestamp \n nonce \n sha256(body)
sign() {
    local method="$1" target="$2" generation="$3" timestamp="$4" nonce="$5" body="$6"
    PWR_SIGN_SECRET_B64="$SECRET_B64" \
        PWR_SIGN_METHOD="$method" PWR_SIGN_TARGET="$target" \
        PWR_SIGN_GEN="$generation" PWR_SIGN_TS="$timestamp" \
        PWR_SIGN_NONCE="$nonce" PWR_SIGN_BODY="$body" \
        python3 -c '
import base64, hashlib, hmac, os, sys
secret = base64.b64decode(os.environ["PWR_SIGN_SECRET_B64"])
if len(secret) < 32:
    sys.stderr.write("secret decodes to %d bytes, need >= 32\n" % len(secret))
    raise SystemExit(2)
body = os.environ["PWR_SIGN_BODY"].encode()
canonical = "\n".join((
    os.environ["PWR_SIGN_METHOD"],
    os.environ["PWR_SIGN_TARGET"],
    os.environ["PWR_SIGN_GEN"],
    os.environ["PWR_SIGN_TS"],
    os.environ["PWR_SIGN_NONCE"],
    hashlib.sha256(body).hexdigest(),
)).encode()
print("v1=" + hmac.new(secret, canonical, hashlib.sha256).hexdigest())
'
}

uuid() { python3 -c 'import uuid; print(uuid.uuid4())'; }

# Sends a request and echoes "<status> <body>".
send() {
    local key_id="$1" ts="$2" nonce="$3" signed_method="$4" signed_target="$5"
    local generation="$6" signature="$7" body="$8"
    curl -s -o /tmp/pwr_smoke_body.$$ -w '%{http_code}' --max-time 15 \
        -X POST "${BACKEND_URL}${TARGET_PATH}" \
        -H "Content-Type: application/json" \
        -H "Idempotency-Key: ${IDEMPOTENCY_KEY:-none}" \
        -H "X-PWR-Key-Id: ${key_id}" \
        -H "X-PWR-Timestamp: ${ts}" \
        -H "X-PWR-Nonce: ${nonce}" \
        -H "X-PWR-Signed-Method: ${signed_method}" \
        -H "X-PWR-Signed-Target: ${signed_target}" \
        -H "X-PWR-Delivery-Generation: ${generation}" \
        -H "X-PWR-Signature: ${signature}" \
        --data-raw "$body" 2>/dev/null
    local code=$?
    BODY="$(head -c 400 /tmp/pwr_smoke_body.$$ 2>/dev/null)"
    rm -f /tmp/pwr_smoke_body.$$
    return $code
}

TS="$(date +%s)"
GEN=1
# A body that is syntactically JSON and cannot possibly validate against
# EventAcceptanceRequest. Parsing happens AFTER verification, so 422 is proof
# the signature was accepted -- and it never reaches Odoo.
UNPARSEABLE='{"not_an_event":true}'

# ── Case 1: correct signature, invalid schema -> must be 422, never 401 ──
NONCE="$(uuid)"
SIG="$(sign POST "$TARGET_PATH" "$GEN" "$TS" "$NONCE" "$UNPARSEABLE")" || cannot_run "could not compute a signature (bad secret encoding?)."
status="$(send "$KEY_ID" "$TS" "$NONCE" POST "$TARGET_PATH" "$GEN" "$SIG" "$UNPARSEABLE")"
case "$status" in
401) fail "correctly signed request was REJECTED as unsigned (401). Body: $BODY" ;;
503) cannot_run "the backend answered 503: it has no v2 keyring configured." \
    "The credentials this script found are not the ones the backend is running with." ;;
422) pass "correctly signed request passed signature verification (422 = schema rejected, signature accepted)" ;;
*) pass "correctly signed request was not rejected as unsigned (status ${status}); signature verification passed" ;;
esac

# ── Case 2: tampered body -> must be 401 ─────────────────────────────────
NONCE="$(uuid)"
SIG="$(sign POST "$TARGET_PATH" "$GEN" "$TS" "$NONCE" "$UNPARSEABLE")"
status="$(send "$KEY_ID" "$TS" "$NONCE" POST "$TARGET_PATH" "$GEN" "$SIG" '{"not_an_event":false}')"
if [ "$status" = "401" ]; then
    pass "tampered BODY refused with 401"
else
    fail "tampered BODY was NOT refused: status ${status}. Body: $BODY"
fi

# ── Case 3: tampered target -> must be 401 ───────────────────────────────
NONCE="$(uuid)"
SIG="$(sign POST "/api/internal/n8n/v2/callbacks/status" "$GEN" "$TS" "$NONCE" "$UNPARSEABLE")"
status="$(send "$KEY_ID" "$TS" "$NONCE" POST "/api/internal/n8n/v2/callbacks/status" "$GEN" "$SIG" "$UNPARSEABLE")"
if [ "$status" = "401" ]; then
    pass "signature valid for a DIFFERENT target refused with 401"
else
    fail "a signature made for another target was NOT refused: status ${status}. Body: $BODY"
fi

# ── Case 4: unknown key id -> must be 401 ────────────────────────────────
NONCE="$(uuid)"
SIG="$(sign POST "$TARGET_PATH" "$GEN" "$TS" "$NONCE" "$UNPARSEABLE")"
status="$(send "pwr-key-that-does-not-exist" "$TS" "$NONCE" POST "$TARGET_PATH" "$GEN" "$SIG" "$UNPARSEABLE")"
if [ "$status" = "401" ]; then
    pass "unknown key id refused with 401"
else
    fail "an unknown key id was NOT refused: status ${status}. Body: $BODY"
fi

# ── Case 5: stale timestamp -> informational ─────────────────────────────
# Reported, not asserted: verify_signature answers 409 for a stale timestamp,
# and 409 is also what an Odoo conflict answers. Asserting on an ambiguous
# code is how a guard ends up passing for the wrong reason.
STALE="$((TS - 86400))"
NONCE="$(uuid)"
SIG="$(sign POST "$TARGET_PATH" "$GEN" "$STALE" "$NONCE" "$UNPARSEABLE")"
status="$(send "$KEY_ID" "$STALE" "$NONCE" POST "$TARGET_PATH" "$GEN" "$SIG" "$UNPARSEABLE")"
say "INFO  stale timestamp (24h old) answered ${status} -- expected 409 timestamp_outside_window"

say ""
if [ "$FAILURES" -ne 0 ]; then
    say "=== ${FAILURES} signing assertion(s) FAILED ==="
    exit 1
fi
say "=== signing smoke passed: signed accepted, tampered refused ==="
say ""
say "NOT covered here (needs provisioned credentials, a real Odoo job row and"
say "an activated v2 workflow -- Task 15 Step 3's full list):"
say "  * the backend -> n8n direction and the native header credential"
say "  * replay/nonce reservation in Odoo, active/previous key overlap"
say "  * the callback route and the signed artifact upload"
