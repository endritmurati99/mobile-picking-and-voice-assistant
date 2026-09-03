"""Reconcile one Odoo database to the fixed 47-SKU LEGO catalog.

Run through ``odoo shell``. It always rolls back unless ``--apply`` is passed
through ``RECONCILE_ARGS``; see the commands printed in the task report.
"""

from collections import Counter
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import shlex
from typing import NamedTuple


class SafetyError(RuntimeError):
    pass


class CatalogItem(NamedTuple):
    code: str
    name: str
    barcode: str = ""
    product_type: str = "consu"
    sale_ok: bool = True
    purchase_ok: bool = True
    tracking: str = "none"
    list_price: float = 1.0
    standard_price: float = 0.0
    is_storable: bool = True
    image_1920: str = ""
    ai_reference_description: str = ""
    ai_reference_image_sha1: str = ""
    ai_reference_reviewed: bool = False
    description: str = ""
    description_sale: str = ""
    description_purchase: str = ""
    description_picking: str = ""
    description_pickingin: str = ""
    description_pickingout: str = ""
    weight: float = 0.0
    volume: float = 0.0

    def values(self):
        return {
            "name": self.name,
            "default_code": self.code,
            "barcode": self.barcode or self.code,
            "active": True,
            "type": self.product_type,
            "sale_ok": self.sale_ok,
            "purchase_ok": self.purchase_ok,
            "tracking": self.tracking,
            "list_price": self.list_price,
            "standard_price": self.standard_price,
            "is_storable": self.is_storable,
            "image_1920": self.image_1920 or False,
            "ai_reference_description": self.ai_reference_description or False,
            "ai_reference_image_sha1": self.ai_reference_image_sha1 or False,
            "ai_reference_reviewed": self.ai_reference_reviewed,
            "description": self.description or False,
            "description_sale": self.description_sale or False,
            "description_purchase": self.description_purchase or False,
            "description_picking": self.description_picking or False,
            "description_pickingin": self.description_pickingin or False,
            "description_pickingout": self.description_pickingout or False,
            "weight": self.weight,
            "volume": self.volume,
        }


LEGO_CATALOG = tuple(
    CatalogItem(code, name)
    for code, name in (
        ("173057", "LKW"),
        ("184779", "Krebs Max"),
        ("237828", "Windkraft"),
        ("274816", "Erwin"),
        ("301121", "Brick 2x4 rot"),
        ("301124", "Brick 2x2 hellgrün"),
        ("324876", "Papagei Moritz"),
        ("343701", "Brick 2x2 weiß"),
        ("343721", "Brick 2x2 rot"),
        ("343724", "Brick 2x2 gelb"),
        ("4100853", "Flower gelb"),
        ("4159527", "Brick 2x2 orange"),
        ("4166960", "Brick 2x2 blau"),
        ("4183780", "Brick 2x2 grün"),
        ("4185178", "Plate 2x4 grün"),
        ("419375", "Helikopter"),
        ("4216758", "Plate 2x4 blau"),
        ("4250172", "Plate 2x4 weiß"),
        ("4250173", "Plate 2x4 pink"),
        ("4648231", "Brick 2x2 hellgelb"),
        ("4648234", "Brick 2x2 pink"),
        ("4652854", "Brick 2x4 W. Bows blau"),
        ("498235", "Blume"),
        ("518295", "Wal"),
        ("6004979", "Brick 2x4 W. Inv. Bows grün"),
        ("6023350", "Brick 2x2x2 R=15 gelb"),
        ("6059082", "Plate 2x6 weiß"),
        ("6096680", "Brick Round 2x2x2 weiß"),
        ("6101121", "Brick 1x2x2 weiß"),
        ("6135522", "Brick 2x4 W. Bows weiß"),
        ("6138111", "Brick Bow 2x3x1 hellblau"),
        ("6167549", "Brick 2x3 W. Inv. Bow gelb"),
        ("6171865", "Brick 2x4 W. Inv. Bows gelb"),
        ("619287", "Ente Henri"),
        ("6214736", "Flower grün"),
        ("6256703", "Roof Tile 4x2 Deg. 45 W/O Knobs rot"),
        ("6269088", "Brick 2x2 dot blau Propeller"),
        ("6286339", "Brick 2x2x1.5 Outside Bow No. 9 blau"),
        ("6294208", "Flower hellblau"),
        ("6294237", "Brick 2x2 hellblau"),
        ("6294241", "Brick 2x3 W. Inv. Bow hellblau"),
        ("6294939", "Brick 2x4 hellgelb"),
        ("6294943", "Brick 2x4 W. Inv. Bows blau"),
        ("6346241", "Roof Tile 2x2x2 Deg. 54 blau"),
        ("6380873", "Brick 2x4 W. Bows gelb"),
        ("834593", "Burger"),
        ("926404", "Sparkasse"),
    )
)

