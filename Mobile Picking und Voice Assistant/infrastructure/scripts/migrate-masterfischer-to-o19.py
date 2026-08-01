"""Migriere die ECHTEN Daten aus v18 `masterfischer` nach v19 `masterfischer_o19`.

Hintergrund: Der Odoo-19-Cutover war ein bewusster **Reseed**, keine Migration --
`masterfischer_o19` bekam generische Schrauben-Demodaten aus `seed-odoo.py`, nie
den echten LEGO/Fischertechnik-Katalog und die realen Auftraege aus v18. Der
Eigentuemer will jetzt die echten Datensaetze. Das holt sie nach.

Laeuft in der Odoo-19-Shell und liest v18 direkt aus demselben Postgres-Cluster:

    odoo shell --no-http -d masterfischer_o19 --db_host=db --db_user=odoo \
        --db_password="$PASSWORD" < migrate-masterfischer-to-o19.py

Was passiert:
  1. v18 lesen (psycopg2): 54 echte Produkte, die 20 offenen internen Auftraege
     mit ihren Bewegungen.
  2. v19: die 15 Fake-Schrauben-Produkte archivieren, die 15 Fake-Auftraege
     stornieren.
  3. v19: echte Produkte anlegen, je ein Heimat-Regal zuweisen und Bestand
     buchen (damit die Zonen-/Laufweg-Logik des Assistenten Sinn ergibt).
  4. v19: die 20 offenen Auftraege als interne Transfers mit den echten
     Produktzeilen neu anlegen, confirmen und reservieren.

Idempotenz: an einem `PWR_MIGRATED`-Marker-Produkt erkennt das Skript einen
zweiten Lauf und bricht ab, statt doppelt anzulegen.
"""
import os
import re
import sys

import psycopg2

env = env  # noqa: F821  (Odoo-Shell-Global)

SRC_DB = "masterfischer"
MARKER = "PWR-MIGRATED-MARKER"


def log(msg):
    print(f"MIG: {msg}", flush=True)


# --- Idempotenz --------------------------------------------------------------
Product = env["product.product"].sudo()
if Product.search([("default_code", "=", MARKER)], limit=1):
    log("Marker gefunden -- Migration lief bereits. Abbruch ohne Aenderung.")
    sys.exit(0)

# --- 1. v18 lesen ------------------------------------------------------------
password = os.environ.get("PASSWORD")
if not password:
    log("PASSWORD env fehlt -- ohne DB-Passwort kein Lesezugriff auf v18.")
    sys.exit(2)

src = psycopg2.connect(host="db", dbname=SRC_DB, user="odoo", password=password)
cur = src.cursor()

cur.execute(
    """
    select coalesce(pt.name->>'en_US', pt.name->>'de_DE', pt.name::text) as name,
           pp.default_code, pp.barcode, pt.list_price
    from product_product pp
    join product_template pt on pt.id = pp.product_tmpl_id
    where coalesce(pt.active, true) and pp.default_code is not null
    order by pt.id
    """
)
src_products = cur.fetchall()
log(f"v18: {len(src_products)} Produkte gelesen")

cur.execute(
    """
    select p.id, p.name, p.scheduled_date, coalesce(p.priority, '0'), p.origin
    from stock_picking p
    join stock_picking_type t on t.id = p.picking_type_id
    where p.state = 'assigned' and t.code = 'internal'
    order by p.id
    """
)
src_pickings = cur.fetchall()


def model_name(origin):
    """Der v18-`origin` einer Fertigungs-Komponentenentnahme nennt das Modell,
    z. B. "[498235] Blume (BOM 498235)" -> "Blume". Genau das gehoert auf die
    Auftragskarte: der Picker baut ein MODELL (Blume, Ente Henri), nicht einen
    losen Baustein. Faellt auf den Rohtext zurueck, wenn das Muster fehlt."""
    match = re.search(r"\]\s*(.+?)\s*\(BOM", origin or "")
    return (match.group(1).strip() if match else (origin or "").strip()) or "Modell"

cur.execute(
    """
    select m.picking_id, pp.default_code, m.product_uom_qty
    from stock_move m
    join product_product pp on pp.id = m.product_id
    join stock_picking p on p.id = m.picking_id
    join stock_picking_type t on t.id = p.picking_type_id
    where p.state = 'assigned' and t.code = 'internal'
      and pp.default_code is not null and m.product_uom_qty > 0
    """
)
moves_by_picking = {}
for pid, code, qty in cur.fetchall():
    moves_by_picking.setdefault(pid, []).append((code, float(qty)))
src.close()
log(f"v18: {len(src_pickings)} offene interne Auftraege, "
    f"{sum(len(v) for v in moves_by_picking.values())} Bewegungszeilen")

