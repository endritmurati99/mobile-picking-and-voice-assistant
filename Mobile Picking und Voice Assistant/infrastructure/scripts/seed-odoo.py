"""
Seed-Daten für Odoo 19 Community.

Erstellt Mindest-Testdaten für den Picking-PoC:
- Lagerorte mit Barcodes
- Produkte mit EAN-Barcodes
- Test-Pickings mit verschiedenen Prioritäten, Terminen und Zuständen

Verwendung (generische Testdaten):
    python seed-odoo.py --url http://localhost:8069 --db masterfischer_o19 --user admin --api-key admin

Zweite Lagerinstanz (Compose-Profil `second-odoo`, Port 8070):
    python seed-odoo.py --url http://localhost:8070 --db lager2_o19 --user admin --api-key admin

Verwendung (BOM-basierte Pickings aus echten Produkten, benoetigt `mrp`):
    python seed-odoo.py --url http://localhost:8069 --db masterfischer_o19 --user admin --api-key admin --bom-mode

Odoo-19-Hinweise:
- `stock.move.name` gibt es nicht mehr; die Bewegungsbezeichnung wird aus dem
  Produkt berechnet (`description_picking`).
- `res.users.groups_id` heisst jetzt `group_ids`.
- `--bom-mode` / `--lego-seed` brauchen ein installiertes `mrp`-Modul.
"""
import argparse
import sys
from datetime import date, timedelta
from xmlrpc.client import ServerProxy


ODOO_KWARG_KEYS = {
    "context",
    "count",
    "fields",
    "limit",
    "load",
    "offset",
    "order",
}


def _normalize_execute_args(args, kwargs):
    normalized_args = list(args)
    normalized_kwargs = dict(kwargs)
    if normalized_args and isinstance(normalized_args[-1], dict):
        maybe_kwargs = normalized_args[-1]
        if maybe_kwargs and set(maybe_kwargs).issubset(ODOO_KWARG_KEYS):
            normalized_kwargs.update(normalized_args.pop())
    return normalized_args, normalized_kwargs


def _apply_inventory(execute, quant_ids):
    """stock.quant.action_apply_inventory anwenden.

    Odoo 18 und 19 geben None zurueck; der XML-RPC-Marshaller laeuft mit
    allow_none=False und wirft danach einen Fault. Die Buchung ist zu diesem
    Zeitpunkt bereits committed, deshalb wird genau dieser Fehler geschluckt.
    """
    if not quant_ids:
        return
    try:
        execute("stock.quant", "action_apply_inventory", quant_ids)
    except Exception as apply_err:
        message = str(apply_err)
        if "marshal None" not in message and "allow_none" not in message:
            raise


def build_demo_customers():
    return [
        {
            "name": "ACME Demo GmbH",
            "street": "Musterstrasse 12",
            "zip": "48149",
            "city": "Muenster",
            "country_code": "DE",
            "email": "logistik@acme-demo.example",
            "phone": "+49 251 000001",
        },
        {
            "name": "Meyer Spielwaren KG",
            "street": "Hafenweg 7",
            "zip": "48155",
            "city": "Muenster",
            "country_code": "DE",
            "email": "wareneingang@meyer-demo.example",
            "phone": "+49 251 000002",
        },
        {
            "name": "Fischer Techniklabor AG",
            "street": "Industriestrasse 4",
            "zip": "72178",
            "city": "Waldachtal",
            "country_code": "DE",
            "email": "lab@fischer-demo.example",
            "phone": "+49 7443 000003",
        },
        {
            "name": "FH Demo Logistik",
            "street": "Leonardo-Campus 10",
            "zip": "48149",
            "city": "Muenster",
            "country_code": "DE",
            "email": "laborlogistik@fh-demo.example",
            "phone": "+49 251 000004",
        },
    ]