ALLOWED_DATABASES = {"masterfischer_o19", "lager2_o19"}
CATALOG_FIXTURE_SHA256 = "9c03764e44ff7750b6888920b3de3dc600ea1557517d2627859864977271a223"
DELETED_TARGET_TABLES = {
    "product_product", "product_template", "stock_picking", "stock_move",
    "stock_move_line", "stock_quant",
}


def load_catalog(path):
    raw = Path(path).read_bytes()
    if hashlib.sha256(raw).hexdigest() != CATALOG_FIXTURE_SHA256:
        raise SafetyError("catalog fixture SHA-256 differs from the reviewed export")
    rows = json.loads(raw)
    catalog = tuple(CatalogItem(**row) for row in rows)
    if len(catalog) != 47 or {item.code for item in catalog} != {
        item.code for item in LEGO_CATALOG
    }:
        raise SafetyError("fixture does not contain the exact 47-SKU allowlist")
    return catalog


class ProductState(NamedTuple):
    token: object
    code: str
    name: str
    barcode: str
    active: bool
    product_type: str
    sale_ok: bool
    purchase_ok: bool
    tracking: str
    list_price: float
    standard_price: float
    is_storable: bool
    image_1920: str
    ai_reference_description: str
    ai_reference_image_sha1: str
    ai_reference_reviewed: bool
    description: str = ""
    description_sale: str = ""
    description_purchase: str = ""
    description_picking: str = ""
    description_pickingin: str = ""
    description_pickingout: str = ""
    weight: float = 0.0
    volume: float = 0.0


class ForeignKeyState(NamedTuple):
    target_table: str
    dependent_table: str
    dependent_column: str
    delete_rule: str
    count: int
    inside_deletion: bool = False
    touches_protected: bool = False


class Snapshot(NamedTuple):
    products: tuple
    templates: int
    nonlego_pickings: int
    nonlego_picking_states: tuple
    mixed_pickings: int
    nonlego_moves: int
    nonlego_move_lines: int
    nonlego_quants: int
    restricted_dependencies: tuple
    protected_history: tuple
    fk_inventory: tuple = ()
    deleted_fk_residue: tuple = ()


class Plan(NamedTuple):
    delete_tokens: tuple
    update_tokens: tuple
    create_items: tuple

    @property
    def changed(self):
        return bool(self.delete_tokens or self.update_tokens or self.create_items)


class Result(NamedTuple):
    mode: str
    changed: bool
    plan: Plan
    before: Snapshot
    after: object


def _matches(product, item):
    return (
        product.code == item.code
        and product.name == item.name
        and product.barcode == (item.barcode or item.code)
        and product.active
        and product.product_type == item.product_type
        and product.sale_ok == item.sale_ok
        and product.purchase_ok == item.purchase_ok
        and product.tracking == item.tracking
        and product.list_price == item.list_price
        and product.standard_price == item.standard_price
        and product.is_storable == item.is_storable
        and product.image_1920 == item.image_1920
        and product.ai_reference_description == item.ai_reference_description
        and product.ai_reference_image_sha1 == item.ai_reference_image_sha1
        and product.ai_reference_reviewed == item.ai_reference_reviewed
        and product.description == item.description
        and product.description_sale == item.description_sale
        and product.description_purchase == item.description_purchase
        and product.description_picking == item.description_picking
        and product.description_pickingin == item.description_pickingin
        and product.description_pickingout == item.description_pickingout
        and product.weight == item.weight
        and product.volume == item.volume
    )


