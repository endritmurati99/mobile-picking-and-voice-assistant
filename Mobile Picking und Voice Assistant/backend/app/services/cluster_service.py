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
