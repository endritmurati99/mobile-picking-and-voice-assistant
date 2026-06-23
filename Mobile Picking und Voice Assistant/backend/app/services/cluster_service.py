"""
Cluster-/Batch-Picking — mehrere stock.picking gebuendelt in einem Rundgang.

Odoo 18: echter stock.picking.batch (action_confirm / action_done).
Box-Zuordnung ist rein logisch (Box N <-> Picking N), keine Odoo-Packages.
picking_service.py bleibt unberuehrt; Route-Sort wird wiederverwendet.

Verifizierte Odoo-18-Fakten siehe docs/superpowers/specs/2026-06-23-odoo18-batch-api-facts.md
"""
from __future__ import annotations

import json
import logging
import re
import time
from collections import defaultdict
from typing import Any

from app.services.n8n_webhook import coerce_event_result
from app.services.odoo_client import OdooAPIError
from app.services.route_optimizer import build_route_plan

logger = logging.getLogger(__name__)

# Farbtokens passend zum PWA-Designsystem (Akzent-Palette, zyklisch).
BOX_PALETTE: list[str] = ["#A299FF", "#FF8A7E", "#6FD3C7", "#F4C77B", "#7EA8FF", "#C58BFF"]


def assign_boxes(picking_ids: list[int]) -> dict[int, dict[str, Any]]:
    """Deterministische Box-Nummer + Farbe je Picking (1-based, nach picking_id sortiert)."""
    box_map: dict[int, dict[str, Any]] = {}
    for index, picking_id in enumerate(sorted(set(picking_ids))):
        box_map[picking_id] = {
            "box_index": index + 1,
            "box_color": BOX_PALETTE[index % len(BOX_PALETTE)],
        }
    return box_map


def build_cluster_lines(
    lines_by_picking: dict[int, list[dict[str, Any]]],
    box_map: dict[int, dict[str, Any]],
) -> list[dict[str, Any]]:
    """Alle Move-Lines mergen, mit Box/Picking taggen und route-sortieren.

    Offene Positionen werden via ``build_route_plan`` route-sortiert nach vorne
    gestellt; bereits gepickte Positionen landen am Ende.
    """
    merged: list[dict[str, Any]] = []
    for picking_id, lines in lines_by_picking.items():
        box = box_map.get(picking_id, {})
        for line in lines:
            tagged = dict(line)
            tagged["picking_id"] = picking_id
            tagged["box_index"] = box.get("box_index")
            tagged["box_color"] = box.get("box_color")
            merged.append(tagged)

    plan = build_route_plan(merged)
    ordered_open = plan["ordered_move_lines"]
    open_ids = {line["id"] for line in ordered_open}
    done = [line for line in merged if line["id"] not in open_ids]
    return ordered_open + done


def _zone_of(location: str) -> str:
    """Lagerzone aus dem Location-Pfad ableiten (vorletztes Segment)."""
    parts = [p.strip() for p in (location or "").split("/") if p.strip()]
    if len(parts) >= 2:
        return parts[-2]
    return parts[-1] if parts else "Unbekannt"


def _clean_product_name(display_name: str) -> str:
    """Odoo-'[ref] '-Prefix aus dem Produktnamen entfernen."""
    return re.sub(r"^\[.*?\]\s*", "", display_name or "")


