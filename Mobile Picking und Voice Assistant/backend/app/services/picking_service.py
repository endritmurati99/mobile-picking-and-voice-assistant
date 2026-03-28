"""
Business logic for picking operations.

Odoo 18 notes:
- `stock.move.line.quantity` is the relevant quantity field
- `stock.move.picked` indicates whether a move was confirmed in the UI flow
"""
from __future__ import annotations

import logging
import re
from collections import defaultdict
from datetime import datetime, timezone
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


def _location_zone_key(location: str) -> str:
    zone = _location_zone(location)
    return re.sub(r"[^a-z0-9]+", "-", zone.lower()).strip("-")


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


def _clean_context_text(value: Any) -> str:
    if not value:
        return ""
    return str(value).strip()


def _extract_kit_name_from_source_document(value: Any) -> str:
    source_document = _clean_context_text(value)
    if not source_document:
        return ""

    extracted = re.sub(r"^\[[^\]]+\]\s*", "", source_document)
    extracted = re.sub(
        r"\s*\((?:bom|mo|mrp|so|po|wh)[^)]*\)\s*$",
        "",
        extracted,
        flags=re.IGNORECASE,
    )
    return extracted.strip()


def _enrich_line_payload(line: dict[str, Any]) -> dict[str, Any]:
    product_short_name = line.get("product_name", "")
    location_src = line.get("location_src", "")
    location_src_short = _location_short(location_src)
    location_src_zone = _location_zone(location_src)
    quantity_demand = line.get("quantity_demand", 0)

    line["product_short_name"] = product_short_name
    line["product_sku"] = line.get("product_sku") or ""
    line["location_src_short"] = location_src_short
    line["location_src_zone"] = location_src_zone
    line["ui_display"] = product_short_name or "Produkt"
    line["voice_instruction_short"] = _build_voice_instruction_short(
        location_src_short,
        quantity_demand,
        product_short_name,
    )
    return line


def _build_progress_ratio(completed_count: int, total_count: int) -> float:
    if total_count <= 0:
        return 0.0
    return round(completed_count / total_count, 4)


def _apply_human_context(
    picking: dict[str, Any],
    *,
    include_voice_intro: bool,
    opening_instruction: str = "",
) -> dict[str, Any]:
    kit_name = _extract_kit_name_from_source_document(picking.get("origin", ""))

    picking["kit_name"] = kit_name
    picking["has_human_context"] = bool(kit_name)
    if include_voice_intro:
        if kit_name and opening_instruction:
            picking["voice_intro"] = f"{kit_name}. {opening_instruction}"
        elif kit_name:
            picking["voice_intro"] = f"{kit_name}."
        else:
            picking["voice_intro"] = ""
    return picking