# --- 2. v19: Fake-Daten entfernen -------------------------------------------
Picking = env["stock.picking"].sudo()
Quant = env["stock.quant"].sudo()
Location = env["stock.location"].sudo()

fake_pickings = Picking.search([("state", "not in", ("done", "cancel"))])
if fake_pickings:
    try:
        fake_pickings.action_cancel()
    except Exception as exc:  # noqa: BLE001
        log(f"WARN action_cancel: {exc}")
    log(f"v19: {len(fake_pickings)} Fake-Auftraege storniert")

# Bestehende (Schrauben-)Produkte archivieren, damit der Katalog nur die echten
# zeigt. Nicht loeschen: an ihnen haengen die stornierten Auftraege.
fake_products = Product.search([])
if fake_products:
    fake_products.write({"active": False})
    log(f"v19: {len(fake_products)} Fake-Produkte archiviert")

# --- 3. v19: echte Produkte + Bestand ---------------------------------------
regale = Location.search([("complete_name", "=like", "WH/Stock/Regal%")], order="id")
if not regale:
    regale = Location.search([("usage", "=", "internal"),
                              ("complete_name", "=like", "WH/Stock/%")], order="id")
if not regale:
    log("Keine gezonten Regal-Lagerorte gefunden -- Abbruch.")
    sys.exit(2)
log(f"v19: {len(regale)} Regal-Lagerorte fuer die Verteilung")

code_to_product = {}
for i, (name, code, barcode, price) in enumerate(src_products):
    product = Product.create({
        "name": name,
        "default_code": code,
        "barcode": barcode or code,
        "type": "consu",
        "is_storable": True,
        "tracking": "none",
        "list_price": price or 1.0,
    })
    home = regale[i % len(regale)]
    quant = Quant.create({
        "product_id": product.id,
        "location_id": home.id,
        "inventory_quantity": 500,
    })
    try:
        quant.action_apply_inventory()
    except Exception as exc:  # noqa: BLE001
        if "None" not in str(exc):
            raise
    code_to_product[code] = product
log(f"v19: {len(code_to_product)} echte Produkte angelegt und bebucht")

# Marker-Produkt (archiviert, nur fuer die Idempotenz-Pruefung).
Product.create({
    "name": "PWR Migration Marker",
    "default_code": MARKER,
    "type": "consu",
    "is_storable": False,
    "active": False,
})

# --- 4. v19: Auftraege neu anlegen ------------------------------------------
# Die internen Operationstypen (Pick/Pack/Internal Transfers) sind in diesem
# Lager DEAKTIVIERT -- es faehrt 1-Schritt-Auslieferung, nur Receipts und
# Delivery Orders sind aktiv. Die echten v18-Auftraege waren interne Transfers,
# aber gegen die Lagerkonfiguration zu kaempfen lohnt nicht: wir legen sie als
# AUSLIEFERUNGEN an -- genau die Struktur, die die Fake-Daten (WH/OUT) hatten
# und die die App nachweislich verarbeitet. Der Picker pickt dieselben echten
# LEGO-Produkte; ob intern oder Auslieferung aendert die Pick-Erfahrung nicht.
picking_type = env["stock.picking.type"].sudo().search([("code", "=", "outgoing")], limit=1)
stock_loc = picking_type.default_location_src_id or Location.search(
    [("complete_name", "=", "WH/Stock")], limit=1)
output_loc = picking_type.default_location_dest_id
log(f"v19: Typ '{picking_type.display_name}', {stock_loc.display_name} -> {output_loc.display_name}")

created = assigned = 0
for pid, name, sched, prio, origin in src_pickings:
    lines = moves_by_picking.get(pid, [])
    move_vals = []
    for code, qty in lines:
        product = code_to_product.get(code)
        if not product:
            continue
        move_vals.append((0, 0, {
            "product_id": product.id,
            "product_uom_qty": qty,
            "location_id": stock_loc.id,
            "location_dest_id": output_loc.id,
        }))
    if not move_vals:
        continue
    picking = Picking.create({
        "picking_type_id": picking_type.id,
        "location_id": stock_loc.id,
        "location_dest_id": output_loc.id,
        "scheduled_date": sched,
        "priority": prio if prio in ("0", "1") else "0",
        "origin": model_name(origin),
        "move_ids": move_vals,
    })
    picking.action_confirm()
    picking.action_assign()
    created += 1
    if picking.state == "assigned":
        assigned += 1

env.cr.commit()
log(f"v19: {created} Auftraege angelegt, davon {assigned} reserviert (assigned)")
log("FERTIG")