def build_demo_customer_order_plan():
    return [
        {
            "origin": "SO-DEMO-001",
            "customer_index": 0,
            "delivery_date": "2026-07-09",
            "zone": "Links",
            "products": ["301121", "343721", "4166960"],
        },
        {
            "origin": "SO-DEMO-002",
            "customer_index": 1,
            "delivery_date": "2026-07-09",
            "zone": "Links",
            "products": ["301121", "343724", "4166960"],
        },
        {
            "origin": "SO-DEMO-003",
            "customer_index": 2,
            "delivery_date": "2026-07-09",
            "zone": "Links",
            "products": ["301121", "343701", "4166960"],
        },
        {
            "origin": "SO-DEMO-004",
            "customer_index": 3,
            "delivery_date": "2026-07-09",
            "zone": "Links",
            "products": ["301121", "343721", "4166960"],
        },
        {
            "origin": "SO-DEMO-005",
            "customer_index": 0,
            "delivery_date": "2026-07-10",
            "zone": "Rechts",
            "products": ["4216758", "4250172"],
        },
        {
            "origin": "SO-DEMO-006",
            "customer_index": 1,
            "delivery_date": "2026-07-10",
            "zone": "Rechts",
            "products": ["4216758", "4185178"],
        },
    ]


def build_demo_cluster_products():
    return [
        {"name": "Demo Klemmbaustein 2x4 rot", "barcode": "301121", "default_code": "301121"},
        {"name": "Demo Achse 4M", "barcode": "343721", "default_code": "343721"},
        {"name": "Demo Verbinder blau", "barcode": "4166960", "default_code": "4166960"},
        {"name": "Demo Achse 6M", "barcode": "343724", "default_code": "343724"},
        {"name": "Demo Platte 2x6", "barcode": "343701", "default_code": "343701"},
        {"name": "Demo Technikrahmen rechts", "barcode": "4216758", "default_code": "4216758"},
        {"name": "Demo Zahnrad 20Z", "barcode": "4250172", "default_code": "4250172"},
        {"name": "Demo Winkelverbinder", "barcode": "4185178", "default_code": "4185178"},
    ]


