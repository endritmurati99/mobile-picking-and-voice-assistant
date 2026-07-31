#!/usr/bin/env bash
# Generate the edge certificate (Foundation Task 15).
#
# Two arguments, both mandatory, and both END UP IN THE CERTIFICATE:
#
#   * the DNS name, because a browser that reaches the PWA by name and finds
#     only an IP SAN shows a certificate warning -- and a warning the operator
#     is trained to click through is the same as no TLS at all;
#   * the LAN IP, because the phones on the warehouse floor are handed an IP.
#
# The old version took ONE argument named "LAN-IP" and passed it to mkcert
# unexamined. mkcert decides per argument whether it becomes a DNS or an IP
# SAN, so a typo ("192.168.1.10O") silently produced a DNS SAN and a cert no
# device would accept for the address it actually dials. Nothing checked.
#
# So: generate into a temporary directory, ASK THE CERTIFICATE what it carries,
# and install only if both SANs are really there. The install is atomic --
# write beside the live file, then rename -- because Caddy re-reads these files
# and a half-written cert.pem is an outage.
set -euo pipefail

usage() {
    cat <<'EOF'
Verwendung: setup-certs.sh <DNS-NAME> <LAN-IP>
Beispiel:   setup-certs.sh picking.warehouse.test 192.168.1.100

Beide Argumente sind Pflicht. Das erzeugte Zertifikat wird geprueft: es muss
DNS:<DNS-NAME> UND IP Address:<LAN-IP> tragen, sonst wird nichts installiert.
EOF
}

if [ "${1:-}" = "-h" ] || [ "${1:-}" = "--help" ]; then
    usage
    exit 0
fi

LAN_DNS="${1:-}"
LAN_IP="${2:-}"
if [ -z "$LAN_DNS" ] || [ -z "$LAN_IP" ]; then
    usage >&2
    exit 2
fi

# An IP in the DNS slot produces a certificate that is technically valid and
# practically useless. Refuse the swapped order outright, with the message that
# actually names the mistake.
if [[ "$LAN_DNS" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
    echo "FEHLER: '<DNS-NAME>' ist eine IP-Adresse. Reihenfolge: DNS-Name zuerst, dann IP." >&2
    usage >&2
    exit 2
fi
if ! [[ "$LAN_IP" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
    echo "FEHLER: '<LAN-IP>' ist keine IPv4-Adresse: $LAN_IP" >&2
    usage >&2
    exit 2
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# Overridable ONLY so the SAN/atomicity behaviour of this script can itself be
# exercised against a throwaway directory. Production runs use the default.
CERT_DIR="${CERT_DIR:-$SCRIPT_DIR/../certs}"

if ! command -v mkcert >/dev/null 2>&1; then
    echo "FEHLER: mkcert nicht installiert." >&2
    echo "  macOS:   brew install mkcert" >&2
    echo "  Linux:   https://github.com/FiloSottile/mkcert#installation" >&2
    exit 1
fi
if ! command -v openssl >/dev/null 2>&1; then
    echo "FEHLER: openssl nicht installiert -- ohne openssl ist das Zertifikat nicht pruefbar." >&2
    exit 1
fi
if [ ! -d "$CERT_DIR" ]; then
    echo "FEHLER: Zertifikatsverzeichnis fehlt: $CERT_DIR" >&2
    exit 1
fi

TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

mkcert -install
mkcert -cert-file "$TMP_DIR/cert.pem" -key-file "$TMP_DIR/key.pem" \
    "$LAN_DNS" "$LAN_IP" localhost 127.0.0.1

if [ ! -s "$TMP_DIR/cert.pem" ] || [ ! -s "$TMP_DIR/key.pem" ]; then
    echo "FEHLER: mkcert hat kein Zertifikat/keinen Schluessel erzeugt." >&2
    exit 1
fi

# The verification. `grep -F` over the printed extension, because the point is
# to read back what the certificate says, not what we asked for.
SAN="$(openssl x509 -in "$TMP_DIR/cert.pem" -noout -ext subjectAltName)"
missing=0
if ! grep -qF "DNS:$LAN_DNS" <<<"$SAN"; then
    echo "FEHLER: Zertifikat traegt KEINEN SAN 'DNS:$LAN_DNS'." >&2
    missing=1
fi
if ! grep -qF "IP Address:$LAN_IP" <<<"$SAN"; then
    echo "FEHLER: Zertifikat traegt KEINEN SAN 'IP Address:$LAN_IP'." >&2
    missing=1
fi
if [ "$missing" -ne 0 ]; then
    echo "Erzeugte SANs waren:" >&2
    echo "$SAN" >&2
    echo "Die vorhandenen Dateien in $CERT_DIR bleiben UNVERAENDERT." >&2
    exit 1
fi

# Key and certificate must belong together; a mismatched pair makes Caddy fail
# its handshake with an error nobody connects back to this script.
cert_pub="$(openssl x509 -in "$TMP_DIR/cert.pem" -noout -pubkey)"
key_pub="$(openssl pkey -in "$TMP_DIR/key.pem" -pubout)"
if [ "$cert_pub" != "$key_pub" ]; then
    echo "FEHLER: Schluessel und Zertifikat gehoeren nicht zusammen." >&2
    exit 1
fi

# Atomic install: same filesystem, write beside, rename over. `install` sets the
# mode at creation time, so the key is never briefly world-readable.
install -m 0644 "$TMP_DIR/cert.pem" "$CERT_DIR/cert.pem.new"
install -m 0600 "$TMP_DIR/key.pem" "$CERT_DIR/key.pem.new"
mv -f "$CERT_DIR/cert.pem.new" "$CERT_DIR/cert.pem"
mv -f "$CERT_DIR/key.pem.new" "$CERT_DIR/key.pem"

echo ""
echo "OK: Zertifikate installiert in $CERT_DIR"
echo "$SAN"
openssl x509 -in "$CERT_DIR/cert.pem" -noout -enddate
echo "CA-Datei fuer mobile Geraete: $(mkcert -CAROOT)/rootCA.pem"
echo ""
echo "Caddy liest die Dateien erst nach einem Neustart neu:"
echo "  docker compose restart caddy"