def unsafe_fk_dependencies(inventory):
    unsafe = []
    for fk in inventory:
        if not fk.count or (fk.inside_deletion and not fk.touches_protected):
            continue
        unsafe.append((f"{fk.dependent_table}.{fk.dependent_column}", fk.count))
    return tuple(unsafe)


def plan_reconciliation(snapshot, catalog=LEGO_CATALOG):
    desired = {item.code: item for item in catalog}
    candidates = {}
    delete = []
    for product in snapshot.products:
        if product.code not in desired or product.name.startswith("Demo "):
            delete.append(product.token)
            continue
        candidates.setdefault(product.code, []).append(product)

    updates = []
    creates = []
    for code, item in desired.items():
        matches = candidates.get(code, ())
        if len(matches) > 1:
            raise SafetyError(f"duplicate non-demo product for SKU {code}")
        if not matches:
            creates.append(item)
        elif not _matches(matches[0], item):
            updates.append(matches[0].token)

    if snapshot.mixed_pickings:
        raise SafetyError("mixed LEGO/non-LEGO picking detected")
    blocked_states = dict(snapshot.nonlego_picking_states)
    if blocked_states.get("done"):
        raise SafetyError("done non-LEGO picking detected")
    fk_unsafe = unsafe_fk_dependencies(snapshot.fk_inventory)
    blocked = tuple(snapshot.restricted_dependencies) + fk_unsafe
    if blocked:
        raise SafetyError(
            "restricted non-LEGO dependencies: "
            + ", ".join(f"{name}={count}" for name, count in blocked)
        )
    return Plan(tuple(delete), tuple(updates), tuple(creates))


def postcondition_errors(snapshot, catalog=LEGO_CATALOG, protected_history=None):
    errors = []
    desired = {item.code: item for item in catalog}
    products_by_code = {}
    for product in snapshot.products:
        products_by_code.setdefault(product.code, []).append(product)
    if len(snapshot.products) != len(catalog):
        errors.append(f"products={len(snapshot.products)}, expected={len(catalog)}")
    if snapshot.templates != len(catalog):
        errors.append(f"templates={snapshot.templates}, expected={len(catalog)}")
    if set(products_by_code) != set(desired):
        errors.append("SKU set differs from allowlist")
    for code, item in desired.items():
        records = products_by_code.get(code, ())
        if len(records) != 1 or not _matches(records[0], item):
            errors.append(f"catalog mismatch for SKU {code}")
    residue = {
        "pickings": snapshot.nonlego_pickings,
        "moves": snapshot.nonlego_moves,
        "move_lines": snapshot.nonlego_move_lines,
        "quants": snapshot.nonlego_quants,
    }
    if any(residue.values()):
        errors.append("non-LEGO residue: " + ", ".join(f"{k}={v}" for k, v in residue.items()))
    if protected_history is not None and snapshot.protected_history != protected_history:
        errors.append(
            f"LEGO history changed: {snapshot.protected_history}, expected={protected_history}"
        )
    if snapshot.deleted_fk_residue:
        errors.append("foreign-key residue remains after deletion")
    return errors


def reconcile(session, catalog=LEGO_CATALOG, apply=False):
    try:
        if session.db_name not in ALLOWED_DATABASES:
            raise SafetyError(f"database {session.db_name!r} is not an allowed target")
        before = session.snapshot()
        plan = plan_reconciliation(before, catalog)
        if not apply:
            session.rollback()
            return Result("dry-run", plan.changed, plan, before, None)
        if plan.changed:
            session.apply(plan)
        after = session.snapshot()
        errors = postcondition_errors(after, catalog, before.protected_history)
        if errors:
            raise SafetyError("postcondition failed: " + "; ".join(errors))
        session.commit()
        return Result("apply", plan.changed, plan, before, after)
    except Exception:
        session.rollback()
        raise


