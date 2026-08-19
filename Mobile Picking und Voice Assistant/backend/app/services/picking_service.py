"""
Business logic for picking operations.

Odoo 18/19 notes:
- `stock.move.line.quantity` is the relevant quantity field
- `stock.move.line.picked` indicates whether a line was confirmed in the UI flow
"""
from __future__ import annotations

import json
import logging
import re
import time
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

from app.services.mobile_workflow import PickerIdentity
from app.services.n8n_webhook import N8NWebhookClient, coerce_event_result
from app.services.odoo_client import OdooAPIError, OdooClient
from app.services.route_optimizer import build_route_plan
from app.services.serial_validation import build_serial_move_line_values
from app.utils.serial import reconcile_serials

logger = logging.getLogger(__name__)


def _emit_serial_confirm(
    success: bool,
    picking_id: int,
    move_line_id: int,
    product_id: int | None,
    serial_recorded: bool,
    t0: float,
) -> None:
    """Emit a structured serial_confirm telemetry event.

    Invariant: ``confirm_pick_line`` emits exactly one such event per call on
    every exit path — both failures (``success=False``: line missing, wrong
    barcode, out of stock) and successes. This keeps the ``success_rate`` metric
    in ``summarize_serial_events`` a true rate over all confirm attempts, not
    only over the ones that happened to succeed.
    """
    logger.info(json.dumps({
        "event_type": "serial_confirm",
        "picking_id": picking_id,
        "move_line_id": move_line_id,
        "product_id": product_id,
        "success": success,
        "serial_recorded": serial_recorded,
        "latency_ms": int((time.monotonic() - t0) * 1000),
    }, ensure_ascii=False))


def _clean_product_name(display_name: str) -> str:
    """Strip Odoo's '[barcode/ref] ' prefix from product display names."""
    return re.sub(r"^\[.*?\]\s*", "", display_name or "")


def _m2o_id(value: Any) -> int | None:
    if isinstance(value, (list, tuple)) and value:
        candidate = value[0]
        return candidate if isinstance(candidate, int) and not isinstance(candidate, bool) else None
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    return None


def _m2o_name(value: Any) -> str:
    if isinstance(value, (list, tuple)) and len(value) > 1:
        return str(value[1] or "").strip()
    return ""


def _date_key(value: Any) -> str:
    raw = str(value or "").strip()
    return raw[:10] if len(raw) >= 10 else ""


def _shipping_address(partner: dict[str, Any]) -> dict[str, str]:
    country = partner.get("country_id")
    return {
        "street": partner.get("street") or "",
        "street2": partner.get("street2") or "",
        "zip": partner.get("zip") or "",
        "city": partner.get("city") or "",
        "country": country[1] if isinstance(country, (list, tuple)) and len(country) > 1 else "",
    }


async def _read_partner_map(odoo, partner_ids: list[int]) -> dict[int, dict[str, Any]]:
    ids = sorted({pid for pid in partner_ids if pid is not None})
    if not ids:
        return {}
    partners = await odoo.search_read(
        "res.partner",
        [("id", "in", ids)],
        ["name", "street", "street2", "zip", "city", "country_id", "email", "phone"],
        limit=len(ids),
    )
    return {partner["id"]: partner for partner in partners}


def _apply_shipping_context(picking: dict[str, Any], partner_map: dict[int, dict[str, Any]]) -> None:
    partner_id = _m2o_id(picking.get("partner_id"))
    partner = partner_map.get(partner_id, {})
    picking["customer_name"] = _m2o_name(picking.get("partner_id")) or partner.get("name") or ""
    picking["shipping_address"] = _shipping_address(partner)
    picking["customer_reference"] = picking.get("origin") or picking.get("name") or ""
    picking["delivery_date"] = _date_key(picking.get("date_deadline") or picking.get("scheduled_date"))
    picking["carrier_name"] = _m2o_name(picking.get("carrier_id")) if "carrier_id" in picking else ""


