"""
Business logic for picking operations.

Odoo 18 notes:
- `stock.move.line.quantity` is the relevant quantity field
- `stock.move.picked` indicates whether a move was confirmed in the UI flow
"""
from __future__ import annotations

import re
from collections import defaultdict
from typing import Any

from app.services.mobile_workflow import PickerIdentity
from app.services.n8n_webhook import N8NWebhookClient
from app.services.odoo_client import OdooAPIError, OdooClient
from app.services.route_optimizer import build_route_plan


def _clean_product_name(display_name: str) -> str:
    """Strip Odoo's '[barcode/ref] ' prefix from product display names."""
    return re.sub(r"^\[.*?\]\s*", "", display_name or "")


def _location_parts(location: str) -> list[str]:
    return [part.strip() for part in (location or "").split("/") if part and part.strip()]


def _location_short(location: str) -> str:
    parts = _location_parts(location)
    return parts[-1] if parts else (location or "")


def _location_zone(location: str) -> str:
    parts = _location_parts(location)
    if len(parts) >= 2:
        return parts[-2]
    return _location_short(location)


def _format_quantity(value: float | int | None) -> str:
    if value is None:
        return "0"
    numeric = float(value)
    if numeric.is_integer():
        return str(int(numeric))
    return f"{numeric:.2f}".rstrip("0").rstrip(".")


def _clean_picking_type_name(value: str) -> str:
    if not value:
        return ""
    return value.split(":")[-1].strip()


def _build_voice_instruction_short(location_short: str, quantity: float | int | None, product_name: str) -> str:
    segments = []
    if location_short:
        segments.append(f"{location_short}.")
    segments.append(f"{_format_quantity(quantity)} Stueck.")
    if product_name:
        segments.append(f"{product_name}.")
    return " ".join(segment for segment in segments if segment)


def _build_primary_item_display(quantity: float | int | None, product_name: str) -> str:
    if not product_name:
        return ""
    return f"{_format_quantity(quantity)}x {product_name}"


def _enrich_line_payload(line: dict[str, Any]) -> dict[str, Any]:
    product_short_name = line.get("product_name", "")
    location_src = line.get("location_src", "")
    location_src_short = _location_short(location_src)
    location_src_zone = _location_zone(location_src)
    quantity_demand = line.get("quantity_demand", 0)

    line["product_short_name"] = product_short_name
    line["location_src_short"] = location_src_short
    line["location_src_zone"] = location_src_zone
    line["ui_display"] = product_short_name or "Produkt"
    line["voice_instruction_short"] = _build_voice_instruction_short(
        location_src_short,
        quantity_demand,
        product_short_name,
    )
    return line


def _apply_operational_preview(picking: dict[str, Any], ordered_lines: list[dict[str, Any]]) -> dict[str, Any]:
    reference_code = picking.get("name", "")
    picking_type_name = ""
    if picking.get("picking_type_id"):
        picking_type_name = _clean_picking_type_name(picking["picking_type_id"][1])

    fallback_label = picking_type_name or reference_code or "Picking"
    primary_line = ordered_lines[0] if ordered_lines else None

    picking["reference_code"] = reference_code
    picking["open_line_count"] = len(ordered_lines)
    picking["primary_item_display"] = (
        _build_primary_item_display(
            primary_line.get("quantity_demand"),
            primary_line.get("product_short_name", primary_line.get("product_name", "")),
        )
        if primary_line
        else fallback_label
    )
    picking["next_location_short"] = primary_line.get("location_src_short", "") if primary_line else ""
    picking["voice_instruction_short"] = (
        primary_line.get("voice_instruction_short", "")
        if primary_line
        else f"{fallback_label}."
    )
    return picking


class PickingService:
    def __init__(self, odoo: OdooClient, n8n: N8NWebhookClient):
        self._odoo = odoo
        self._n8n = n8n

    async def get_open_pickings(self) -> list[dict]:
        """Load open pickings enriched with operational preview data."""
        pickings = await self._odoo.search_read(
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
        if not pickings:
            return []

        picking_ids = [picking["id"] for picking in pickings]
        raw_lines = await self._odoo.execute_kw(
            "stock.move.line",
            "search_read",
            [[("picking_id", "in", picking_ids)]],
            {
                "fields": [
                    "id",
                    "picking_id",
                    "product_id",
                    "quantity",
                    "move_id",
                    "location_id",
                ],
                "limit": max(500, len(picking_ids) * 20),
            },
        )

        move_ids = list(
            {
                line["move_id"][0]
                for line in raw_lines
                if line.get("move_id")
            }
        )
        move_map: dict[int, dict[str, Any]] = {}
        if move_ids:
            moves = await self._odoo.search_read(
                "stock.move",
                [("id", "in", move_ids)],
                ["id", "product_uom_qty", "picked"],
            )
            move_map = {move["id"]: move for move in moves}

        lines_by_picking: dict[int, list[dict[str, Any]]] = defaultdict(list)
        for raw_line in raw_lines:
            picking_value = raw_line.get("picking_id")
            if not picking_value:
                continue
            picking_id = picking_value[0]
            move_id = raw_line["move_id"][0] if raw_line.get("move_id") else None
            move = move_map.get(move_id, {})
            enriched_line = _enrich_line_payload(
                {
                    "id": raw_line["id"],
                    "product_id": raw_line["product_id"][0] if raw_line.get("product_id") else None,
                    "product_name": _clean_product_name(raw_line["product_id"][1]) if raw_line.get("product_id") else "",
                    "quantity_demand": move.get("product_uom_qty", raw_line.get("quantity", 0)),
                    "quantity_done": raw_line.get("quantity", 0) if move.get("picked") else 0,
                    "picked": bool(move.get("picked")),
                    "location_src": raw_line["location_id"][1] if raw_line.get("location_id") else "",
                }
            )
            lines_by_picking[picking_id].append(enriched_line)

        enriched_pickings = []
        for picking in pickings:
            route_plan = build_route_plan(lines_by_picking.get(picking["id"], []))
            ordered_lines = route_plan.get("ordered_move_lines", [])
            enriched_pickings.append(_apply_operational_preview(picking, ordered_lines))

        return enriched_pickings

    async def get_picking_detail(self, picking_id: int) -> dict:
        """Load a single picking with move-line details and operational labels."""
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
                "picking_type_id",
                "priority",
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
            picking["route_plan"] = build_route_plan([])
            _apply_operational_preview(picking, [])
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

        move_map: dict[int, dict[str, Any]] = {}
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
                _enrich_line_payload(
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
            )

        route_plan = build_route_plan(move_lines)
        ordered_lines = route_plan.pop("ordered_move_lines")
        picking["move_lines"] = ordered_lines
        picking["route_plan"] = route_plan
        _apply_operational_preview(picking, ordered_lines)
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
        picker_identity: PickerIdentity | None = None,
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
                completed_by = "mobile-picking-assistant"
                completed_by_user_id = False
                completed_by_device_id = ""
                if picker_identity and picker_identity.user_id:
                    completed_by = picker_identity.picker_name or completed_by
                    completed_by_user_id = picker_identity.user_id
                    completed_by_device_id = picker_identity.device_id or ""

                await self._n8n.fire(
                    "pick-confirmed",
                    {
                        "picking_id": picking_id,
                        "completed_by": completed_by,
                        "completed_by_user_id": completed_by_user_id,
                        "completed_by_device_id": completed_by_device_id,
                    },
                )

        return {
            "success": True,
            "message": "Auftrag abgeschlossen." if picking_complete else "Bestaetigt.",
            "picking_complete": picking_complete,
        }
