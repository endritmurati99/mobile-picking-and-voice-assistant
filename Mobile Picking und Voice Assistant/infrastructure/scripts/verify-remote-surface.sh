#!/usr/bin/env bash
# Foundation Task 17: Port-Oberflaeche von einem ZWEITEN Host aus.
#
# Warum von einem zweiten Host: `docker compose ps` zeigt, was Docker zu
# veroeffentlichen glaubt, und ein Test auf demselben Rechner erreicht Ports
# ueber Loopback, die von aussen zu sein koennen -- oder umgekehrt. Die einzige
# Aussage, die zaehlt, ist die eines Geraets im selben Netz.
#
#   bash infrastructure/scripts/verify-remote-surface.sh picking.warehouse.test
#
# Erwartung: 443 offen, alles andere zu. Port 80 wird von der externen Firewall
# geblockt; Caddys 80-Redirect bleibt nur auf einem kontrollierten
# Admin-Segment nuetzlich und gilt hier als unerwartet offen.
set -Eeuo pipefail

HOST="${1:?Usage: verify-remote-surface.sh picking.warehouse.test}"
TIMEOUT=3

if ! command -v nc >/dev/null 2>&1; then
    echo "nc (netcat) is required and not installed" >&2
    exit 2
fi

echo "probing ${HOST} (timeout ${TIMEOUT}s per port)"

if ! nc -z -w"${TIMEOUT}" "${HOST}" 443; then
    echo "FAIL: 443 is closed -- the edge is not reachable at all" >&2
    exit 1
fi
echo "  443  open (expected)"

# 80    Caddy redirect, must be firewalled externally
# 8000  backend        5432/5433 postgres      5678 n8n editor
# 8069  odoo           8100 whisper            9000 portainer-class admin
# 5500  piper          11434 ollama
FORBIDDEN=(80 8000 5432 5433 5678 8069 8100 9000 5500 11434)
failed=0
for port in "${FORBIDDEN[@]}"; do
    if nc -z -w"${TIMEOUT}" "${HOST}" "${port}"; then
        echo "  ${port}  OPEN -- unexpected" >&2
        failed=1
    else
        echo "  ${port}  closed (expected)"
    fi
done

if [ "${failed}" -ne 0 ]; then
    echo "FAIL: service ports are reachable from another host" >&2
    exit 1
fi

echo "PASS: only 443 is reachable from ${HOSTNAME:-this host}"