def main():
    parser = argparse.ArgumentParser(description="Odoo Seed-Daten")
    parser.add_argument("--url", default="http://localhost:8069")
    parser.add_argument("--db", default="masterfischer")
    parser.add_argument("--user", default="admin")
    parser.add_argument("--api-key", required=True)
    parser.add_argument("--bom-mode", action="store_true",
                        help="BOM-basierte Pickings aus echten Produkten erstellen (loescht bestehende nicht-done Pickings)")
    parser.add_argument("--lego-seed", action="store_true",
                        help="LEGO-Produkte einlagern + Pickings aus BOMs erstellen (ohne bestehende Pickings zu loeschen)")
    args = parser.parse_args()

    common = ServerProxy(f"{args.url}/xmlrpc/2/common")
    uid = common.authenticate(args.db, args.user, args.api_key, {})
    if not uid:
        print("FEHLER: Authentifizierung fehlgeschlagen")
        sys.exit(1)

    models = ServerProxy(f"{args.url}/xmlrpc/2/object")

    def execute(model, method, *a, **kw):
        call_args, call_kwargs = _normalize_execute_args(a, kw)
        return models.execute_kw(
            args.db, uid, args.api_key, model, method, call_args, call_kwargs
        )

    def find_or_create(model, domain, vals):
        existing = execute(model, "search", domain)
        if existing:
            return existing[0], False
        new_id = execute(model, "create", vals)
        return new_id, True

    def ensure_demo_users():
        print("\nDemo-Benutzer...")
        companies = execute(
            "res.company", "search_read",
            [],
            {"fields": ["id", "name"], "limit": 1},
        )
        if not companies:
            print("  [WARN] Keine Firma gefunden - Demo-Benutzer werden uebersprungen.")
            return
        company_id = companies[0]["id"]

        group_user = execute(
            "ir.model.data", "search_read",
            [("module", "=", "base"), ("name", "=", "group_user")],
            {"fields": ["res_id"], "limit": 1},
        )
        if not group_user:
            print("  [WARN] base.group_user nicht gefunden - Demo-Benutzer werden uebersprungen.")
            return
        group_user_id = group_user[0]["res_id"]

        demo_users = [
            ("Administrator", "admin"),
            ("Lena Lager", "lena.lager"),
            ("Max Picker", "max.picker"),
        ]

        for name, login in demo_users:
            existing = execute(
                "res.users", "search_read",
                [("login", "=", login)],
                {"fields": ["id", "name"], "limit": 1},
            )
            if existing:
                print(f"  [=] existiert: {existing[0]['name']} (Login: {login}, ID: {existing[0]['id']})")
                continue

            try:
                user_id = execute(
                    "res.users",
                    "create",
                    {
                        "name": name,
                        "login": login,
                        "email": f"{login}@local.test",
                        "password": "demo123",
                        "company_id": company_id,
                        "company_ids": [(6, 0, [company_id])],
                        # Odoo 19: res.users.groups_id wurde zu group_ids umbenannt
                        # (all_group_ids ist der berechnete transitive Abschluss).
                        "group_ids": [(6, 0, [group_user_id])],
                        "notification_type": "email",
                        "active": True,
                    },
                )
                print(f"  [OK] erstellt: {name} (Login: {login}, ID: {user_id})")
            except Exception as exc:
                print(f"  [WARN] Demo-Benutzer {name} konnte nicht erstellt werden: {exc}")

    def ensure_demo_customers():
        print("\nDemo-Kunden...")
        customers = build_demo_customers()
        country_codes = sorted({customer["country_code"] for customer in customers})
        countries = execute(
            "res.country",
            "search_read",
            [("code", "in", country_codes)],
            fields=["id", "code"],
            limit=len(country_codes),
        )
        country_by_code = {country["code"]: country["id"] for country in countries}

        partner_ids = {}
        for index, customer in enumerate(customers):
            vals = dict(customer)
            country_code = vals.pop("country_code", "")
            country_id = country_by_code.get(country_code)
            if country_id:
                vals["country_id"] = country_id

            existing = execute(
                "res.partner",
                "search_read",
                [("email", "=", vals["email"])],
                fields=["id", "name"],
                limit=1,
            )
            if existing:
                partner_id = existing[0]["id"]
                execute("res.partner", "write", [partner_id], vals)
                print(f"  [=] aktualisiert: {vals['name']} (ID: {partner_id})")
            else:
                partner_id = execute("res.partner", "create", vals)
                print(f"  [OK] erstellt: {vals['name']} (ID: {partner_id})")
            partner_ids[index] = partner_id
        return partner_ids

    if args.lego_seed:
        seed_lego(execute)
        return

    if args.bom_mode:
        ensure_demo_users()
        seed_bom_pickings(execute)
        return

    ensure_demo_users()

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
        *build_demo_cluster_products(),
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
        prod_ids[prod["default_code"]] = pid
        status = "[OK] erstellt" if created else "[=] existiert"
        print(f"  {status}: {prod['name']} (ID: {pid})")
    product_names = {prod["default_code"]: prod["name"] for prod in products_data}

    # ── Bestand einbuchen ────────────────────────────────────
    print("\nBestaende einbuchen...")

    demo_product_locations = {
        "301121": "LOC-A01",
        "343721": "LOC-A02",
        "4166960": "LOC-A02",
        "343724": "LOC-A02",
        "343701": "LOC-A02",
        "4216758": "LOC-B01",
        "4250172": "LOC-B02",
        "4185178": "LOC-B02",
    }

    stock_quants = [
        (prod_ids["4006381333931"], loc_ids["LOC-A01"], 100),
        (prod_ids["4006381333948"], loc_ids["LOC-A02"], 200),
        (prod_ids["4006381333955"], loc_ids["LOC-A02"], 150),
        (prod_ids["5901234123457"], loc_ids["LOC-B01"], 50),
        (prod_ids["7622210100528"], loc_ids["LOC-B02"], 30),
        (prod_ids["4006381334013"], loc_ids["LOC-C02"], 80),
        (prod_ids["4006381334020"], loc_ids["LOC-D01"], 60),
    ]
    stock_quants.extend(
        (prod_ids[code], loc_ids[location_barcode], 80)
        for code, location_barcode in demo_product_locations.items()
    )

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
                _apply_inventory(execute, quant_ids)
            print(f"  [OK] {qty} Stk. eingebucht (Produkt {product_id} -> Lagerort {location_id})")
        except Exception as e:
            print(f"  [WARN] Bestand-Einbuchung uebersprungen: {e}")

    demo_partner_ids = ensure_demo_customers()

    # ── Picking-Typ ermitteln ────────────────────────────────
    print("\nPickings...")

    pick_type = execute(
        "stock.picking.type", "search_read",
        [("code", "=", "outgoing")],
        fields=["id", "default_location_src_id", "default_location_dest_id"],
        limit=1,
    )
    if not pick_type:
        pick_type = execute(
            "stock.picking.type", "search_read",
            [("code", "=", "internal")],
            fields=["id", "default_location_src_id", "default_location_dest_id"],
            limit=1,
        )

    if not pick_type:
        print("  [WARN] Kein Picking-Typ gefunden — Pickings werden nicht erstellt.")
    else:
        pt = pick_type[0]
        src = pt["default_location_src_id"][0] if pt["default_location_src_id"] else parent_id
        dest = pt["default_location_dest_id"][0] if pt["default_location_dest_id"] else loc_ids["LOC-C01"]

        def make_picking(moves, priority="0", scheduled_date=None, partner_id=None,
                         origin=None, date_deadline=None):
            vals = {
                "picking_type_id": pt["id"],
                "location_id": src,
                "location_dest_id": dest,
                "priority": priority,
                # Odoo 19: stock.move.name existiert nicht mehr. Die Bewegungs-
                # bezeichnung wird aus dem Produkt berechnet (description_picking).
                "move_ids": [
                    (0, 0, {
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
            if date_deadline:
                vals["date_deadline"] = date_deadline
            if partner_id:
                vals["partner_id"] = partner_id
            if origin:
                vals["origin"] = origin
            pid = execute("stock.picking", "create", vals)
            execute("stock.picking", "action_confirm", [pid])
            execute("stock.picking", "action_assign", [pid])
            return pid

        print("\nCluster-Demo-Auftraege...")
        for order in build_demo_customer_order_plan():
            moves = [
                {
                    "name": product_names[code],
                    "product_id": prod_ids[code],
                    "qty": 4,
                    "loc_src": loc_ids[demo_product_locations[code]],
                }
                for code in order["products"]
            ]
            partner_id = demo_partner_ids.get(order["customer_index"])
            pick_id = make_picking(
                moves=moves,
                priority="0",
                scheduled_date=order["delivery_date"],
                date_deadline=order["delivery_date"],
                partner_id=partner_id,
                origin=order["origin"],
            )
            print(
                f"  [OK] {order['origin']} - {order['zone']}, "
                f"Lieferdatum {order['delivery_date']} (ID: {pick_id})"
            )

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
                execute("stock.move.line", "write", ml_ids, {"quantity": 6.0, "picked": True})
        print(f"  [OK] Picking 9 - Teilweise erledigt (1/3)      (ID: {p9})")

    # ── Pflichtmodule pruefen ────────────────────────────────
    print("\nPflichtmodule...")
    try:
        modules = execute(
            "ir.module.module", "search_read",
            [("name", "in", ["quality_alert_custom", "stock_picking_batch"])],
            fields=["name", "state"],
        )
        module_by_name = {module["name"]: module for module in modules}
        for module_name in ["quality_alert_custom", "stock_picking_batch"]:
            module = module_by_name.get(module_name)
            if module:
                print(f"  {module_name}: {module['state']}")
                if module["state"] != "installed":
                    print("  [WARN] Modul nicht installiert! In Odoo Apps installieren.")
            else:
                print(f"  [WARN] Modul {module_name} nicht gefunden. 'Update Apps List' in Odoo ausfuehren.")
    except Exception as e:
        print(f"  [WARN] Pruefung fehlgeschlagen: {e}")

    print("\nSeed-Daten komplett!")


def seed_lego(execute):
    """
    LEGO-Seed: Bestand fuer alle BOM-Komponenten auffuellen und
    danach neue Pickings fuer die wichtigsten Lego-Produkte erstellen.

    Loescht keine bestehenden Pickings.
    """
    from datetime import date, timedelta
    today = date.today()
    yesterday = (today - timedelta(days=1)).isoformat()
    tomorrow = (today + timedelta(days=1)).isoformat()
    today_str = today.isoformat()

    # ── Lagerorte laden / erstellen ───────────────────────────
    print("\nLEGO-Seed: Lagerorte...")
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
        {"name": "Regal D-01", "barcode": "LOC-D01"},
    ]
    loc_ids = {}
    for loc in locations_data:
        existing = execute("stock.location", "search", [("barcode", "=", loc["barcode"])])
        if existing:
            loc_ids[loc["barcode"]] = existing[0]
        else:
            lid = execute("stock.location", "create",
                          {**loc, "usage": "internal", "location_id": parent_id})
            loc_ids[loc["barcode"]] = lid
            print(f"  [OK] Lagerort erstellt: {loc['name']}")
    print(f"  {len(loc_ids)} Lagerorte bereit")

    # Auswahl-Lagerorte fuer Bestand-Verteilung
    restock_locs = [
        loc_ids.get("LOC-A01"),
        loc_ids.get("LOC-A02"),
        loc_ids.get("LOC-B01"),
        loc_ids.get("LOC-B02"),
        loc_ids.get("LOC-C01"),
        loc_ids.get("LOC-D01"),
    ]
    restock_locs = [l for l in restock_locs if l]

    # ── BOMs laden (IDs 12-22 = LEGO-Sortiment) ──────────────
    print("\nLEGO-Seed: Lade Stuecklisten...")
    lego_bom_ids = [12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22]
    boms = execute(
        "mrp.bom", "search_read",
        [("id", "in", lego_bom_ids)],
        fields=["id", "product_tmpl_id", "code", "bom_line_ids"],
    )
    print(f"  {len(boms)} Stuecklisten geladen")

    # ── Alle Komponenten-Produkte sammeln ─────────────────────
    all_bom_line_ids = []
    for bom in boms:
        all_bom_line_ids.extend(bom.get("bom_line_ids", []))

    component_lines = execute(
        "mrp.bom.line", "search_read",
        [("bom_id", "in", lego_bom_ids)],
        fields=["product_id", "product_qty"],
    ) if all_bom_line_ids else []

    # Einzigartige Produkt-IDs
    component_product_ids = list({line["product_id"][0] for line in component_lines if line.get("product_id")})
    print(f"  {len(component_product_ids)} einzigartige Komponenten-Produkte")

    # ── Bestand einbuchen ─────────────────────────────────────
    print("\nLEGO-Seed: Bestand einbuchen...")
    import random
    random.seed(42)  # Reproduzierbar

    stocked = 0
    for i, product_id in enumerate(component_product_ids):
        loc_id = restock_locs[i % len(restock_locs)]
        qty = random.choice([30, 40, 50, 60, 70, 80])

        try:
            # Vorhandenen Quant suchen
            existing_quants = execute(
                "stock.quant", "search",
                [("product_id", "=", product_id), ("location_id", "=", loc_id)],
            )
            if existing_quants:
                execute("stock.quant", "write", existing_quants,
                        {"inventory_quantity": qty})
            else:
                existing_quants = [execute("stock.quant", "create", {
                    "product_id": product_id,
                    "location_id": loc_id,
                    "inventory_quantity": qty,
                })]
            _apply_inventory(execute, existing_quants)
            stocked += 1
        except Exception as e:
            print(f"  [WARN] Bestand fuer Produkt {product_id}: {e}")

    print(f"  {stocked} Produkte eingelagert")

    # ── Pickings aus BOMs erstellen ────────────────────────────
    print("\nLEGO-Seed: Erstelle Pickings...")

    # Picking-Typ: Internal Transfer
    pick_type = execute(
        "stock.picking.type", "search_read",
        [("code", "=", "internal")],
        fields=["id", "default_location_src_id", "default_location_dest_id"],
        limit=1,
    )
    if not pick_type:
        print("  [WARN] Kein Internal-Transfer-Typ gefunden - Pickings werden uebersprungen.")
        return
    pt = pick_type[0]

    mfg_loc = execute(
        "stock.location", "search_read",
        [("usage", "=", "internal"), ("name", "=", "Manufacturing")],
        fields=["id"], limit=1,
    )
    dest_loc_id = mfg_loc[0]["id"] if mfg_loc else pt["default_location_dest_id"][0]

    # Konfiguration: BOM-ID -> (Prioritaet, Datum, Label)
    picking_config = [
        (21, "0",  today_str,  "Normal, heute"),         # Ente Henri
        (16, "1",  today_str,  "DRINGEND, heute"),       # Wal
        (15, "0",  tomorrow,   "Normal, morgen"),        # Windkraft
        (19, "1",  today_str,  "DRINGEND, heute"),       # Blume
        (12, "0",  today_str,  "Normal, heute"),         # Sparkasse
        (20, "1",  yesterday,  "DRINGEND, ueberfaellig"),# LKW
        (13, "0",  tomorrow,   "Normal, morgen"),        # Papagei Moritz
        (17, "1",  today_str,  "DRINGEND, heute"),       # Krebs Max
        (18, "0",  tomorrow,   "Normal, morgen"),        # Erwin
    ]

    bom_map = {b["id"]: b for b in boms}
    created = 0

    for bom_id, priority, sched_date, label in picking_config:
        bom = bom_map.get(bom_id)
        if not bom:
            print(f"  [SKIP] BOM {bom_id} nicht gefunden")
            continue

        product_name = bom["product_tmpl_id"][1]

        # Komponenten mit Bestand suchen
        lines = execute(
            "mrp.bom.line", "search_read",
            [("bom_id", "=", bom_id)],
            fields=["product_id", "product_qty"],
        )
        components = []
        for line in lines:
            pid = line["product_id"][0]
            quants = execute(
                "stock.quant", "search_read",
                [("product_id", "=", pid), ("quantity", ">", 0),
                 ("location_id.usage", "=", "internal"),
                 ("location_id", "!=", dest_loc_id)],
                fields=["location_id", "quantity"],
                order="quantity desc",
                limit=1,
            )
            if quants:
                components.append({
                    "product_id": pid,
                    "product_name": line["product_id"][1],
                    "qty": line["product_qty"],
                    "location_id": quants[0]["location_id"][0],
                })

        if not components:
            print(f"  [SKIP] Keine Komponenten mit Bestand fuer {product_name}")
            continue

        try:
            vals = {
                "picking_type_id": pt["id"],
                "location_id": pt["default_location_src_id"][0] if pt["default_location_src_id"] else False,
                "location_dest_id": dest_loc_id,
                "priority": priority,
                "origin": f"{product_name} (BOM {bom['code']})",
                "scheduled_date": sched_date,
                # Odoo 19: stock.move.name entfaellt (siehe make_picking).
                "move_ids": [
                    (0, 0, {
                        "product_id": c["product_id"],
                        "product_uom_qty": c["qty"],
                        "location_id": c["location_id"],
                        "location_dest_id": dest_loc_id,
                    })
                    for c in components
                ],
            }
            pick_id = execute("stock.picking", "create", vals)
            execute("stock.picking", "action_confirm", [pick_id])
            execute("stock.picking", "action_assign", [pick_id])
            prio_str = "DRINGEND" if priority == "1" else "Normal  "
            print(f"  [OK] {prio_str} | {label:25} | {product_name} -> Picking {pick_id}")
            created += 1
        except Exception as e:
            print(f"  [WARN] Picking fuer {product_name} fehlgeschlagen: {e}")

    print(f"\nLEGO-Seed abgeschlossen: {stocked} Produkte eingelagert, {created} Pickings erstellt.")
    print("Tipp: PWA-Picking-Liste zeigt jetzt LEGO-Produkte mit Kachelbild.")


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
            # Odoo 19: stock.move.name entfaellt (siehe make_picking).
            "move_ids": [
                (0, 0, {
                    "product_id": c["product_id"],
                    "product_uom_qty": c["qty"],
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