class OdooSession:
    def __init__(self, odoo_env, catalog=LEGO_CATALOG):
        self.env = odoo_env
        self.db_name = odoo_env.cr.dbname
        self.catalog = catalog
        self._deleted_targets = None

    def _template_count(self):
        return self.env["product.template"].sudo().with_context(
            active_test=False
        ).search_count([])

    @staticmethod
    def _binary(value):
        if not value:
            return ""
        return value.decode("ascii") if isinstance(value, bytes) else value

    def _product_states(self):
        products = self.env["product.product"].sudo().with_context(
            active_test=False, lang="en_US"
        ).search([])
        states = []
        for product in products:
            states.append(ProductState(
                token=product.id,
                code=product.default_code or "",
                name=product.name or "",
                barcode=product.barcode or "",
                active=bool(product.active),
                product_type=product.type,
                sale_ok=bool(product.sale_ok),
                purchase_ok=bool(product.purchase_ok),
                tracking=product.tracking,
                list_price=float(product.list_price),
                standard_price=float(product.standard_price),
                is_storable=bool(product.is_storable),
                image_1920=self._binary(product.image_1920),
                ai_reference_description=product.ai_reference_description or "",
                ai_reference_image_sha1=product.ai_reference_image_sha1 or "",
                ai_reference_reviewed=bool(product.ai_reference_reviewed),
                description=product.description or "",
                description_sale=product.description_sale or "",
                description_purchase=product.description_purchase or "",
                description_picking=product.description_picking or "",
                description_pickingin=product.description_pickingin or "",
                description_pickingout=product.description_pickingout or "",
                weight=float(product.weight),
                volume=float(product.volume),
            ))
        return tuple(states), products

    def _fk_constraints(self, target_tables):
        self.env.cr.execute(
            """
            SELECT c.conname, target.relname, dependent.relname
              FROM pg_constraint c
              JOIN pg_class target ON target.oid = c.confrelid
              JOIN pg_class dependent ON dependent.oid = c.conrelid
             WHERE c.contype = 'f'
               AND target.relname = ANY(%s)
               AND array_length(c.conkey, 1) <> 1
            """,
            (list(target_tables),),
        )
        composite = self.env.cr.fetchall()
        if composite:
            raise SafetyError(f"composite foreign keys require review: {composite}")
        self.env.cr.execute(
            """
            SELECT target.relname,
                   dependent.relname,
                   a.attname,
                   c.confdeltype
              FROM pg_constraint c
              JOIN pg_class target ON target.oid = c.confrelid
              JOIN pg_class dependent ON dependent.oid = c.conrelid
              JOIN pg_attribute a
                ON a.attrelid = c.conrelid AND a.attnum = c.conkey[1]
             WHERE c.contype = 'f'
               AND target.relname = ANY(%s)
             ORDER BY 1, 2, 3
            """,
            (list(target_tables),),
        )
        return self.env.cr.fetchall()

    def _table_has_id(self, table):
        self.env.cr.execute(
            """SELECT EXISTS (
                   SELECT 1 FROM pg_attribute a
                   JOIN pg_class c ON c.oid = a.attrelid
                    WHERE c.relname = %s AND a.attname = 'id'
                      AND a.attnum > 0 AND NOT a.attisdropped
               )""",
            (table,),
        )
        return self.env.cr.fetchone()[0]

    def _history_fingerprint(self, protected):
        from psycopg2 import sql

        rows = []
        for table, ids in sorted(protected.items()):
            if not ids:
                continue
            self.env.cr.execute(sql.SQL(
                "SELECT to_jsonb(t)::text FROM {} t WHERE id = ANY(%s) ORDER BY id"
            ).format(sql.Identifier(table)), (ids,))
            rows.extend(("row", table, value[0]) for value in self.env.cr.fetchall())
        for target, dependent, column, _delete_rule in self._fk_constraints(protected):
            ids = protected[target]
            if not ids:
                continue
            order = sql.SQL("id") if self._table_has_id(dependent) else sql.SQL("to_jsonb(t)::text")
            self.env.cr.execute(sql.SQL(
                "SELECT to_jsonb(t)::text FROM {} t WHERE {} = ANY(%s) ORDER BY {}"
            ).format(sql.Identifier(dependent), sql.Identifier(column), order), (ids,))
            rows.extend(
                ("dependent", target, dependent, column, value[0])
                for value in self.env.cr.fetchall()
            )
        payload = json.dumps(rows, ensure_ascii=False, separators=(",", ":"))
        return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def _fk_inventory(self, targets, protected=None):
        from psycopg2 import sql

        if not any(targets.values()):
            return ()
        target_tables = [table for table, ids in targets.items() if ids]
        inventory = []
        protected = protected or {}
        for target, dependent, column, delete_rule in self._fk_constraints(target_tables):
            ids = targets[target]
            self.env.cr.execute(sql.SQL("SELECT count(*) FROM {} WHERE {} = ANY(%s)").format(
                sql.Identifier(dependent), sql.Identifier(column)
            ), (ids,))
            count = self.env.cr.fetchone()[0]
            dependent_ids = set()
            if count and self._table_has_id(dependent):
                self.env.cr.execute(sql.SQL("SELECT id FROM {} WHERE {} = ANY(%s)").format(
                    sql.Identifier(dependent), sql.Identifier(column)
                ), (ids,))
                dependent_ids = {row[0] for row in self.env.cr.fetchall()}
            inside = bool(
                count and dependent in targets and dependent_ids
                and dependent_ids.issubset(set(targets[dependent]))
            )
            touches = bool(
                count and dependent in protected
                and dependent_ids.intersection(set(protected[dependent]))
            )
            inventory.append(ForeignKeyState(
                target, dependent, column, delete_rule, count, inside, touches
            ))
        return tuple(inventory)

    def _deletion_targets(self, nonlego_ids):
        products = self.env["product.product"].sudo().with_context(active_test=False).browse(
            nonlego_ids
        ).exists()
        moves = self.env["stock.move"].sudo().search([("product_id", "in", nonlego_ids)])
        lines = self.env["stock.move.line"].sudo().search([
            "|", ("product_id", "in", nonlego_ids), ("move_id", "in", moves.ids)
        ])
        pickings = moves.mapped("picking_id")
        quants = self.env["stock.quant"].sudo().search([("product_id", "in", nonlego_ids)])
        return {
            "product_product": products.ids,
            "product_template": products.mapped("product_tmpl_id").ids,
            "stock_picking": pickings.ids,
            "stock_move": moves.ids,
            "stock_move_line": lines.ids,
            "stock_quant": quants.ids,
        }

    def _target_residue(self, targets):
        from psycopg2 import sql

        residue = []
        for table, ids in targets.items():
            if not ids:
                continue
            self.env.cr.execute(sql.SQL(
                "SELECT count(*) FROM {} WHERE id = ANY(%s)"
            ).format(sql.Identifier(table)), (ids,))
            count = self.env.cr.fetchone()[0]
            if count:
                residue.append(ForeignKeyState(table, table, "id", "target", count))
        return tuple(residue)

    def snapshot(self):
        self.env.invalidate_all()
        states, products = self._product_states()
        desired_codes = {item.code for item in self.catalog}
        nonlego_ids = [
            state.token for state in states
            if state.code not in desired_codes or state.name.startswith("Demo ")
        ]
        protected_ids = [state.token for state in states if state.token not in nonlego_ids]
        Move = self.env["stock.move"].sudo()
        MoveLine = self.env["stock.move.line"].sudo()
        Picking = self.env["stock.picking"].sudo()
        Quant = self.env["stock.quant"].sudo()
        nonlego_moves = Move.search([("product_id", "in", nonlego_ids)]) if nonlego_ids else Move.browse()
        nonlego_lines = MoveLine.search([("product_id", "in", nonlego_ids)]) if nonlego_ids else MoveLine.browse()
        nonlego_pickings = nonlego_moves.mapped("picking_id")
        protected_moves = Move.search([("product_id", "in", protected_ids)]) if protected_ids else Move.browse()
        protected_lines = MoveLine.search([("product_id", "in", protected_ids)]) if protected_ids else MoveLine.browse()
        protected_pickings = protected_moves.mapped("picking_id")
        mixed = nonlego_pickings.filtered(
            lambda picking: any(move.product_id.id in protected_ids for move in picking.move_ids)
        )
        restricted = []
        for model_name in ("stock.lot", "stock.scrap"):
            if model_name in self.env and nonlego_ids:
                count = self.env[model_name].sudo().search_count([("product_id", "in", nonlego_ids)])
                if count:
                    restricted.append((model_name, count))
        shared_templates = products.filtered(lambda p: p.id in nonlego_ids).mapped("product_tmpl_id").filtered(
            lambda template: any(variant.id in protected_ids for variant in template.product_variant_ids)
        )
        if shared_templates:
            restricted.append(("shared_product_template", len(shared_templates)))
        state_counts = Counter(nonlego_pickings.mapped("state"))
        targets = self._deletion_targets(nonlego_ids)
        protected = {
            "stock_picking": protected_pickings.ids,
            "stock_move": protected_moves.ids,
            "stock_move_line": protected_lines.ids,
        }
        fk_inventory = self._fk_inventory(targets, protected)
        deleted_residue = ()
        if self._deleted_targets is not None:
            deleted_residue = self._target_residue(self._deleted_targets) + tuple(
                fk for fk in self._fk_inventory(self._deleted_targets) if fk.count
            )
        return Snapshot(
            products=states,
            templates=self._template_count(),
            nonlego_pickings=len(targets["stock_picking"]),
            nonlego_picking_states=tuple(sorted(state_counts.items())),
            mixed_pickings=len(mixed),
            nonlego_moves=len(targets["stock_move"]),
            nonlego_move_lines=len(targets["stock_move_line"]),
            nonlego_quants=len(targets["stock_quant"]),
            restricted_dependencies=tuple(restricted),
            protected_history=self._history_fingerprint(protected),
            fk_inventory=fk_inventory,
            deleted_fk_residue=deleted_residue,
        )

    def apply(self, plan):
        Product = self.env["product.product"].sudo().with_context(active_test=False, lang="en_US")
        delete_products = Product.browse(list(plan.delete_tokens)).exists()
        delete_ids = delete_products.ids
        if delete_ids:
            targets = self._deletion_targets(delete_ids)
            pickings = self.env["stock.picking"].sudo().browse(targets["stock_picking"])
            to_cancel = pickings.filtered(lambda picking: picking.state != "cancel")
            if to_cancel:
                to_cancel.action_cancel()
            targets = self._deletion_targets(delete_ids)
            unsafe = unsafe_fk_dependencies(self._fk_inventory(targets))
            if unsafe:
                raise SafetyError(f"foreign-key graph changed during cancellation: {unsafe}")
            self._deleted_targets = {table: list(ids) for table, ids in targets.items()}
            for table in ("stock_move_line", "stock_move", "stock_quant"):
                if targets[table]:
                    self.env.cr.execute(
                        f"DELETE FROM {table} WHERE id = ANY(%s)", (targets[table],)
                    )
            self.env.invalidate_all()
            self.env["stock.picking"].sudo().browse(targets["stock_picking"]).exists().unlink()
            self.env["product.template"].sudo().with_context(active_test=False).browse(
                targets["product_template"]
            ).exists().unlink()

        wanted = {item.code: item for item in self.catalog}
        for token in plan.update_tokens:
            product = Product.browse(token).exists()
            if not product:
                raise SafetyError(f"product selected for update disappeared: {token}")
            product.write(wanted[product.default_code].values())
        for item in plan.create_items:
            Product.create(item.values())

    def commit(self):
        self.env.cr.commit()

    def rollback(self):
        self.env.cr.rollback()