def _line_is_picked(raw_line: dict[str, Any], move: dict[str, Any]) -> bool:
    if "picked" in raw_line:
        return bool(raw_line.get("picked"))
    return bool(move.get("picked"))


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
    segments.append(f"{_format_quantity(quantity)} Stück.")
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

    async def get_stock_snapshot(
        self,
        *,
        product_id: int | None,
        location_id: int | None,
    ) -> dict[str, Any]:
        if product_id is None:
            return {
                "product_id": None,
                "location_id": location_id,
                "location_name": "",
                "quantity_available": 0.0,
                "quantity_total": 0.0,
                "available": 0.0,
                "total": 0.0,
                "status": "unknown",
                "alternative_locations": [],
                "recommendation": None,
            }

        quants = await self._odoo.search_read(
            "stock.quant",
            [("product_id", "=", product_id)],
            ["quantity", "reserved_quantity", "location_id"],
            limit=50,
        )

        current_available = 0.0
        current_total = 0.0
        current_location_name = ""
        alternative_locations: list[dict[str, Any]] = []

        for quant in quants:
            total_quantity = float(quant.get("quantity", 0) or 0)
            available_quantity = total_quantity - float(quant.get("reserved_quantity", 0) or 0)
            location_value = quant.get("location_id")
            location_tuple = location_value if isinstance(location_value, list) else location_value or []
            quant_location_id = location_tuple[0] if location_tuple else None
            quant_location_name = location_tuple[1] if location_tuple else ""

            if quant_location_id == location_id:
                current_available += available_quantity
                current_total += total_quantity
                current_location_name = quant_location_name or current_location_name
                continue

            if available_quantity > 0 and quant_location_id:
                alternative_locations.append(
                    {
                        "id": quant_location_id,
                        "name": quant_location_name,
                        "quantity_available": round(available_quantity, 2),
                    }
                )

        alternative_locations.sort(key=lambda item: (-item["quantity_available"], item["name"]))
        alternative_locations = alternative_locations[:3]

        quantity_available = round(current_available, 2)
        quantity_total = round(current_total, 2)
        status = "available" if quantity_available > 0 else "out_of_stock"

        recommendation = None
        if location_id and quantity_available <= 0 and alternative_locations:
            recommendation = {
                "action": "trigger_replenishment",
                "location_id": location_id,
                "recommended_location_id": alternative_locations[0]["id"],
                "recommended_location": alternative_locations[0]["name"],
                "reason": "Am Zielplatz ist kein verfügbarer Bestand vorhanden, aber an einem Alternativplatz liegt Ware.",
                "quantity": 1.0,
            }

        return {
            "product_id": product_id,
            "location_id": location_id,
            "location_name": current_location_name,
            "quantity_available": quantity_available,
            "quantity_total": quantity_total,
            "available": quantity_available,
            "total": quantity_total,
            "status": status,
            "alternative_locations": alternative_locations,
            "recommendation": recommendation,
        }

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
                "date_deadline",
                "state",
                "picking_type_id",
                "priority",
            ],
            limit=100,
        )
        if not pickings:
            return []

        partner_map = await _read_partner_map(
            self._odoo,
            [_m2o_id(picking.get("partner_id")) for picking in pickings],
        )
        for picking in pickings:
            _apply_shipping_context(picking, partner_map)

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
                    "picked",
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
            picked = _line_is_picked(raw_line, move)
            product_id = raw_line["product_id"][0] if raw_line.get("product_id") else None
            product = product_map.get(product_id, {})
            enriched_line = _enrich_line_payload(
                {
                    "id": raw_line["id"],
                    "product_id": product_id,
                    "product_name": _clean_product_name(raw_line["product_id"][1]) if raw_line.get("product_id") else "",
                    "product_sku": product.get("default_code") or "",
                    "quantity_demand": move.get("product_uom_qty", raw_line.get("quantity", 0)),
                    "quantity_done": raw_line.get("quantity", 0) if picked else 0,
                    "picked": picked,
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
                "date_deadline",
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
        partner_map = await _read_partner_map(
            self._odoo,
            [_m2o_id(picking.get("partner_id"))],
        )
        _apply_shipping_context(picking, partner_map)
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
                    "picked",
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
                ["id", "barcode", "default_code", "tracking"],
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
            picked = _line_is_picked(raw_line, move)
            move_lines.append(
                _enrich_line_payload(
                    {
                        "id": raw_line["id"],
                        "product_id": product_id,
                        "product_name": _clean_product_name(raw_line["product_id"][1]) if raw_line.get("product_id") else "",
                        "product_barcode": product_meta_map.get(product_id, {}).get("barcode") if product_id else None,
                        "product_sku": product_meta_map.get(product_id, {}).get("default_code") if product_id else "",
                        "tracking": product_meta_map.get(product_id, {}).get("tracking") if product_id else None,
                        "quantity_demand": move.get("product_uom_qty", raw_line.get("quantity", 0)),
                        "quantity_done": raw_line.get("quantity", 0) if picked else 0,
                        "picked": picked,
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

    async def reconcile_return_serials(self, picking_id: int, returned_serials: list[str]) -> dict[str, Any]:
        """Compare returned serials with the serials recorded on a shipped picking.

        This is intentionally read-only: Odoo remains the system of record for the
        shipped serials, while follow-up handling of deviations can be layered on
        later as Quality Alert, n8n event, or supervisor queue.
        """
        fields = ["id", "product_id", "lot_id", "lot_name"]
        try:
            lines = await self._odoo.execute_kw(
                "stock.move.line",
                "search_read",
                [[("picking_id", "=", picking_id)]],
                {"fields": fields},
            )
        except OdooAPIError:
            lines = await self._odoo.execute_kw(
                "stock.move.line",
                "search_read",
                [[("picking_id", "=", picking_id)]],
                {"fields": ["id", "product_id", "lot_id"]},
            )

        if not lines:
            return {
                "success": False,
                "picking_id": picking_id,
                "message": "Picking nicht gefunden oder ohne Seriennummern.",
                "shipped_serials": [],
                "returned_serials": [serial.strip() for serial in returned_serials if serial and serial.strip()],
                "reconcile": reconcile_serials([], returned_serials),
            }

        product_ids = sorted(
            {
                product_id
                for product_id in (_m2o_id(line.get("product_id")) for line in lines)
                if product_id is not None
            }
        )
        product_meta: dict[int, dict[str, Any]] = {}
        if product_ids:
            products = await self._odoo.search_read(
                "product.product",
                [("id", "in", product_ids)],
                ["id", "tracking", "display_name", "name", "default_code"],
            )
            product_meta = {product["id"]: product for product in products}

        shipped_entries = []
        shipped_serials = []
        for line in lines:
            product_id = _m2o_id(line.get("product_id"))
            product = product_meta.get(product_id, {})
            if product.get("tracking") != "serial":
                continue

            serial_number = _m2o_name(line.get("lot_id")) or str(line.get("lot_name") or "").strip()
            if not serial_number:
                continue

            product_name = (
                product.get("display_name")
                or product.get("name")
                or _m2o_name(line.get("product_id"))
            )
            shipped_serials.append(serial_number)
            shipped_entries.append({
                "move_line_id": line.get("id"),
                "product_id": product_id,
                "product_name": _clean_product_name(product_name),
                "serial_number": serial_number,
            })

        returned_clean = [serial.strip() for serial in returned_serials if serial and serial.strip()]
        result = reconcile_serials(shipped_serials, returned_clean)
        summary = {
            "shipped_count": len(shipped_serials),
            "returned_count": len(returned_clean),
            "missing_count": len(result["missing"]),
            "unknown_count": len(result["unknown"]),
            "duplicate_count": len(result["duplicates"]),
        }

        return {
            "success": True,
            "ok": result["ok"],
            "picking_id": picking_id,
            "message": (
                "Retouren-Seriennummern passen zur Lieferung."
                if result["ok"]
                else "Retouren-Seriennummern weichen von der Lieferung ab."
            ),
            "shipped_serials": shipped_serials,
            "shipped_items": shipped_entries,
            "returned_serials": returned_clean,
            "reconcile": result,
            "summary": summary,
        }

    async def confirm_pick_line(
        self,
        picking_id: int,
        move_line_id: int,
        scanned_barcode: str,
        quantity: float,
        picker_identity: PickerIdentity | None = None,
        serial_number: str = "",
    ) -> dict:
        """
        Confirm a move line via barcode scan.

        The Odoo 18/19 flow uses `stock.move.line.picked` to track whether a line is done.
        """
        _t0 = time.monotonic()
        lines = await self._odoo.execute_kw(
            "stock.move.line",
            "search_read",
            [[("id", "=", move_line_id), ("picking_id", "=", picking_id)]],
            {
                "fields": ["id", "product_id", "quantity", "move_id", "location_id", "lot_id"],
                "limit": 1,
            },
        )
        if not lines:
            _emit_serial_confirm(False, picking_id, move_line_id, None, False, _t0)
            return {
                "success": False,
                "message": "Move-Line nicht gefunden",
                "picking_complete": False,
            }

        line = lines[0]
        product_id = line["product_id"][0] if line.get("product_id") else None
        move_id = line["move_id"][0] if line.get("move_id") else None
        location_id = line["location_id"][0] if line.get("location_id") else None
        existing_lot_id = line["lot_id"][0] if line.get("lot_id") else None

        if product_id and scanned_barcode:
            products = await self._odoo.search_read(
                "product.product",
                [("id", "=", product_id)],
                ["barcode"],
            )
            expected_barcode = products[0].get("barcode") if products else None
            if expected_barcode and scanned_barcode != expected_barcode:
                _emit_serial_confirm(False, picking_id, move_line_id, product_id, False, _t0)
                return {
                    "success": False,
                    "message": f"Falscher Artikel. Erwartet: {expected_barcode}",
                    "picking_complete": False,
                }

        stock_snapshot = None
        if location_id is not None:
            stock_snapshot = await self.get_stock_snapshot(
                product_id=product_id,
                location_id=location_id,
            )
        if stock_snapshot and stock_snapshot["status"] == "out_of_stock":
            _emit_serial_confirm(False, picking_id, move_line_id, product_id, False, _t0)
            return {
                "success": False,
                "message": "Kein Bestand am aktuellen Lagerplatz. Bitte Problem melden, Nachschub anfordern oder überspringen.",
                "picking_complete": False,
                "blocked_reason": "out_of_stock",
                "stock_context": stock_snapshot,
            }

        qty = quantity if quantity > 0 else line.get("quantity", 1.0)
        line_values: dict[str, Any] = {"quantity": qty, "picked": True}

        tracking = None
        if product_id:
            tracked = await self._odoo.search_read(
                "product.product", [("id", "=", product_id)], ["tracking"], limit=1
            )
            tracking = tracked[0].get("tracking") if tracked else None

        recorded_serial = ""
        serial_result = await build_serial_move_line_values(
            self._odoo,
            product_id=product_id,
            tracking=tracking,
            serial_number=serial_number,
            quantity=qty,
            location_id=location_id,
            existing_lot_id=existing_lot_id,
        )
        if not serial_result["ok"]:
            _emit_serial_confirm(False, picking_id, move_line_id, product_id, False, _t0)
            return {
                "success": False,
                "message": serial_result["message"],
                "picking_complete": False,
                **{k: v for k, v in serial_result.items() if k not in {"ok", "message", "values", "recorded_serial"}},
            }
        line_values.update(serial_result.get("values", {}))
        recorded_serial = serial_result.get("recorded_serial", "")

        # Quantity (and the optional serial) go to Odoo in a single move-line write
        # instead of two separate round-trips for the same record.
        await self._odoo.write("stock.move.line", [move_line_id], line_values)

        # Ab hier ist die Buchung in Odoo geschrieben -- alles Weitere ist
        # Nachlauf. Fliegt hier eine Ausnahme heraus, bricht der Router die
        # Idempotenz-Reservierung ab (`abort_idempotent_request`), obwohl die
        # Position bereits gebucht ist: der Wiederholungsversuch mit demselben
        # Idempotency-Key laeuft dann erneut durch und bucht ein zweites Mal.
        # Genau diese halbfertige Buchung darf nicht entstehen, deshalb wird der
        # Fehler protokolliert und als degradierte Antwort gemeldet, nicht
        # geworfen. Der urspruengliche Grund bleibt im Log sichtbar.
        # Single search_read instead of search + read (saves one Odoo round-trip).
        move_lines: list[dict[str, Any]] = []
        followup_error = ""
        try:
            move_lines = await self._odoo.execute_kw(
                "stock.move.line",
                "search_read",
                [[("picking_id", "=", picking_id)]],
                {"fields": ["id", "picked"]},
            )
        except Exception as exc:
            followup_error = str(exc)
            logger.warning(
                "Folgeabfrage nach gebuchter Position fehlgeschlagen (picking %s, "
                "move_line %s): %s",
                picking_id,
                move_line_id,
                followup_error,
            )
        all_done = bool(move_lines) and all(line.get("picked") for line in move_lines)

        picking_complete = False
        validate_error = ""
        if all_done:
            try:
                await self._odoo.call_method(
                    "stock.picking",
                    "button_validate",
                    [picking_id],
                    context={"skip_immediate": True, "skip_backorder": True},
                )
                picking_complete = True
            except OdooAPIError as exc:
                # Jede Zeile ist gepickt, und Odoo weigert sich trotzdem --
                # typisch, wenn eine Zeile noch ein Los oder eine Seriennummer
                # verlangt. Frueher verschwand der Grund hier spurlos: der
                # Auftrag blieb offen, der Picker las "Bestaetigt." und ging
                # weiter. Sichtbar falsch und unsichtbar begruendet ist die
                # Kombination, die einen Fehler im Betrieb unauffindbar macht.
                picking_complete = False
                validate_error = str(exc)
                logger.warning(
                    "button_validate refused picking %s after the last line was "
                    "confirmed: %s",
                    picking_id,
                    validate_error,
                )
            except Exception as exc:
                # Gleiche Begruendung wie oben: die Position ist gebucht, also
                # darf auch ein untypischer Fehler den Abbruchpfad nicht mehr
                # ausloesen.
                picking_complete = False
                validate_error = str(exc)
                logger.warning(
                    "button_validate fuer picking %s unerwartet fehlgeschlagen: %s",
                    picking_id,
                    validate_error,
                )

            # Bei `picking_complete` feuerte hier der v1-Workflow
            # `pick-confirmed`, den es nicht mehr gibt. Die Buchung passiert in
            # Odoo; ein n8n-Folgeprozess existiert fuer diesen Fall nicht mehr,
            # also bleibt auch kein degradierter Zweig zu melden.
        _emit_serial_confirm(True, picking_id, move_line_id, product_id, bool(recorded_serial), _t0)
        if picking_complete:
            message = "Auftrag abgeschlossen."
        elif validate_error or followup_error:
            # Der Picker muss den Unterschied hoeren: die Position ist gebucht,
            # der AUFTRAG aber nicht -- sonst legt er das Geraet weg und der
            # Auftrag bleibt offen liegen. Odoos Begruendung steht im Log, nicht
            # in der Antwort: sie enthaelt Modell- und Feldnamen.
            message = (
                "Position gebucht, aber der Auftrag konnte nicht abgeschlossen "
                "werden. Bitte im Lagerbüro melden."
            )
        else:
            message = "Bestätigt."
        return {
            "success": True,
            "message": message,
            "picking_complete": picking_complete,
            "recorded_serial": recorded_serial,
        }

    async def request_replenishment(
        self,
        picking_id: int,
        move_line_id: int,
        *,
        reason: str = "",
        picker_identity: PickerIdentity | None = None,
    ) -> dict[str, Any]:
        lines = await self._odoo.execute_kw(
            "stock.move.line",
            "search_read",
            [[("id", "=", move_line_id), ("picking_id", "=", picking_id)]],
            {"fields": ["id", "product_id", "location_id"]},
        )
        if not lines:
            return {
                "success": False,
                "message": "Move-Line nicht gefunden.",
            }

        line = lines[0]
        product_id = line["product_id"][0] if line.get("product_id") else None
        location_tuple = line.get("location_id") if isinstance(line.get("location_id"), list) else []
        location_id = location_tuple[0] if location_tuple else None

        stock_snapshot = await self.get_stock_snapshot(
            product_id=product_id,
            location_id=location_id,
        )
        if stock_snapshot["status"] != "out_of_stock":
            return {
                "success": False,
                "message": (
                    "Am aktuellen Lagerplatz sind laut System noch "
                    f"{_format_quantity(stock_snapshot['quantity_available'])} Stück verfügbar."
                ),
                "stock_context": stock_snapshot,
            }

        recommendation = stock_snapshot.get("recommendation")
        if not recommendation:
            return {
                "success": False,
                "message": "Kein Alternativbestand für Nachschub gefunden. Bitte Problem melden.",
                "stock_context": stock_snapshot,
            }

        requested_by = "mobile-picking-assistant"
        requested_by_user_id = None
        requested_by_device_id = None
        if picker_identity and picker_identity.user_id:
            requested_by = picker_identity.picker_name or requested_by
            requested_by_user_id = picker_identity.user_id
            requested_by_device_id = picker_identity.device_id or None

        # Kein Anstoss ueber n8n mehr: der v1-Workflow `shortage-reported`
        # ist weg, und es gibt keinen Nachfolger, der den Nachschub buchen
        # wuerde. Die Antwort nennt deshalb den Befund und den Alternativplatz,
        # behauptet aber keine ausgeloeste Anforderung -- eine Meldung
        # "Nachschub angefordert", der nichts folgt, ist schlimmer als gar
        # keine: der Picker wartet dann auf Ware, die niemand bewegt.
        return {
            "success": True,
            "message": (
                "Kein verfuegbarer Bestand am aktuellen Platz. "
                f"Ware liegt in {recommendation.get('recommended_location', 'einem Alternativplatz')}. "
                "Bitte im Lagerbuero melden."
            ),
            "replenishment_triggered": False,
            "recommended_location_id": recommendation.get("recommended_location_id"),
            "recommended_location": recommendation.get("recommended_location"),
            "stock_context": stock_snapshot,
        }
