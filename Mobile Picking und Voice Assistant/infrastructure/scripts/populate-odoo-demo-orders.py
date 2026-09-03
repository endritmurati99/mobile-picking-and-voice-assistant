"""Fill the two demo warehouses to a fixed number of open LEGO pickings.

Run through ``odoo shell``. Dry-run is the default; set ``POPULATE_APPLY=1``
to commit. The authoritative LEGO fixture must be available at
``RECONCILE_FIXTURE``.
"""

import json
import os
from datetime import date


ALLOWED_DATABASES = {"masterfischer_o19", "lager2_o19"}
TARGET = int(os.environ.get("POPULATE_TARGET", "120"))
APPLY = os.environ.get("POPULATE_APPLY") == "1"
FIXTURE = os.environ.get("RECONCILE_FIXTURE", "/tmp/lego-catalog-o19.json")
OPEN_STATES = ["confirmed", "assigned"]


def population_plan(open_count, target, cluster_candidates):
    selected = list(cluster_candidates[:8])
    return max(0, target - open_count), sorted(selected) if len(selected) >= 2 else []


def run(odoo_env):
    db = odoo_env.cr.dbname
    if db not in ALLOWED_DATABASES:
        raise RuntimeError(f"Refusing unexpected database: {db}")

    with open(FIXTURE, encoding="utf-8") as handle:
        codes = [item["code"] for item in json.load(handle)]

    products = odoo_env["product.product"].search([("default_code", "in", codes)])
    if len(products) != len(codes):
        raise RuntimeError(f"Expected {len(codes)} LEGO products, found {len(products)}")

    Picking = odoo_env["stock.picking"]
    open_domain = [("state", "in", OPEN_STATES)]
    open_count = Picking.search_count(open_domain)
    create_count, _ = population_plan(open_count, TARGET, [])
    if not APPLY:
        print(json.dumps({"db": db, "apply": False, "open": open_count, "create": create_count}))
        odoo_env.cr.rollback()
        return

    picking_type = odoo_env["stock.picking.type"].search([("code", "=", "outgoing")], limit=1)
    if not picking_type or not picking_type.default_location_src_id or not picking_type.default_location_dest_id:
        raise RuntimeError("Outgoing picking type with source and destination is required")
    source = picking_type.default_location_src_id
    destination = picking_type.default_location_dest_id

    # Lager 2 starts empty. Fifty units per SKU comfortably cover 120 small demo orders.
    Quant = odoo_env["stock.quant"]
    for product in products:
        available = Quant._get_available_quantity(product, source)
        if available < 50:
            Quant._update_available_quantity(product, source, 50 - available)

    admin = odoo_env["res.users"].search([("login", "=", "admin")], limit=1)
    if not admin:
        raise RuntimeError("Admin user not found")

    created = odoo_env["stock.picking"]
    ordered_products = products.sorted(lambda product: product.default_code or "")
    for index in range(create_count):
        first = ordered_products[index % len(ordered_products)]
        second = ordered_products[(index * 7 + 1) % len(ordered_products)]
        picking = Picking.create({
            "picking_type_id": picking_type.id,
            "location_id": source.id,
            "location_dest_id": destination.id,
            "priority": "1" if index % 12 == 0 else "0",
            "scheduled_date": date.today().isoformat(),
            "origin": f"PWA-DEMO-{db}-{open_count + index + 1:03d}",
            "partner_id": admin.partner_id.id,
            "move_ids": [(0, 0, {
                "product_id": product.id,
                "product_uom_qty": 1,
                "location_id": source.id,
                "location_dest_id": destination.id,
            }) for product in (first, second)],
        })
        picking.action_confirm()
        picking.action_assign()
        created |= picking

    batch_created = False
    if db == "masterfischer_o19":
        Batch = odoo_env["stock.picking.batch"]
        active = Batch.search([("user_id", "=", admin.id), ("state", "=", "in_progress")], limit=1)
        if not active:
            candidates = Picking.search([
                ("state", "=", "assigned"),
                ("batch_id", "=", False),
            ], order="id desc", limit=8)
            _, cluster_ids = population_plan(TARGET, TARGET, candidates.ids)
            if len(cluster_ids) < 2:
                raise RuntimeError("Not enough assigned pickings for an admin cluster")
            batch = Batch.create({"picking_ids": [(6, 0, cluster_ids)], "user_id": admin.id})
            for box_index, picking in enumerate(Picking.browse(cluster_ids), 1):
                package = odoo_env["stock.package"].create({
                    "name": f"CLUSTER-B{box_index}/{picking.name}",
                })
                picking.move_line_ids.write({"result_package_id": package.id})
            batch.action_confirm()
            batch_created = True

    final_open = Picking.search_count(open_domain)
    non_lego_moves = odoo_env["stock.move"].search_count([
        ("picking_id.state", "in", OPEN_STATES),
        ("product_id", "not in", products.ids),
    ])
    if final_open != TARGET or non_lego_moves:
        raise RuntimeError(f"Postcondition failed: open={final_open}, non_lego_moves={non_lego_moves}")
    if db == "masterfischer_o19" and not odoo_env["stock.picking.batch"].search_count([
        ("user_id", "=", admin.id), ("state", "=", "in_progress")
    ]):
        raise RuntimeError("Postcondition failed: no active admin cluster")

    odoo_env.cr.commit()
    print(json.dumps({
        "db": db,
        "apply": True,
        "created": len(created),
        "open": final_open,
        "assigned": Picking.search_count([("state", "=", "assigned")]),
        "admin_cluster_created": batch_created,
    }))


if __name__ == "__main__":
    run(env)
