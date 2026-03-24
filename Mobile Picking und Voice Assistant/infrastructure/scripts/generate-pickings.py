"""
Generiert zufällige Test-Pickings in Odoo.

Lädt vorhandene Produkte und Lagerorte dynamisch aus der Datenbank —
kein seed-odoo.py erforderlich.

Verwendung:
    python generate-pickings.py --url http://localhost:8069 --db masterfischer --user admin --api-key <key>
    python generate-pickings.py --count 50
"""
import argparse
import random
import sys
from xmlrpc.client import ServerProxy


def main():
    parser = argparse.ArgumentParser(description="Test-Pickings generieren")
    parser.add_argument("--url", default="http://localhost:8069")
    parser.add_argument("--db", default="masterfischer")
    parser.add_argument("--user", default="admin")
    parser.add_argument("--api-key", required=True)
    parser.add_argument("--count", type=int, default=100)
    args = parser.parse_args()

    common = ServerProxy(f"{args.url}/xmlrpc/2/common")
    uid = common.authenticate(args.db, args.user, args.api_key, {})
    if not uid:
        print("FEHLER: Authentifizierung fehlgeschlagen")
        sys.exit(1)

    models = ServerProxy(f"{args.url}/xmlrpc/2/object")

    def execute(model, method, *a, **kw):
        return models.execute_kw(args.db, uid, args.api_key, model, method, list(a), kw)

    # ── Produkte mit vorhandenem Bestand laden ─────────────────────
    print("Lade Produkte mit Bestand...")
    quants = execute(
        "stock.quant", "search_read",
        [("location_id.usage", "=", "internal"), ("quantity", ">", 0)],
        fields=["product_id", "location_id", "quantity"],
        limit=200,
    )

    if not quants:
        print("FEHLER: Kein Bestand gefunden. Bitte zuerst Produkte und Bestand in Odoo anlegen.")
        sys.exit(1)

    # Bestand-Map: product_id -> [(location_id, qty), ...]
    stock_map = {}
    for q in quants:
        pid = q["product_id"][0]
        lid = q["location_id"][0]
        qty = q["quantity"]
        if pid not in stock_map:
            stock_map[pid] = []
        stock_map[pid].append((lid, qty))

    print(f"  {len(stock_map)} Produkte mit Bestand gefunden")

    # Ziel-Lagerort (Output oder Pack Zone)
    dest_candidates = execute(
        "stock.location", "search_read",
        [("usage", "=", "internal"), ("name", "ilike", "Output")],
        fields=["id", "complete_name"], limit=1,
    )
    if not dest_candidates:
        dest_candidates = execute(
            "stock.location", "search_read",
            [("usage", "=", "internal")],
            fields=["id", "complete_name"], limit=1,
        )
    dest_id = dest_candidates[0]["id"]
    print(f"  Ziel-Lagerort: {dest_candidates[0]['complete_name']} (ID: {dest_id})")

    # ── Picking-Typ laden ──────────────────────────────────────────
    pt_res = execute(
        "stock.picking.type", "search_read",
        [("code", "=", "internal")],
        fields=["id", "default_location_src_id", "default_location_dest_id"],
        limit=1,
    )
    if not pt_res:
        pt_res = execute(
            "stock.picking.type", "search_read",
            [("code", "=", "outgoing")],
            fields=["id", "default_location_src_id", "default_location_dest_id"],
            limit=1,
        )
    if not pt_res:
        print("FEHLER: Kein Picking-Typ gefunden.")
        sys.exit(1)

    pt_id = pt_res[0]["id"]
    print(f"  Picking-Typ ID: {pt_id}")

    # ── Pickings erstellen ─────────────────────────────────────────
    print(f"\nErstelle {args.count} Pickings...")

    product_ids = list(stock_map.keys())
    created = 0
    assigned = 0
    skipped = 0

    for i in range(args.count):
        num_lines = random.randint(1, 3)
        sample = random.sample(product_ids, min(num_lines, len(product_ids)))
        lines = []

        for pid in sample:
            locs = stock_map[pid]
            src_id, avail_qty = random.choice(locs)
            qty = random.randint(1, max(1, int(avail_qty / 10)))
            lines.append((0, 0, {
                "name": f"Position {len(lines)+1}",
                "product_id": pid,
                "product_uom_qty": qty,
                "location_id": src_id,
                "location_dest_id": dest_id,
            }))

        if not lines:
            skipped += 1
            continue

        try:
            picking_id = execute("stock.picking", "create", {
                "picking_type_id": pt_id,
                "location_id": lines[0][2]["location_id"],
                "location_dest_id": dest_id,
                "move_ids": lines,
            })
            execute("stock.picking", "action_confirm", [picking_id])
            execute("stock.picking", "action_assign", [picking_id])
            created += 1

            state_res = execute("stock.picking", "read", [picking_id], fields=["state"])
            state = state_res[0]["state"] if state_res else "?"
            if state == "assigned":
                assigned += 1

            if (i + 1) % 10 == 0 or (i + 1) == args.count:
                print(f"  {i+1}/{args.count} — Picking {picking_id} [{state}]")

        except Exception as e:
            print(f"  [FEHLER] Picking {i+1}: {e}")
            skipped += 1

    print(f"\nFertig!")
    print(f"  Erstellt:      {created}")
    print(f"  Assigned:      {assigned}  (erscheinen in der PWA)")
    print(f"  Uebersprungen: {skipped}")
    if created - assigned > 0:
        print(f"  Hinweis: {created - assigned} nicht 'assigned' — evtl. reservierter Bestand erschoepft")


if __name__ == "__main__":
    main()