class ClusterService:
    def __init__(self, odoo, n8n):
        self._odoo = odoo
        self._n8n = n8n

    async def suggest_batches(self) -> list[dict[str, Any]]:
        """Offene assigned-Pickings ohne Batch nach Lagerzone gruppieren."""
        pickings = await self._odoo.search_read(
            "stock.picking",
            [("state", "=", "assigned"), ("batch_id", "=", False)],
            ["name", "batch_id"],
            limit=100,
        )
        if not pickings:
            return []

        picking_ids = [p["id"] for p in pickings]
        name_by_id = {p["id"]: p["name"] for p in pickings}
        lines = await self._odoo.search_read(
            "stock.move.line",
            [("picking_id", "in", picking_ids)],
            ["picking_id", "location_id"],
            limit=max(500, len(picking_ids) * 20),
        )

        groups: dict[str, dict[str, Any]] = defaultdict(
            lambda: {"picking_ids": set(), "line_count": 0}
        )
        # Zone je Picking aus seiner ersten Move-Line ableiten (stabil).
        zone_by_picking: dict[int, str] = {}
        for line in lines:
            picking_id = line["picking_id"][0] if line.get("picking_id") else None
            if picking_id is None:
                continue
            zone = _zone_of(line["location_id"][1] if line.get("location_id") else "")
            zone_by_picking.setdefault(picking_id, zone)
            target_zone = zone_by_picking[picking_id]
            groups[target_zone]["picking_ids"].add(picking_id)
            groups[target_zone]["line_count"] += 1

        result = []
        for zone, data in groups.items():
            pids = sorted(data["picking_ids"])
            result.append(
                {
                    "zone": zone,
                    "picking_ids": pids,
                    "order_count": len(pids),
                    "line_count": data["line_count"],
                    "picking_names": [name_by_id[p] for p in pids],
                }
            )
        result.sort(key=lambda g: (-g["order_count"], g["zone"]))
        return result

    async def create_batch(self, picking_ids, picker_identity=None) -> dict[str, Any]:
        """Echten stock.picking.batch anlegen und bestaetigen (draft -> in_progress)."""
        ids = [int(p) for p in (picking_ids or [])]
        if not ids:
            raise ValueError("picking_ids darf nicht leer sein")

        # company_id von den Pickings uebernehmen -> verhindert _check_company.
        pickings = await self._odoo.search_read(
            "stock.picking", [("id", "in", ids)], ["company_id"], limit=len(ids)
        )
        company_id = None
        for picking in pickings:
            if picking.get("company_id"):
                company_id = picking["company_id"][0]
                break

        # 'name' bewusst weglassen -> Odoo-Sequenz 'picking.batch' fuellt es.
        vals: dict[str, Any] = {"picking_ids": [(6, 0, ids)]}
        if company_id is not None:
            vals["company_id"] = company_id
        if picker_identity and getattr(picker_identity, "user_id", None):
            vals["user_id"] = picker_identity.user_id

        batch_id = await self._odoo.create("stock.picking.batch", vals)
        await self._odoo.call_method("stock.picking.batch", "action_confirm", [batch_id])
        return await self.get_batch(batch_id)

    async def get_batch(self, batch_id: int) -> dict[str, Any]:
        """Batch mit gemergter, route-sortierter Sammelliste + Box-Tags + Fortschritt."""
        batches = await self._odoo.search_read(
            "stock.picking.batch", [("id", "=", batch_id)],
            ["name", "state", "picking_ids", "user_id"], limit=1,
        )
        if not batches:
            return {"error": "Batch nicht gefunden"}

        batch = batches[0]
        picking_ids = batch.get("picking_ids", []) or []
        pickings = await self._odoo.search_read(
            "stock.picking", [("id", "in", picking_ids)], ["name"],
            limit=len(picking_ids) or 1,
        ) if picking_ids else []
        name_by_picking = {p["id"]: p["name"] for p in pickings}
        box_map = assign_boxes(picking_ids)

        raw_lines = await self._odoo.search_read(
            "stock.move.line", [("picking_id", "in", picking_ids)],
            ["picking_id", "product_id", "quantity", "move_id", "location_id"],
            limit=max(500, len(picking_ids) * 20),
        ) if picking_ids else []

        move_ids = list({l["move_id"][0] for l in raw_lines if l.get("move_id")})
        moves = await self._odoo.search_read(
            "stock.move", [("id", "in", move_ids)], ["id", "product_uom_qty", "picked"],
        ) if move_ids else []
        move_map = {m["id"]: m for m in moves}

        product_ids = list({l["product_id"][0] for l in raw_lines if l.get("product_id")})
        products = await self._odoo.search_read(
            "product.product", [("id", "in", product_ids)],
            ["id", "default_code", "barcode", "tracking"],
        ) if product_ids else []
        product_map = {p["id"]: p for p in products}

        lines_by_picking: dict[int, list[dict[str, Any]]] = defaultdict(list)
        for raw in raw_lines:
            picking_id = raw["picking_id"][0] if raw.get("picking_id") else None
            move = move_map.get(raw["move_id"][0] if raw.get("move_id") else None, {})
            product_id = raw["product_id"][0] if raw.get("product_id") else None
            product = product_map.get(product_id, {})
            location = raw["location_id"][1] if raw.get("location_id") else ""
            loc_parts = [part.strip() for part in location.split("/") if part.strip()]
            lines_by_picking[picking_id].append({
                "id": raw["id"],
                "product_id": product_id,
                "product_name": _clean_product_name(raw["product_id"][1]) if raw.get("product_id") else "",
                "product_barcode": product.get("barcode"),
                "product_sku": product.get("default_code") or "",
                "tracking": product.get("tracking"),
                "quantity_demand": move.get("product_uom_qty", raw.get("quantity", 0)),
                "quantity_done": raw.get("quantity", 0) if move.get("picked") else 0,
                "picked": bool(move.get("picked")),
                "location_src": location,
                "location_src_short": loc_parts[-1] if loc_parts else location,
            })

        ordered = build_cluster_lines(lines_by_picking, box_map)
        for line in ordered:
            short = line.get("location_src_short", "")
            qty = line.get("quantity_demand", 0)
            name = line.get("product_name", "")
            line["voice_instruction_short"] = f"{short}. {qty} Stück. {name}.".strip()
            line["picking_name"] = name_by_picking.get(line.get("picking_id"), "")

        total = len(ordered)
        done = sum(1 for line in ordered if line.get("picked"))
        return {
            "batch_id": batch_id,
            "name": batch.get("name", ""),
            "state": batch.get("state", ""),
            "picker": batch["user_id"][1] if batch.get("user_id") else "",
            "boxes": [
                {"picking_id": pid, "picking_name": name_by_picking.get(pid, ""),
                 "box_index": box_map[pid]["box_index"], "box_color": box_map[pid]["box_color"]}
                for pid in sorted(picking_ids)
            ],
            "lines": ordered,
            "progress": {
                "total": total, "done": done,
                "ratio": round(done / total, 4) if total else 0.0,
            },
        }

    async def confirm_cluster_line(
        self, batch_id, picking_id, move_line_id,
        scanned_barcode="", quantity=0, serial_number="", picker_identity=None,
    ) -> dict[str, Any]:
        """Position bestaetigen: Menge (+ optional Serial) schreiben, OHNE Validierung.

        Anders als confirm_pick_line wird hier KEIN button_validate ausgeloest -
        der ganze Batch wird spaeter gesammelt via validate_batch abgeschlossen.
        """
        t0 = time.monotonic()
        # IDOR-Schutz: die Move-Line MUSS zu picking_id gehoeren UND dieses Picking
        # zum angefragten batch_id. Sonst koennte ein Client eine fremde move_line_id
        # einschleusen und Menge/Serial/picked auf einen anderen Auftrag schreiben.
        lines = await self._odoo.search_read(
            "stock.move.line",
            [
                ("id", "=", move_line_id),
                ("picking_id", "=", picking_id),
                ("picking_id.batch_id", "=", batch_id),
            ],
            ["id", "product_id", "quantity", "move_id", "location_id"],
            limit=1,
        )
        if not lines:
            self._emit_cluster_confirm(False, batch_id, picking_id, move_line_id, None, False, t0)
            return {"success": False,
                    "message": "Position gehört nicht zu diesem Batch.",
                    "progress": None}

        line = lines[0]
        product_id = line["product_id"][0] if line.get("product_id") else None
        move_id = line["move_id"][0] if line.get("move_id") else None

        if product_id and scanned_barcode:
            products = await self._odoo.search_read(
                "product.product", [("id", "=", product_id)], ["barcode", "tracking"])
            expected = products[0].get("barcode") if products else None
            if expected and scanned_barcode != expected:
                self._emit_cluster_confirm(False, batch_id, picking_id, move_line_id, product_id, False, t0)
                return {"success": False, "message": f"Falscher Artikel. Erwartet: {expected}",
                        "progress": None}

        qty = quantity if quantity > 0 else line.get("quantity", 1.0)
        line_values: dict[str, Any] = {"quantity": qty}

        recorded_serial = ""
        serial_clean = (serial_number or "").strip()
        if serial_clean and product_id:
            tracked = await self._odoo.search_read(
                "product.product", [("id", "=", product_id)], ["tracking"])
            if tracked and tracked[0].get("tracking") in ("serial", "lot"):
                line_values["lot_name"] = serial_clean
                recorded_serial = serial_clean

        await self._odoo.write("stock.move.line", [move_line_id], line_values)
        if move_id:
            await self._odoo.write("stock.move", [move_id], {"picked": True})

        self._emit_cluster_confirm(
            True, batch_id, picking_id, move_line_id, product_id, bool(recorded_serial), t0)
        batch = await self.get_batch(batch_id)
        return {"success": True, "message": "Bestätigt.", "recorded_serial": recorded_serial,
                "progress": batch.get("progress")}

    async def validate_batch(self, batch_id, picker_identity=None) -> dict[str, Any]:
        """Ganzen Batch gesammelt abschliessen via action_done (+ n8n-Event)."""
        batches = await self._odoo.search_read(
            "stock.picking.batch", [("id", "=", batch_id)], ["picking_ids", "user_id"], limit=1)
        if not batches:
            return {"success": False, "batch_complete": False, "message": "Batch nicht gefunden."}
        batch = batches[0]
        member_ids = batch.get("picking_ids", []) or []

        # Ownership: nur der zugewiesene Picker darf den Batch (destruktiv) abschliessen.
        owner = batch.get("user_id")
        owner_id = owner[0] if isinstance(owner, list) else owner
        requester_id = getattr(picker_identity, "user_id", None) if picker_identity else None
        if owner_id and requester_id and owner_id != requester_id:
            return {"success": False, "batch_complete": False,
                    "message": "Dieser Batch gehört einem anderen Picker."}

        try:
            result = await self._odoo.call_method(
                "stock.picking.batch", "action_done", [batch_id],
                context={
                    "skip_backorder": True,
                    "picking_ids_not_to_backorder": member_ids,
                    "skip_sms": True,
                },
            )
        except OdooAPIError as exc:
            return {"success": False, "batch_complete": False,
                    "message": f"Batch-Abschluss fehlgeschlagen: {exc}"}

        # action_done gibt bei offenen Rueckfragen ein Wizard-Action-Dict zurueck.
        if isinstance(result, dict) and result.get("res_model"):
            return {"success": False, "batch_complete": False,
                    "pending_action": result.get("res_model"),
                    "message": ("Batch-Abschluss erfordert eine manuelle Bestätigung in Odoo "
                                f"({result.get('res_model')}).")}

        completed_by = "mobile-picking-assistant"
        user_id = False
        if picker_identity and getattr(picker_identity, "user_id", None):
            completed_by = getattr(picker_identity, "picker_name", None) or completed_by
            user_id = picker_identity.user_id

        event = coerce_event_result(await self._n8n.fire_event(
            "batch-confirmed",
            {"batch_id": batch_id, "completed_by": completed_by, "completed_by_user_id": user_id},
            picker={"user_id": user_id or None, "name": completed_by},
        ))
        if not event.delivered:
            return {"success": True, "batch_complete": True, "integration_status": "degraded",
                    "integration_error": event.error,
                    "message": "Batch abgeschlossen, n8n-Folgeprozess degradiert."}
        return {"success": True, "batch_complete": True, "message": "Batch abgeschlossen."}

    def _emit_cluster_confirm(self, success, batch_id, picking_id, move_line_id,
                              product_id, serial_recorded, t0):
        """Strukturiertes cluster_confirm-Telemetrie-Event (analog serial_confirm)."""
        logger.info(json.dumps({
            "event_type": "cluster_confirm",
            "batch_id": batch_id,
            "picking_id": picking_id,
            "move_line_id": move_line_id,
            "product_id": product_id,
            "success": success,
            "serial_recorded": serial_recorded,
            "latency_ms": int((time.monotonic() - t0) * 1000),
        }, ensure_ascii=False))
