#!/bin/bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CERT_DIR="$SCRIPT_DIR/../certs"
LAN_HOST="${1:-${LAN_HOST:-}}"
if [ -z "$LAN_HOST" ]; then
    echo "Verwendung: $0 <LAN-IP>"
    echo "Beispiel:   $0 192.168.1.100"
    exit 1
fi
if ! command -v mkcert &> /dev/null; then
    echo "FEHLER: mkcert nicht installiert."
    echo "  macOS:   brew install mkcert"
    echo "  Linux:   https://github.com/FiloSottile/mkcert#installation"
    exit 1
fi
mkcert -install
mkcert -cert-file "$CERT_DIR/cert.pem" -key-file "$CERT_DIR/key.pem" "$LAN_HOST" localhost 127.0.0.1
echo ""
echo "✅ Zertifikate in $CERT_DIR"
echo "CA-Datei für mobile Geräte: $(mkcert -CAROOT)/rootCA.pem"
