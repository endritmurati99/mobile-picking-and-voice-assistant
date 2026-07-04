"""Demo traceability presets for BOM/product tracking.

This is intentionally scoped to demo databases. Product tracking changes are
real Odoo master-data changes and should not be exposed for production use.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import floor, isclose
from typing import Any

from app.services.odoo_client import OdooAPIError, OdooClient


DEMO_MODES: dict[str, dict[str, str]] = {
    "none": {
        "label": "Aus",
        "description": "BOM-Endprodukte und Komponenten ohne Lot-/Serienpflicht.",
    },
    "finished_lot": {
        "label": "Endprodukt Lot",
        "description": "Nur fertige BOM-Produkte sind chargenpflichtig.",
    },
    "finished_serial": {
        "label": "Endprodukt Serial",
        "description": "Nur fertige BOM-Produkte sind seriennummernpflichtig.",
    },
    "component_lot": {
        "label": "Komponenten Lot",
        "description": "Nur BOM-Komponenten sind chargenpflichtig.",
    },
    "component_serial": {
        "label": "Komponenten Serial",
        "description": "Nur BOM-Komponenten sind seriennummernpflichtig.",
    },
    "finished_lot_component_lot": {
        "label": "End Lot + Komp. Lot",
        "description": "Fertige BOM-Produkte und Komponenten sind chargenpflichtig.",
    },
    "finished_lot_component_serial": {
        "label": "End Lot + Komp. Serial",
        "description": "Fertige BOM-Produkte sind chargenpflichtig, Komponenten seriennummernpflichtig.",
    },
    "full_lot_traceability": {
        "label": "Voll: End Serial + Komp. Lot",
        "description": "Fertiges Produkt mit Seriennummer, Komponenten mit Chargen.",
    },
    "full_serial_traceability": {
        "label": "Voll: alles Serial",
        "description": "Fertige Produkte und Komponenten sind seriennummernpflichtig.",
    },
}

MODE_TRACKING: dict[str, tuple[str, str]] = {
    "none": ("none", "none"),
    "finished_lot": ("lot", "none"),
    "finished_serial": ("serial", "none"),
    "component_lot": ("none", "lot"),
    "component_serial": ("none", "serial"),
    "finished_lot_component_lot": ("lot", "lot"),
    "finished_lot_component_serial": ("lot", "serial"),
    "full_lot_traceability": ("serial", "lot"),
    "full_serial_traceability": ("serial", "serial"),
}

SERIAL_CREATE_CAP = 40


@dataclass(frozen=True)
class DemoProducts:
    finished_product_ids: list[int]
    component_product_ids: list[int]
    product_template_by_product: dict[int, int]
    component_line_product_ids: set[int]


def _m2o_id(value: Any) -> int | None:
    if isinstance(value, (list, tuple)) and value:
        try:
            return int(value[0])
        except (TypeError, ValueError):
            return None
    return None


def _qty(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _code(value: str | None, fallback: int) -> str:
    normalized = "".join(ch if ch.isalnum() else "-" for ch in str(value or "").strip())
    return normalized.strip("-") or str(fallback)


class DemoTraceabilityService:
    def __init__(self, odoo: OdooClient):
        self._odoo = odoo

    async def get_status(self) -> dict[str, Any]:
        products = await self._get_demo_products()
        finished_product_ids = self._effective_finished_product_ids(products)
        product_ids = sorted(set(finished_product_ids + products.component_product_ids))
        rows = await self._read_products(product_ids)
        finished_tracking = {row["tracking"] for row in rows if row["id"] in finished_product_ids}
        component_tracking = {row["tracking"] for row in rows if row["id"] in products.component_product_ids}

        return {
            "enabled": True,
            "mode": self._detect_mode(finished_tracking, component_tracking),
            "modes": [{"name": name, **meta} for name, meta in DEMO_MODES.items()],
            "counts": {
                "finished_products": len(finished_product_ids),
                "component_products": len(products.component_product_ids),
                "overlap_products": len(set(products.finished_product_ids) & set(products.component_product_ids)),
            },
            "finished_tracking": sorted(finished_tracking),
            "component_tracking": sorted(component_tracking),
        }

    async def apply_mode(self, mode: str) -> dict[str, Any]:
        if mode not in DEMO_MODES:
            raise ValueError(f"Unbekannter Demo-Modus: {mode}")

        products = await self._get_demo_products()
        finished_tracking, component_tracking = self._tracking_for_mode(mode)
        finished_product_ids = self._effective_finished_product_ids(products)
        touched_templates: set[int] = set()

        touched_templates.update(
            await self._set_product_tracking(finished_product_ids, finished_tracking, products)
        )
        touched_templates.update(
            await self._set_product_tracking(products.component_product_ids, component_tracking, products)
        )

        created_lots = 0
        created_quants = 0
        split_lines = 0

        if finished_tracking in {"lot", "serial"}:
            lot_count, quant_count = await self._ensure_lots_and_quants(finished_product_ids, finished_tracking)
            created_lots += lot_count
            created_quants += quant_count
            if finished_tracking == "serial":
                split_lines += await self._split_open_serial_move_lines(finished_product_ids)

        if component_tracking == "lot":
            lot_count, quant_count = await self._ensure_lots_and_quants(products.component_product_ids, "lot")
            created_lots += lot_count
            created_quants += quant_count
        elif component_tracking == "serial":
            lot_count, quant_count = await self._ensure_lots_and_quants(products.component_product_ids, "serial")
            created_lots += lot_count
            created_quants += quant_count
            split_lines += await self._split_open_serial_move_lines(products.component_product_ids)

        status = await self.get_status()
        status.update(
            {
                "applied_mode": mode,
                "message": DEMO_MODES[mode]["label"],
                "touched_templates": len(touched_templates),
                "created_or_updated_lots": created_lots,
                "created_or_updated_quants": created_quants,
                "split_move_lines": split_lines,
            }
        )
        return status

    def _tracking_for_mode(self, mode: str) -> tuple[str, str]:
        try:
            return MODE_TRACKING[mode]
        except KeyError as exc:
            raise ValueError(f"Unbekannter Demo-Modus: {mode}") from exc

    def _detect_mode(self, finished_tracking: set[str], component_tracking: set[str]) -> str:
        if not finished_tracking:
            finished_tracking = {"none"}
        if not component_tracking:
            component_tracking = {"none"}
        for mode, tracking in MODE_TRACKING.items():
            if finished_tracking == {tracking[0]} and component_tracking == {tracking[1]}:
                return mode
        return "mixed"

    def _effective_finished_product_ids(self, products: DemoProducts) -> list[int]:
        component_ids = set(products.component_product_ids)
        return [product_id for product_id in products.finished_product_ids if product_id not in component_ids]

    async def _get_demo_products(self) -> DemoProducts:
        boms = await self._odoo.execute_kw(
            "mrp.bom",
            "search_read",
            [[]],
            {"fields": ["id", "product_id", "product_tmpl_id"], "limit": 200},
        )
        if not boms:
            return DemoProducts([], [], {}, set())

        bom_ids = [int(bom["id"]) for bom in boms]
        bom_product_ids = [_m2o_id(bom.get("product_id")) for bom in boms]
        template_ids = [_m2o_id(bom.get("product_tmpl_id")) for bom in boms]
        template_ids = [value for value in template_ids if value]

        finished_product_ids = [value for value in bom_product_ids if value]
        if template_ids:
            variants = await self._odoo.execute_kw(
                "product.product",
                "search_read",
                [[("product_tmpl_id", "in", template_ids)]],
                {"fields": ["id", "product_tmpl_id"], "limit": 500},
            )
            finished_product_ids.extend(int(row["id"]) for row in variants)

        lines = await self._odoo.execute_kw(
            "mrp.bom.line",
            "search_read",
            [[("bom_id", "in", bom_ids)]],
            {"fields": ["product_id"], "limit": 1000},
        )
        component_product_ids = sorted(
            {
                product_id
                for product_id in (_m2o_id(line.get("product_id")) for line in lines)
                if product_id
            }
        )
        finished_product_ids = sorted(set(finished_product_ids))
        all_ids = sorted(set(finished_product_ids + component_product_ids))
        product_template_by_product = {}
        if all_ids:
            products = await self._read_products(all_ids)
            product_template_by_product = {
                int(row["id"]): _m2o_id(row.get("product_tmpl_id")) or int(row["id"])
                for row in products
            }
        return DemoProducts(
            finished_product_ids=finished_product_ids,
            component_product_ids=component_product_ids,
            product_template_by_product=product_template_by_product,
            component_line_product_ids=set(component_product_ids),
        )

    async def _read_products(self, product_ids: list[int]) -> list[dict[str, Any]]:
        if not product_ids:
            return []
        return await self._odoo.execute_kw(
            "product.product",
            "search_read",
            [[("id", "in", sorted(set(product_ids)))]],
            {"fields": ["id", "product_tmpl_id", "default_code", "tracking"], "limit": len(set(product_ids)) + 10},
        )

    async def _set_product_tracking(
        self,
        product_ids: list[int],
        tracking: str,
        products: DemoProducts,
    ) -> set[int]:
        template_ids = {
            products.product_template_by_product[product_id]
            for product_id in product_ids
            if product_id in products.product_template_by_product
        }
        if template_ids:
            await self._odoo.write("product.template", sorted(template_ids), {"tracking": tracking})
        return template_ids

    async def _ensure_lots_and_quants(self, product_ids: list[int], tracking: str) -> tuple[int, int]:
        product_rows = await self._read_products(product_ids)
        lot_count = 0
        quant_count = 0
        for product in product_rows:
            product_id = int(product["id"])
            code = _code(product.get("default_code"), product_id)
            quants = await self._odoo.execute_kw(
                "stock.quant",
                "search_read",
                [[("product_id", "=", product_id), ("location_id.usage", "=", "internal")]],
                {"fields": ["id", "quantity", "location_id"], "limit": 200},
            )
            for quant in quants:
                quantity = _qty(quant.get("quantity"))
                if quantity <= 0:
                    continue
                location_id = _m2o_id(quant.get("location_id"))
                if not location_id:
                    continue
                if tracking == "lot":
                    lot_name = f"DEMO-LOT-{code}-L{location_id}"
                    lot_id = await self._ensure_lot(product_id, lot_name)
                    await self._ensure_quant(product_id, location_id, lot_id, max(quantity, 1.0))
                    lot_count += 1
                    quant_count += 1
                elif tracking == "serial":
                    serial_total = max(1, min(SERIAL_CREATE_CAP, floor(quantity)))
                    for index in range(1, serial_total + 1):
                        lot_name = f"DEMO-SN-{code}-L{location_id}-{index:03d}"
                        lot_id = await self._ensure_lot(product_id, lot_name)
                        await self._ensure_quant(product_id, location_id, lot_id, 1.0)
                        lot_count += 1
                        quant_count += 1
        return lot_count, quant_count

    async def _ensure_lot(self, product_id: int, name: str) -> int:
        existing = await self._odoo.search_read(
            "stock.lot",
            [("product_id", "=", product_id), ("name", "=", name)],
            ["id"],
            limit=1,
        )
        if existing:
            return int(existing[0]["id"])
        return int(await self._odoo.create("stock.lot", {"product_id": product_id, "name": name}))

    async def _ensure_quant(self, product_id: int, location_id: int, lot_id: int, quantity: float) -> None:
        existing = await self._odoo.execute_kw(
            "stock.quant",
            "search_read",
            [[("product_id", "=", product_id), ("location_id", "=", location_id), ("lot_id", "=", lot_id)]],
            {"fields": ["id", "quantity"], "limit": 1},
        )
        if existing:
            quant_id = int(existing[0]["id"])
            if not isclose(_qty(existing[0].get("quantity")), quantity):
                await self._odoo.write("stock.quant", [quant_id], {"inventory_quantity": quantity})
                await self._apply_inventory([quant_id])
            return
        quant_id = await self._odoo.create(
            "stock.quant",
            {
                "product_id": product_id,
                "location_id": location_id,
                "lot_id": lot_id,
                "inventory_quantity": quantity,
            },
        )
        await self._apply_inventory([int(quant_id)])

    async def _apply_inventory(self, quant_ids: list[int]) -> None:
        try:
            await self._odoo.call_method("stock.quant", "action_apply_inventory", quant_ids)
        except OdooAPIError:
            # Some Odoo versions apply the inventory quantity immediately on create
            # in test/demo contexts. Keep mode switching best-effort here.
            return

    async def _split_open_serial_move_lines(self, product_ids: list[int]) -> int:
        if not product_ids:
            return 0
        lines = await self._odoo.execute_kw(
            "stock.move.line",
            "search_read",
            [[
                ("product_id", "in", sorted(set(product_ids))),
                ("picking_id.state", "in", ["assigned", "confirmed"]),
                ("picked", "=", False),
            ]],
            {
                "fields": [
                    "id",
                    "picking_id",
                    "move_id",
                    "product_id",
                    "product_uom_id",
                    "location_id",
                    "location_dest_id",
                    "quantity",
                    "lot_id",
                    "result_package_id",
                ],
                "limit": 1000,
            },
        )
        created = 0
        for line in lines:
            if line.get("lot_id"):
                continue
            quantity = _qty(line.get("quantity"))
            whole = floor(quantity)
            if quantity <= 1 or not isclose(quantity, whole):
                continue
            line_id = int(line["id"])
            await self._odoo.write("stock.move.line", [line_id], {"quantity": 1.0})
            base_vals = {
                "picking_id": _m2o_id(line.get("picking_id")),
                "move_id": _m2o_id(line.get("move_id")),
                "product_id": _m2o_id(line.get("product_id")),
                "product_uom_id": _m2o_id(line.get("product_uom_id")),
                "location_id": _m2o_id(line.get("location_id")),
                "location_dest_id": _m2o_id(line.get("location_dest_id")),
                "quantity": 1.0,
                "result_package_id": _m2o_id(line.get("result_package_id")),
            }
            vals = {key: value for key, value in base_vals.items() if value}
            for _ in range(whole - 1):
                await self._odoo.create("stock.move.line", vals)
                created += 1
        return created
