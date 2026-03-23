"""
Business logic for picking operations.

Odoo 18 notes:
- `stock.move.line.quantity` is the relevant quantity field
- `stock.move.picked` indicates whether a move was confirmed in the UI flow
"""
import re

from app.services.n8n_webhook import N8NWebhookClient
from app.services.odoo_client import OdooAPIError, OdooClient
from app.services.route_optimizer import build_route_plan


def _clean_product_name(display_name: str) -> str:
    """Strip Odoo's '[barcode/ref] ' prefix from product display names."""
    return re.sub(r"^\[.*?\]\s*", "", display_name)


class PickingService:
    def __init__(self, odoo: OdooClient, n8n: N8NWebhookClient):
        self._odoo = odoo
        self._n8n = n8n

    async def get_open_pickings(self) -> list[dict]:
        """Load open pickings (list view — no moves needed)."""
        return await self._odoo.search_read(
            "stock.picking",
            [("state", "=", "assigned")],
            [
                "name",
                "partner_id",
                "scheduled_date",
                "state",
                "picking_type_id",
                "priority",
            ],
        )

    async def get_picking_detail(self, picking_id: int) -> dict:
        """Load a single picking with move-line details and product barcodes."""
        pickings = await self._odoo.search_read(
            "stock.picking",
            [("id", "=", picking_id)],
            [
                "name",
                "partner_id",
                "scheduled_date",
                "state",
                "move_ids",
                "location_id",
                "location_dest_id",
            ],
        )
        if not pickings:
            return {"error": "Picking nicht gefunden"}

        picking = pickings[0]
        move_line_ids = await self._odoo.execute_kw(
            "stock.move.line",
            "search",
            [[("picking_id", "=", picking_id)]],
        )

        if not move_line_ids:
            picking["move_lines"] = []
            return picking

        raw_lines = await self._odoo.execute_kw(
            "stock.move.line",
            "read",
            [move_line_ids],
            {
                "fields": [
                    "id",
                    "product_id",
                    "quantity",
                    "move_id",
                    "location_id",
                    "location_dest_id",
                    "lot_id",
                ]
            },
        )

        product_ids = list(
            {
                line["product_id"][0]
                for line in raw_lines
                if line.get("product_id")
            }
        )
        move_ids = list(
            {
                line["move_id"][0]
                for line in raw_lines
                if line.get("move_id")
            }
        )

        barcode_map: dict[int, str | None] = {}
        if product_ids:
            products = await self._odoo.search_read(
                "product.product",
                [("id", "in", product_ids)],
                ["id", "barcode"],
            )
            barcode_map = {product["id"]: product.get("barcode") for product in products}

        move_map: dict[int, dict] = {}
        if move_ids:
            moves = await self._odoo.search_read(
                "stock.move",
                [("id", "in", move_ids)],
                ["id", "product_uom_qty", "picked"],
            )
            move_map = {move["id"]: move for move in moves}

        move_lines = []
        for raw_line in raw_lines:
            product_id = raw_line["product_id"][0] if raw_line.get("product_id") else None
            move_id = raw_line["move_id"][0] if raw_line.get("move_id") else None
            move = move_map.get(move_id, {})
            move_lines.append(
                {
                    "id": raw_line["id"],
                    "product_id": product_id,
                    "product_name": _clean_product_name(raw_line["product_id"][1]) if raw_line.get("product_id") else "",
                    "product_barcode": barcode_map.get(product_id) if product_id else None,
                    "quantity_demand": move.get("product_uom_qty", raw_line.get("quantity", 0)),
                    "quantity_done": raw_line.get("quantity", 0) if move.get("picked") else 0,
                    "picked": bool(move.get("picked")),
                    "location_src": raw_line["location_id"][1] if raw_line.get("location_id") else "",
                    "location_dest": raw_line["location_dest_id"][1] if raw_line.get("location_dest_id") else "",
                    "lot": raw_line["lot_id"][1] if raw_line.get("lot_id") else None,
                }
            )

        route_plan = build_route_plan(move_lines)
        picking["move_lines"] = route_plan.pop("ordered_move_lines")
        picking["route_plan"] = route_plan
        return picking

    async def get_picking_route_plan(self, picking_id: int) -> dict:
        """Expose the computed route plan for UI hints and later simulations."""
        picking = await self.get_picking_detail(picking_id)
        if picking.get("error"):
            return picking
        return picking.get("route_plan", build_route_plan([]))

    async def confirm_pick_line(
        self,
        picking_id: int,
        move_line_id: int,
        scanned_barcode: str,
        quantity: float,
    ) -> dict:
        """
        Confirm a move line via barcode scan.

        The Odoo 18 flow uses `stock.move.picked` to track whether a move is done.
        """
        lines = await self._odoo.execute_kw(
            "stock.move.line",
            "read",
            [[move_line_id]],
            {"fields": ["id", "product_id", "quantity", "move_id"]},
        )
        if not lines:
            return {
                "success": False,
                "message": "Move-Line nicht gefunden",
                "picking_complete": False,
            }

        line = lines[0]
        product_id = line["product_id"][0] if line.get("product_id") else None
        move_id = line["move_id"][0] if line.get("move_id") else None

        if product_id and scanned_barcode:
            products = await self._odoo.search_read(
                "product.product",
                [("id", "=", product_id)],
                ["barcode"],
            )
            expected_barcode = products[0].get("barcode") if products else None
            if expected_barcode and scanned_barcode != expected_barcode:
                return {
                    "success": False,
                    "message": f"Falscher Artikel. Erwartet: {expected_barcode}",
                    "picking_complete": False,
                }

        qty = quantity if quantity > 0 else line.get("quantity", 1.0)
        await self._odoo.write("stock.move.line", [move_line_id], {"quantity": qty})

        if move_id:
            await self._odoo.write("stock.move", [move_id], {"picked": True})

        move_ids = await self._odoo.execute_kw(
            "stock.move",
            "search",
            [[("picking_id", "=", picking_id)]],
        )
        moves = await self._odoo.execute_kw(
            "stock.move",
            "read",
            [move_ids],
            {"fields": ["picked"]},
        )
        all_done = bool(moves) and all(move.get("picked") for move in moves)

        picking_complete = False
        if all_done:
            try:
                await self._odoo.call_method(
                    "stock.picking",
                    "button_validate",
                    [picking_id],
                    context={"skip_immediate": True, "skip_backorder": True},
                )
                picking_complete = True
            except OdooAPIError:
                picking_complete = False

            if picking_complete:
                await self._n8n.fire(
                    "pick-confirmed",
                    {
                        "picking_id": picking_id,
                        "completed_by": "mobile-picking-assistant",
                    },
                )

        return {
            "success": True,
            "message": "Auftrag abgeschlossen." if picking_complete else "Bestaetigt.",
            "picking_complete": picking_complete,
        }
