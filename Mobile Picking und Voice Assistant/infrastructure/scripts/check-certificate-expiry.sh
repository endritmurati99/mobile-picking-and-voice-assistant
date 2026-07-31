#!/usr/bin/env bash
# Certificate expiry gate (Foundation Task 15).
#
# Exits nonzero when fewer than 30 days remain. The window exists so the
# warehouse notices during a working week, not on the morning the phones stop
# trusting the edge.
#
# "expired" alone is a useless alert: it does not say WHICH file or WHEN, and
# on a host with several certificates the operator's first action is another
# openssl call. So the failure message names the path and the notAfter date it
# actually read.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CERT_PATH="${1:-${CERT_PATH:-$SCRIPT_DIR/../certs/cert.pem}}"
# Seconds. 2592000 = 30 days. Overridable for testing this script itself.
CERT_MIN_SECONDS="${CERT_MIN_SECONDS:-2592000}"

if [ ! -f "$CERT_PATH" ]; then
    echo "FAIL  certificate: Datei fehlt: $CERT_PATH" >&2
    echo "      Erzeugen mit: bash infrastructure/scripts/setup-certs.sh <DNS-NAME> <LAN-IP>" >&2
    exit 1
fi

if ! ENDDATE="$(openssl x509 -in "$CERT_PATH" -noout -enddate 2>/dev/null)"; then
    echo "FAIL  certificate: $CERT_PATH ist kein lesbares X.509-Zertifikat" >&2
    exit 1
fi
ENDDATE="${ENDDATE#notAfter=}"

SUBJECT="$(openssl x509 -in "$CERT_PATH" -noout -subject 2>/dev/null || true)"

if openssl x509 -in "$CERT_PATH" -checkend "$CERT_MIN_SECONDS" -noout >/dev/null 2>&1; then
    echo "PASS  certificate: $CERT_PATH gueltig bis $ENDDATE (mehr als $((CERT_MIN_SECONDS / 86400)) Tage)"
    exit 0
fi

# Distinguish "already dead" from "dies soon" -- same exit code, different
# urgency, and the operator should not have to work that out.
if openssl x509 -in "$CERT_PATH" -checkend 0 -noout >/dev/null 2>&1; then
    STATE="laeuft in weniger als $((CERT_MIN_SECONDS / 86400)) Tagen ab"
else
    STATE="ist BEREITS ABGELAUFEN"
fi

{
    echo "FAIL  certificate: $CERT_PATH $STATE"
    echo "      notAfter: $ENDDATE"
    [ -n "$SUBJECT" ] && echo "      $SUBJECT"
    echo "      Erneuern: bash infrastructure/scripts/setup-certs.sh <DNS-NAME> <LAN-IP>"
    echo "      danach:   docker compose restart caddy"
} >&2
exit 1