def _print_snapshot(label, snapshot):
    active = sum(product.active for product in snapshot.products)
    print(
        f"{label} products={len(snapshot.products)} active={active} templates={snapshot.templates} "
        f"nonlego_pickings={snapshot.nonlego_pickings} states={dict(snapshot.nonlego_picking_states)} "
        f"nonlego_moves={snapshot.nonlego_moves} move_lines={snapshot.nonlego_move_lines} "
        f"quants={snapshot.nonlego_quants} protected_history={snapshot.protected_history} "
        f"fk_constraints={len(snapshot.fk_inventory)}"
    )
    nonzero_fks = [
        f"{fk.target_table}<-{fk.dependent_table}.{fk.dependent_column}:"
        f"{fk.count}/{fk.delete_rule}"
        for fk in snapshot.fk_inventory if fk.count
    ]
    print(f"{label} fk_nonzero={nonzero_fks}")


def export_catalog(odoo_env, path):
    if odoo_env.cr.dbname != "masterfischer_o19":
        raise SafetyError("catalog fixture may only be exported from masterfischer_o19")
    session = OdooSession(odoo_env)
    states, _products = session._product_states()
    by_code = {state.code: state for state in states if state.active}
    if set(by_code) & {item.code for item in LEGO_CATALOG} != {
        item.code for item in LEGO_CATALOG
    }:
        raise SafetyError("Lager 1 does not contain the exact active LEGO allowlist")
    rows = []
    for allowed in LEGO_CATALOG:
        state = by_code[allowed.code]
        item = CatalogItem(
            code=state.code,
            name=state.name,
            barcode=state.barcode,
            product_type=state.product_type,
            sale_ok=state.sale_ok,
            purchase_ok=state.purchase_ok,
            tracking=state.tracking,
            list_price=state.list_price,
            standard_price=state.standard_price,
            is_storable=state.is_storable,
            image_1920=state.image_1920,
            ai_reference_description=state.ai_reference_description,
            ai_reference_image_sha1=state.ai_reference_image_sha1,
            ai_reference_reviewed=state.ai_reference_reviewed,
            description=state.description,
            description_sale=state.description_sale,
            description_purchase=state.description_purchase,
            description_picking=state.description_picking,
            description_pickingin=state.description_pickingin,
            description_pickingout=state.description_pickingout,
            weight=state.weight,
            volume=state.volume,
        )
        if not item.is_storable or not item.image_1920:
            raise SafetyError(f"incomplete Lager 1 catalog record for SKU {item.code}")
        if item.ai_reference_description:
            checksum = hashlib.sha1(base64.b64decode(item.image_1920)).hexdigest()
            if checksum != item.ai_reference_image_sha1:
                raise SafetyError(f"stale reference description for SKU {item.code}")
        rows.append(item._asdict())
    Path(path).write_text(
        json.dumps(rows, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    odoo_env.cr.rollback()
    print(f"exported_fixture={path} products={len(rows)}")


def shell_main(odoo_env):
    parser = argparse.ArgumentParser(description="Reconcile Odoo to the 47-SKU LEGO catalog")
    parser.add_argument("--apply", action="store_true", help="commit after exact verification")
    parser.add_argument("--fixture", default=os.environ.get("RECONCILE_FIXTURE", ""))
    parser.add_argument("--export-fixture", metavar="PATH")
    args = parser.parse_args(shlex.split(os.environ.get("RECONCILE_ARGS", "")))
    if args.export_fixture:
        if args.apply:
            raise SafetyError("--export-fixture and --apply are mutually exclusive")
        export_catalog(odoo_env, args.export_fixture)
        return
    if not args.fixture:
        raise SafetyError("catalog fixture required via --fixture or RECONCILE_FIXTURE")
    catalog = load_catalog(args.fixture)
    session = OdooSession(odoo_env, catalog)
    result = reconcile(session, catalog=catalog, apply=args.apply)
    print(f"database={session.db_name} mode={result.mode}")
    _print_snapshot("preflight", result.before)
    print(
        f"plan delete_products={len(result.plan.delete_tokens)} "
        f"update_products={len(result.plan.update_tokens)} "
        f"create_products={len(result.plan.create_items)} changed={result.changed}"
    )
    if result.after:
        _print_snapshot("postcondition", result.after)
        print("COMMIT: exact 47-SKU parity verified")
    else:
        print("ROLLBACK: dry-run (set RECONCILE_ARGS=--apply to commit)")


if "env" in globals():
    shell_main(env)
