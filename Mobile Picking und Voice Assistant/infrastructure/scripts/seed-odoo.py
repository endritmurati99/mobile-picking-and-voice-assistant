"""
Seed-Daten für Odoo 18 Community.

Erstellt Mindest-Testdaten für den Picking-PoC:
- Lagerorte mit Barcodes
- Produkte mit EAN-Barcodes
- Test-Pickings im Status 'assigned'

Verwendung:
    python seed-odoo.py --url http://localhost:8069 --db picking --user admin --api-key <key>
"""
import argparse
import sys
from xmlrpc.client import ServerProxy


def main():
    parser = argparse.ArgumentParser(description="Odoo Seed-Daten")
    parser.add_argument("--url", default="http://localhost:8069")
    parser.add_argument("--db", default="picking")
    parser.add_argument("--user", default="admin")
    parser.add_argument("--api-key", required=True)
    args = parser.parse_args()

    common = ServerProxy(f"{args.url}/xmlrpc/2/common")
    uid = common.authenticate(args.db, args.user, args.api_key, {})
    if not uid:
        print("FEHLER: Authentifizierung fehlgeschlagen")
        sys.exit(1)

    models = ServerProxy(f"{args.url}/xmlrpc/2/object")

    def execute(model, method, *a, **kw):
        return models.execute_kw(
            args.db, uid, args.api_key, model, method, list(a), kw
        )

    def find_or_create(model, domain, vals):
        existing = execute(model, "search", domain)
        if existing:
            return existing[0], False
        new_id = execute(model, "create", vals)
        return new_id, True

    # ── Lagerorte ────────────────────────────────────────────
    print("Lagerorte...")

    stock_loc = execute(
        "stock.location", "search_read",
        [("name", "=", "Stock"), ("usage", "=", "internal")],
        fields=["id"], limit=1,
    )
    parent_id = stock_loc[0]["id"] if stock_loc else False

    locations_data = [
        {"name": "Regal A-01", "barcode": "LOC-A01"},
        {"name": "Regal A-02", "barcode": "LOC-A02"},
        {"name": "Regal B-01", "barcode": "LOC-B01"},
        {"name": "Regal B-02", "barcode": "LOC-B02"},
        {"name": "Regal C-01", "barcode": "LOC-C01"},
    ]

    loc_ids = {}
    for loc in locations_data:
        lid, created = find_or_create(
            "stock.location",
            [("barcode", "=", loc["barcode"])],
            {**loc, "usage": "internal", "location_id": parent_id},
        )
        loc_ids[loc["barcode"]] = lid
        status = "[OK] erstellt" if created else "[=] existiert"
        print(f"  {status}: {loc['name']} (ID: {lid})")

    # ── Produkte ─────────────────────────────────────────────
    print("\nProdukte...")

    products_data = [
        {"name": "Schraube M8x40", "barcode": "4006381333931", "default_code": "SCR-M8-40"},
        {"name": "Mutter M8 DIN934", "barcode": "4006381333948", "default_code": "NUT-M8"},
        {"name": "Unterlegscheibe M8", "barcode": "4006381333955", "default_code": "WSH-M8"},
        {"name": "Winkel 40x40", "barcode": "5901234123457", "default_code": "ANG-40"},
        {"name": "Gewindestange M8", "barcode": "7622210100528", "default_code": "ROD-M8"},
    ]

    prod_ids = {}
    for prod in products_data:
        pid, created = find_or_create(
            "product.product",
            [("barcode", "=", prod["barcode"])],
            {**prod, "type": "consu", "is_storable": True, "tracking": "none"},
        )
        execute(
            "product.product",
            "write",
            [[pid]],
            {"type": "consu", "is_storable": True, "tracking": "none"},
        )
        prod_ids[prod["barcode"]] = pid
        status = "[OK] erstellt" if created else "[=] existiert"
        print(f"  {status}: {prod['name']} (ID: {pid})")

    # ── Bestand einbuchen ────────────────────────────────────
    print("\nBestaende einbuchen...")

    stock_quants = [
        (prod_ids["4006381333931"], loc_ids["LOC-A01"], 100),
        (prod_ids["4006381333948"], loc_ids["LOC-A02"], 200),
        (prod_ids["4006381333955"], loc_ids["LOC-A02"], 150),
        (prod_ids["5901234123457"], loc_ids["LOC-B01"], 50),
        (prod_ids["7622210100528"], loc_ids["LOC-B02"], 30),
    ]

    for product_id, location_id, qty in stock_quants:
        try:
            execute(
                "stock.quant", "create",
                {
                    "product_id": product_id,
                    "location_id": location_id,
                    "inventory_quantity": qty,
                },
            )
            # Bestand anwenden
            quant_ids = execute(
                "stock.quant", "search",
                [("product_id", "=", product_id), ("location_id", "=", location_id)],
            )
            if quant_ids:
                execute("stock.quant", "action_apply_inventory", quant_ids)
            print(f"  [OK] {qty} Stk. eingebucht (Produkt {product_id} -> Lagerort {location_id})")
        except Exception as e:
            print(f"  [WARN] Bestand-Einbuchung uebersprungen: {e}")

    # ── Picking erstellen ────────────────────────────────────
    print("\nPickings...")

    pick_type = execute(
        "stock.picking.type", "search_read",
        [("code", "=", "internal")],
        fields=["id", "default_location_src_id", "default_location_dest_id"],
        limit=1,
    )
    if not pick_type:
        pick_type = execute(
            "stock.picking.type", "search_read",
            [("code", "=", "outgoing")],
            fields=["id", "default_location_src_id", "default_location_dest_id"],
            limit=1,
        )

    if pick_type:
        pt = pick_type[0]
        src = pt["default_location_src_id"][0] if pt["default_location_src_id"] else parent_id
        dest = pt["default_location_dest_id"][0] if pt["default_location_dest_id"] else loc_ids["LOC-C01"]

        picking_id = execute(
            "stock.picking", "create",
            {
                "picking_type_id": pt["id"],
                "location_id": src,
                "location_dest_id": dest,
                "move_ids": [
                    (0, 0, {
                        "name": "Schraube M8x40",
                        "product_id": prod_ids["4006381333931"],
                        "product_uom_qty": 10,
                        "location_id": loc_ids["LOC-A01"],
                        "location_dest_id": dest,
                    }),
                    (0, 0, {
                        "name": "Mutter M8 DIN934",
                        "product_id": prod_ids["4006381333948"],
                        "product_uom_qty": 10,
                        "location_id": loc_ids["LOC-A02"],
                        "location_dest_id": dest,
                    }),
                    (0, 0, {
                        "name": "Winkel 40x40",
                        "product_id": prod_ids["5901234123457"],
                        "product_uom_qty": 5,
                        "location_id": loc_ids["LOC-B01"],
                        "location_dest_id": dest,
                    }),
                ],
            },
        )

        execute("stock.picking", "action_confirm", [picking_id])
        execute("stock.picking", "action_assign", [picking_id])
        print(f"  [OK] Picking erstellt und zugewiesen (ID: {picking_id})")

        # Zweites Picking für Tests
        picking_id_2 = execute(
            "stock.picking", "create",
            {
                "picking_type_id": pt["id"],
                "location_id": src,
                "location_dest_id": dest,
                "move_ids": [
                    (0, 0, {
                        "name": "Unterlegscheibe M8",
                        "product_id": prod_ids["4006381333955"],
                        "product_uom_qty": 20,
                        "location_id": loc_ids["LOC-A02"],
                        "location_dest_id": dest,
                    }),
                    (0, 0, {
                        "name": "Gewindestange M8",
                        "product_id": prod_ids["7622210100528"],
                        "product_uom_qty": 3,
                        "location_id": loc_ids["LOC-B02"],
                        "location_dest_id": dest,
                    }),
                ],
            },
        )
        execute("stock.picking", "action_confirm", [picking_id_2])
        execute("stock.picking", "action_assign", [picking_id_2])
        print(f"  [OK] Picking 2 erstellt und zugewiesen (ID: {picking_id_2})")
    else:
        print("  [WARN] Kein Picking-Typ gefunden")

    # ── Quality-Modul prüfen ─────────────────────────────────
    print("\nQuality-Modul...")
    try:
        execute("ir.module.module", "search_read",
                [("name", "=", "quality_alert_custom")],
                fields=["state"])
        modules = execute(
            "ir.module.module", "search_read",
            [("name", "=", "quality_alert_custom")],
            fields=["state"],
        )
        if modules:
            print(f"  quality_alert_custom: {modules[0]['state']}")
            if modules[0]["state"] != "installed":
                print("  [WARN] Modul nicht installiert! In Odoo Apps installieren.")
        else:
            print("  [WARN] Modul nicht gefunden. 'Update Apps List' in Odoo ausfuehren.")
    except Exception as e:
        print(f"  [WARN] Pruefung fehlgeschlagen: {e}")

    print("\nSeed-Daten komplett!")


if __name__ == "__main__":
    main()
