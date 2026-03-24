"""
Seed-Daten für Odoo 18 Community.

Erstellt Mindest-Testdaten für den Picking-PoC:
- Lagerorte mit Barcodes
- Produkte mit EAN-Barcodes
- Test-Pickings mit verschiedenen Prioritäten, Terminen und Zuständen

Verwendung (generische Testdaten):
    python seed-odoo.py --url http://localhost:8069 --db masterfischer --user admin --api-key admin

Verwendung (BOM-basierte Pickings aus echten Produkten):
    python seed-odoo.py --url http://localhost:8069 --db masterfischer --user admin --api-key admin --bom-mode
"""
import argparse
import sys
from datetime import date, timedelta
from xmlrpc.client import ServerProxy


def main():
    parser = argparse.ArgumentParser(description="Odoo Seed-Daten")
    parser.add_argument("--url", default="http://localhost:8069")
    parser.add_argument("--db", default="masterfischer")
    parser.add_argument("--user", default="admin")
    parser.add_argument("--api-key", required=True)
    parser.add_argument("--bom-mode", action="store_true",
                        help="BOM-basierte Pickings aus echten Produkten erstellen (löscht bestehende nicht-done Pickings)")
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

    if args.bom_mode:
        seed_bom_pickings(execute)
        return

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


def seed_bom_pickings(execute):
    """
    BOM-Modus: Erstellt Pickings basierend auf echten Stücklisten.

    Jedes Picking entspricht dem Kommissionieren der Bauteile
    für ein bestimmtes Endprodukt (z.B. Ente Henri, Papagei Moritz).
    Löscht zuerst alle nicht-abgeschlossenen Pickings.
    """
    from datetime import date, timedelta
    today = date.today()
    yesterday = (today - timedelta(days=1)).isoformat()
    tomorrow = (today + timedelta(days=1)).isoformat()
    today_str = today.isoformat()

    print("BOM-Modus: Bestehende Pickings löschen...")

    # Nicht-abgeschlossene Pickings holen und canceln
    active_picks = execute(
        "stock.picking", "search",
        [("state", "not in", ["done", "cancel"])],
    )
    if active_picks:
        try:
            execute("stock.picking", "action_cancel", active_picks)
        except Exception as e:
            print(f"  [WARN] Cancel teilweise fehlgeschlagen: {e}")
        try:
            execute("stock.picking", "unlink", active_picks)
            print(f"  [OK] {len(active_picks)} Pickings gelöscht")
        except Exception as e:
            print(f"  [WARN] Unlink fehlgeschlagen: {e}")
    else:
        print("  Keine aktiven Pickings vorhanden.")

    # ── Picking-Typ: Internal Transfers ──────────────────────
    pick_type = execute(
        "stock.picking.type", "search_read",
        [("code", "=", "internal")],
        fields=["id", "default_location_src_id", "default_location_dest_id"],
        limit=1,
    )
    if not pick_type:
        print("FEHLER: Kein Internal-Transfer-Picking-Typ gefunden.")
        return
    pt = pick_type[0]

    # Manufacturing-Lagerort als Ziel
    mfg_loc = execute(
        "stock.location", "search_read",
        [("usage", "=", "internal"), ("name", "=", "Manufacturing")],
        fields=["id"], limit=1,
    )
    dest_loc_id = mfg_loc[0]["id"] if mfg_loc else pt["default_location_dest_id"][0]

    # ── BOMs laden ────────────────────────────────────────────
    print("\nBOM-Modus: Lade Stücklisten...")
    boms = execute(
        "mrp.bom", "search_read",
        [],
        fields=["id", "product_tmpl_id", "code", "bom_line_ids"],
    )
    print(f"  {len(boms)} Stücklisten gefunden")

    def get_bom_components(bom_id):
        lines = execute(
            "mrp.bom.line", "search_read",
            [("bom_id", "=", bom_id)],
            fields=["product_id", "product_qty"],
        )
        result = []
        for line in lines:
            product_id = line["product_id"][0]
            # Besten Lagerort mit Bestand finden (nicht Manufacturing)
            quants = execute(
                "stock.quant", "search_read",
                [
                    ("product_id", "=", product_id),
                    ("quantity", ">", 0),
                    ("location_id.usage", "=", "internal"),
                    ("location_id", "!=", dest_loc_id),
                ],
                fields=["location_id", "quantity"],
                order="quantity desc",
                limit=1,
            )
            if quants:
                result.append({
                    "product_id": product_id,
                    "product_name": line["product_id"][1],
                    "qty": line["product_qty"],
                    "location_id": quants[0]["location_id"][0],
                })
        return result

    def make_bom_picking(bom, priority="0", scheduled_date=None, origin=None):
        components = get_bom_components(bom["id"])
        if not components:
            print(f"  [SKIP] Keine Komponenten mit Bestand für BOM {bom['id']}")
            return None

        product_name = bom["product_tmpl_id"][1]
        picking_origin = origin or f"{product_name} (BOM {bom['code']})"

        vals = {
            "picking_type_id": pt["id"],
            "location_id": pt["default_location_src_id"][0] if pt["default_location_src_id"] else False,
            "location_dest_id": dest_loc_id,
            "priority": priority,
            "origin": picking_origin,
            "move_ids": [
                (0, 0, {
                    "name": c["product_name"],
                    "product_id": c["product_id"],
                    "product_uom_qty": c["qty"],
                    "product_uom": 1,
                    "location_id": c["location_id"],
                    "location_dest_id": dest_loc_id,
                })
                for c in components
            ],
        }
        if scheduled_date:
            vals["scheduled_date"] = scheduled_date

        try:
            pick_id = execute("stock.picking", "create", vals)
            execute("stock.picking", "action_confirm", [pick_id])
            execute("stock.picking", "action_assign", [pick_id])
            return pick_id
        except Exception as e:
            print(f"  [WARN] Picking konnte nicht erstellt werden: {e}")
            return None

    # ── Pickings nach BOM erstellen ───────────────────────────
    print("\nBOM-Modus: Erstelle Pickings...")

    # Konfiguration: BOM-ID → (priority, scheduled_date, label)
    # BOMs 12-22 vorhanden: Sparkasse, Papagei, Burger, Windkraft, Wal,
    #                        Krebs Max, Erwin, Blume, LKW, Ente Henri, Helikopter
    picking_config = [
        # BOM-ID, Priorität, Datum, Label
        (21, "0",  today_str, "Normal, heute"),       # Ente Henri
        (13, "1",  today_str, "DRINGEND, heute"),     # Papagei Moritz
        (16, "0",  tomorrow,  "Normal, morgen"),      # Wal
        (14, "1",  yesterday, "DRINGEND, überfällig"),# Burger
        (15, "0",  tomorrow,  "Normal, morgen"),      # Windkraft
        (17, "1",  today_str, "DRINGEND, heute"),     # Krebs Max
        (12, "0",  today_str, "Normal, heute"),       # Sparkasse
        (19, "0",  tomorrow,  "Normal, morgen"),      # Blume
        (20, "0",  today_str, "Normal, heute"),       # LKW
    ]

    bom_map = {b["id"]: b for b in boms}

    for bom_id, priority, sched_date, label in picking_config:
        bom = bom_map.get(bom_id)
        if not bom:
            print(f"  [SKIP] BOM {bom_id} nicht gefunden")
            continue

        product_name = bom["product_tmpl_id"][1]
        pick_id = make_bom_picking(bom, priority=priority, scheduled_date=sched_date)
        if pick_id:
            prio_str = "DRINGEND" if priority == "1" else "Normal  "
            print(f"  [OK] {prio_str} | {label:25} | {product_name} (BOM {bom['code']}) -> Picking {pick_id}")

    print("\nBOM-basierte Pickings erstellt!")
    print("Tipp: In der PWA sind die Pickings nun nach echten Lego-Produkten strukturiert.")


if __name__ == "__main__":
    main()