def _apply_operational_preview(
    picking: dict[str, Any],
    ordered_lines: list[dict[str, Any]],
    all_lines: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    reference_code = picking.get("name", "")
    picking_type_name = ""
    if picking.get("picking_type_id"):
        picking_type_name = _clean_picking_type_name(picking["picking_type_id"][1])

    fallback_label = picking_type_name or reference_code or "Picking"
    primary_line = ordered_lines[0] if ordered_lines else None
    all_lines = all_lines or ordered_lines
    total_line_count = len(all_lines)
    completed_line_count = sum(1 for line in all_lines if line.get("picked"))

    picking["reference_code"] = reference_code
    picking["open_line_count"] = len(ordered_lines)
    picking["total_line_count"] = total_line_count
    picking["completed_line_count"] = completed_line_count
    picking["progress_ratio"] = _build_progress_ratio(completed_line_count, total_line_count)
    picking["primary_item_display"] = (
        _build_primary_item_display(
            primary_line.get("quantity_demand"),
            primary_line.get("product_short_name", primary_line.get("product_name", "")),
        )
        if primary_line
        else fallback_label
    )
    picking["primary_item_sku"] = primary_line.get("product_sku", "") if primary_line else ""
    picking["primary_product_id"] = primary_line.get("product_id") if primary_line else None
    picking["next_location_short"] = primary_line.get("location_src_short", "") if primary_line else ""
    picking["primary_zone_key"] = _location_zone_key(primary_line.get("location_src", "")) if primary_line else ""
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
                "origin",
                "partner_id",
                "scheduled_date",
                "state",
                "picking_type_id",
                "priority",
            ],
            limit=100,
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

        product_ids = list(
            {
                line["product_id"][0]
                for line in raw_lines
                if line.get("product_id")
            }
        )
        product_map: dict[int, dict[str, Any]] = {}
        if product_ids:
            products = await self._odoo.search_read(
                "product.product",
                [("id", "in", product_ids)],
                ["id", "default_code"],
            )
            product_map = {product["id"]: product for product in products}

        lines_by_picking: dict[int, list[dict[str, Any]]] = defaultdict(list)
        for raw_line in raw_lines:
            picking_value = raw_line.get("picking_id")
            if not picking_value:
                continue
            picking_id = picking_value[0]
            move_id = raw_line["move_id"][0] if raw_line.get("move_id") else None
            move = move_map.get(move_id, {})
            product_id = raw_line["product_id"][0] if raw_line.get("product_id") else None
            product = product_map.get(product_id, {})
            enriched_line = _enrich_line_payload(
                {
                    "id": raw_line["id"],
                    "product_id": product_id,
                    "product_name": _clean_product_name(raw_line["product_id"][1]) if raw_line.get("product_id") else "",
                    "product_sku": product.get("default_code") or "",
                    "quantity_demand": move.get("product_uom_qty", raw_line.get("quantity", 0)),
                    "quantity_done": raw_line.get("quantity", 0) if move.get("picked") else 0,
                    "picked": bool(move.get("picked")),
                    "location_src_id": raw_line["location_id"][0] if raw_line.get("location_id") else None,
                    "location_src": raw_line["location_id"][1] if raw_line.get("location_id") else "",
                }
            )
            lines_by_picking[picking_id].append(enriched_line)

        enriched_pickings = []
        for picking in pickings:
            all_lines = lines_by_picking.get(picking["id"], [])
            route_plan = build_route_plan(all_lines)
            ordered_lines = route_plan.get("ordered_move_lines", [])
            _apply_operational_preview(picking, ordered_lines, all_lines)
            enriched_pickings.append(_apply_human_context(picking, include_voice_intro=False))

        # Overwrite primary_product_id with the kit/finished-product image when the
        # origin field contains a recognisable product name (e.g. "Sparkasse (BOM 12)").
        kit_names = list({p["kit_name"] for p in enriched_pickings if p.get("kit_name")})
        if kit_names:
            kit_products = await self._odoo.search_read(
                "product.product",
                [("product_tmpl_id.name", "in", kit_names)],
                ["id", "product_tmpl_id"],
                limit=len(kit_names) * 5,
            )
            kit_id_by_name: dict[str, int] = {}
            for kp in kit_products:
                tmpl = kp.get("product_tmpl_id")
                raw_name = tmpl[1] if isinstance(tmpl, list) else str(tmpl)
                # Odoo includes [ref] prefix in display_name — strip it
                clean = _clean_product_name(raw_name)
                if clean not in kit_id_by_name:
                    kit_id_by_name[clean] = kp["id"]
            for picking in enriched_pickings:
                kit = picking.get("kit_name", "")
                if kit and kit in kit_id_by_name:
                    picking["primary_product_id"] = kit_id_by_name[kit]

        return enriched_pickings

    async def get_picking_detail(self, picking_id: int) -> dict:
        """Load a single picking with move-line details and operational labels."""
        pickings = await self._odoo.search_read(
            "stock.picking",
            [("id", "=", picking_id)],
            [
                "name",
                "origin",
                "partner_id",
                "scheduled_date",
                "state",
                "move_ids",
                "location_id",
                "location_dest_id",
                "picking_type_id",
                "priority",
            ],
            limit=100,
        )
        if not pickings:
            return {"error": "Picking nicht gefunden"}

        picking = pickings[0]
        # Single search_read instead of search + read (saves one Odoo round-trip).
        raw_lines = await self._odoo.execute_kw(
            "stock.move.line",
            "search_read",
            [[("picking_id", "=", picking_id)]],
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

        if not raw_lines:
            picking["move_lines"] = []
            picking["route_plan"] = build_route_plan([])
            _apply_operational_preview(picking, [])
            _apply_human_context(picking, include_voice_intro=True)
            picking["has_pending_quality_ai"] = await self._check_pending_quality_ai(picking_id)
            return picking

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

        product_meta_map: dict[int, dict[str, Any]] = {}
        if product_ids:
            products = await self._odoo.search_read(
                "product.product",
                [("id", "in", product_ids)],
                ["id", "barcode", "default_code"],
            )
            product_meta_map = {product["id"]: product for product in products}

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
                        "product_barcode": product_meta_map.get(product_id, {}).get("barcode") if product_id else None,
                        "product_sku": product_meta_map.get(product_id, {}).get("default_code") if product_id else "",
                        "quantity_demand": move.get("product_uom_qty", raw_line.get("quantity", 0)),
                        "quantity_done": raw_line.get("quantity", 0) if move.get("picked") else 0,
                        "picked": bool(move.get("picked")),
                        "location_src_id": raw_line["location_id"][0] if raw_line.get("location_id") else None,
                        "location_src": raw_line["location_id"][1] if raw_line.get("location_id") else "",
                        "location_dest_id": raw_line["location_dest_id"][0] if raw_line.get("location_dest_id") else None,
                        "location_dest": raw_line["location_dest_id"][1] if raw_line.get("location_dest_id") else "",
                        "lot": raw_line["lot_id"][1] if raw_line.get("lot_id") else None,
                    }
                )
            )

        route_plan = build_route_plan(move_lines)
        ordered_lines = route_plan.pop("ordered_move_lines")
        picking["move_lines"] = ordered_lines
        picking["route_plan"] = route_plan
        _apply_operational_preview(picking, ordered_lines, move_lines)
        opening_instruction = ordered_lines[0].get("voice_instruction_short", "") if ordered_lines else ""
        _apply_human_context(
            picking,
            include_voice_intro=True,
            opening_instruction=opening_instruction,
        )

        # Check for pending AI quality evaluations on this picking
        picking["has_pending_quality_ai"] = await self._check_pending_quality_ai(picking_id)

        return picking

    async def _check_pending_quality_ai(self, picking_id: int) -> bool:
        """Check if there are pending AI evaluations for quality alerts on this picking.

        Alerts stuck in 'pending' for more than 10 minutes are treated as stale
        (the error workflow should have flipped them to 'failed' by then).
        """
        _STALE_MINUTES = 10
        try:
            alerts = await self._odoo.search_read(
                "quality.alert.custom",
                [
                    ("picking_id", "=", picking_id),
                    ("ai_evaluation_status", "=", "pending"),
                ],
                ["id", "create_date"],
                limit=5,
            )
            if not alerts:
                return False
            now = datetime.now(timezone.utc)
            for alert in alerts:
                create_str = alert.get("create_date")
                if create_str:
                    try:
                        created = datetime.strptime(str(create_str), "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
                        if (now - created).total_seconds() > _STALE_MINUTES * 60:
                            continue  # stale — don't count
                    except (ValueError, TypeError):
                        pass
                return True  # at least one non-stale pending alert
            return False
        except Exception:
            return False  # don't block picking detail on AI status errors

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

        # Single search_read instead of search + read (saves one Odoo round-trip).
        moves = await self._odoo.execute_kw(
            "stock.move",
            "search_read",
            [[("picking_id", "=", picking_id)]],
            {"fields": ["id", "picked"]},
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

                await self._n8n.fire_event(
                    "pick-confirmed",
                    {
                        "picking_id": picking_id,
                        "completed_by": completed_by,
                        "completed_by_user_id": completed_by_user_id,
                        "completed_by_device_id": completed_by_device_id,
                    },
                    picker={
                        "user_id": completed_by_user_id or None,
                        "name": completed_by,
                    },
                    device_id=completed_by_device_id or None,
                    picking_context={
                        "picking_id": picking_id,
                        "move_line_id": move_line_id,
                        "product_id": product_id,
                        "location_id": None,
                        "priority": None,
                        "origin": None,
                    },
                )

        return {
            "success": True,
            "message": "Auftrag abgeschlossen." if picking_complete else "Bestaetigt.",
            "picking_complete": picking_complete,
        }
