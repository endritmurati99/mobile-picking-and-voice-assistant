"""
Seed-Daten für Odoo 18 Community.

Erstellt Mindest-Testdaten für den Picking-PoC:
- Lagerorte mit Barcodes
- Produkte mit EAN-Barcodes
- Test-Pickings mit verschiedenen Prioritäten, Terminen und Zuständen

Verwendung:
    python seed-odoo.py --url http://localhost:8069 --db picking --user admin --api-key <key>
"""
import argparse
import sys
from datetime import date, timedelta
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

    # ── Datumshelfer ─────────────────────────────────────────
    today = date.today()
    yesterday = (today - timedelta(days=1)).isoformat()
    three_ago = (today - timedelta(days=3)).isoformat()
    tomorrow = (today + timedelta(days=1)).isoformat()
    day_after = (today + timedelta(days=2)).isoformat()
    today_str = today.isoformat()

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
        {"name": "Regal C-02", "barcode": "LOC-C02"},
        {"name": "Regal D-01", "barcode": "LOC-D01"},
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
        {"name": "Sechskantschraube M6", "barcode": "4006381334013", "default_code": "SCR-M6"},
        {"name": "Federscheibe M10", "barcode": "4006381334020", "default_code": "SPR-M10"},
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
            [pid],
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
        (prod_ids["4006381334013"], loc_ids["LOC-C02"], 80),
        (prod_ids["4006381334020"], loc_ids["LOC-D01"], 60),
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
            quant_ids = execute(
                "stock.quant", "search",
                [("product_id", "=", product_id), ("location_id", "=", location_id)],
            )
            if quant_ids:
                execute("stock.quant", "action_apply_inventory", quant_ids)
            print(f"  [OK] {qty} Stk. eingebucht (Produkt {product_id} -> Lagerort {location_id})")
        except Exception as e:
            print(f"  [WARN] Bestand-Einbuchung uebersprungen: {e}")

    # ── Picking-Typ ermitteln ────────────────────────────────
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

    if not pick_type:
        print("  [WARN] Kein Picking-Typ gefunden — Pickings werden nicht erstellt.")
    else:
        pt = pick_type[0]
        src = pt["default_location_src_id"][0] if pt["default_location_src_id"] else parent_id
        dest = pt["default_location_dest_id"][0] if pt["default_location_dest_id"] else loc_ids["LOC-C01"]

        def make_picking(moves, priority="0", scheduled_date=None):
            vals = {
                "picking_type_id": pt["id"],
                "location_id": src,
                "location_dest_id": dest,
                "priority": priority,
                "move_ids": [
                    (0, 0, {
                        "name": m["name"],
                        "product_id": m["product_id"],
                        "product_uom_qty": m["qty"],
                        "location_id": m["loc_src"],
                        "location_dest_id": dest,
                    })
                    for m in moves
                ],
            }
            if scheduled_date:
                vals["scheduled_date"] = scheduled_date
            pid = execute("stock.picking", "create", vals)
            execute("stock.picking", "action_confirm", [pid])
            execute("stock.picking", "action_assign", [pid])
            return pid

        # 1. Normal, heute
        p1 = make_picking(
            moves=[
                {"name": "Schraube M8x40", "product_id": prod_ids["4006381333931"], "qty": 10, "loc_src": loc_ids["LOC-A01"]},
                {"name": "Mutter M8 DIN934", "product_id": prod_ids["4006381333948"], "qty": 10, "loc_src": loc_ids["LOC-A02"]},
                {"name": "Winkel 40x40", "product_id": prod_ids["5901234123457"], "qty": 5, "loc_src": loc_ids["LOC-B01"]},
            ],
            priority="0", scheduled_date=today_str,
        )
        print(f"  [OK] Picking 1 - Normal, heute                (ID: {p1})")

        # 2. Normal, morgen
        p2 = make_picking(
            moves=[
                {"name": "Unterlegscheibe M8", "product_id": prod_ids["4006381333955"], "qty": 20, "loc_src": loc_ids["LOC-A02"]},
                {"name": "Gewindestange M8", "product_id": prod_ids["7622210100528"], "qty": 3, "loc_src": loc_ids["LOC-B02"]},
            ],
            priority="0", scheduled_date=tomorrow,
        )
        print(f"  [OK] Picking 2 - Normal, morgen                (ID: {p2})")

        # 3. Normal, uebermorgen
        p3 = make_picking(
            moves=[
                {"name": "Sechskantschraube M6", "product_id": prod_ids["4006381334013"], "qty": 15, "loc_src": loc_ids["LOC-C02"]},
                {"name": "Federscheibe M10", "product_id": prod_ids["4006381334020"], "qty": 8, "loc_src": loc_ids["LOC-D01"]},
            ],
            priority="0", scheduled_date=day_after,
        )
        print(f"  [OK] Picking 3 - Normal, uebermorgen           (ID: {p3})")

        # 4. DRINGEND, heute
        p4 = make_picking(
            moves=[
                {"name": "Schraube M8x40", "product_id": prod_ids["4006381333931"], "qty": 25, "loc_src": loc_ids["LOC-A01"]},
                {"name": "Mutter M8 DIN934", "product_id": prod_ids["4006381333948"], "qty": 25, "loc_src": loc_ids["LOC-A02"]},
            ],
            priority="1", scheduled_date=today_str,
        )
        print(f"  [OK] Picking 4 - DRINGEND, heute               (ID: {p4})")

        # 5. DRINGEND, gestern (ueberfaellig)
        p5 = make_picking(
            moves=[
                {"name": "Winkel 40x40", "product_id": prod_ids["5901234123457"], "qty": 10, "loc_src": loc_ids["LOC-B01"]},
                {"name": "Gewindestange M8", "product_id": prod_ids["7622210100528"], "qty": 5, "loc_src": loc_ids["LOC-B02"]},
                {"name": "Federscheibe M10", "product_id": prod_ids["4006381334020"], "qty": 12, "loc_src": loc_ids["LOC-D01"]},
            ],
            priority="1", scheduled_date=yesterday,
        )
        print(f"  [OK] Picking 5 - DRINGEND, gestern ueberfaellig (ID: {p5})")

        # 6. DRINGEND, 3 Tage ueberfaellig
        p6 = make_picking(
            moves=[
                {"name": "Sechskantschraube M6", "product_id": prod_ids["4006381334013"], "qty": 30, "loc_src": loc_ids["LOC-C02"]},
                {"name": "Unterlegscheibe M8", "product_id": prod_ids["4006381333955"], "qty": 40, "loc_src": loc_ids["LOC-A02"]},
            ],
            priority="1", scheduled_date=three_ago,
        )
        print(f"  [OK] Picking 6 - DRINGEND, 3 Tage ueberfaellig (ID: {p6})")

        # 7. Normal, morgen, 5 Positionen
        p7 = make_picking(
            moves=[
                {"name": "Schraube M8x40", "product_id": prod_ids["4006381333931"], "qty": 5, "loc_src": loc_ids["LOC-A01"]},
                {"name": "Mutter M8 DIN934", "product_id": prod_ids["4006381333948"], "qty": 5, "loc_src": loc_ids["LOC-A02"]},
                {"name": "Unterlegscheibe M8", "product_id": prod_ids["4006381333955"], "qty": 5, "loc_src": loc_ids["LOC-A02"]},
                {"name": "Winkel 40x40", "product_id": prod_ids["5901234123457"], "qty": 3, "loc_src": loc_ids["LOC-B01"]},
                {"name": "Sechskantschraube M6", "product_id": prod_ids["4006381334013"], "qty": 10, "loc_src": loc_ids["LOC-C02"]},
            ],
            priority="0", scheduled_date=tomorrow,
        )
        print(f"  [OK] Picking 7 - Normal, 5 Positionen, morgen  (ID: {p7})")

        # 8. DRINGEND, heute, 4 Positionen
        p8 = make_picking(
            moves=[
                {"name": "Gewindestange M8", "product_id": prod_ids["7622210100528"], "qty": 8, "loc_src": loc_ids["LOC-B02"]},
                {"name": "Federscheibe M10", "product_id": prod_ids["4006381334020"], "qty": 20, "loc_src": loc_ids["LOC-D01"]},
                {"name": "Winkel 40x40", "product_id": prod_ids["5901234123457"], "qty": 6, "loc_src": loc_ids["LOC-B01"]},
                {"name": "Schraube M8x40", "product_id": prod_ids["4006381333931"], "qty": 15, "loc_src": loc_ids["LOC-A01"]},
            ],
            priority="1", scheduled_date=today_str,
        )
        print(f"  [OK] Picking 8 - DRINGEND, heute, 4 Positionen (ID: {p8})")

        # 9. Teilweise erledigt (1 von 3 Zeilen gepickt)
        p9 = make_picking(
            moves=[
                {"name": "Schraube M8x40", "product_id": prod_ids["4006381333931"], "qty": 6, "loc_src": loc_ids["LOC-A01"]},
                {"name": "Mutter M8 DIN934", "product_id": prod_ids["4006381333948"], "qty": 6, "loc_src": loc_ids["LOC-A02"]},
                {"name": "Sechskantschraube M6", "product_id": prod_ids["4006381334013"], "qty": 10, "loc_src": loc_ids["LOC-C02"]},
            ],
            priority="0", scheduled_date=today_str,
        )
        # Erste Zeile als gepickt markieren
        move_ids_p9 = execute("stock.move", "search", [("picking_id", "=", p9)])
        if move_ids_p9:
            first_move = move_ids_p9[0]
            ml_ids = execute("stock.move.line", "search", [("move_id", "=", first_move)])
            if ml_ids:
                execute("stock.move.line", "write", ml_ids, {"quantity": 6.0})
            execute("stock.move", "write", [first_move], {"picked": True})
        print(f"  [OK] Picking 9 - Teilweise erledigt (1/3)      (ID: {p9})")

    # ── Quality-Modul prüfen ─────────────────────────────────
    print("\nQuality-Modul...")
    try:
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
