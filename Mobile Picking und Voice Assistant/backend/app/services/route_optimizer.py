"""
Deterministische Routenlogik fuer das Mobile Picking.

Die Heuristik ist bewusst simpel und stabil:
- noch offene Positionen zuerst
- danach Lagerbereich/Zone
- danach Regal-/Ebenen-/Platznummern

So bekommt die PWA eine nachvollziehbare Reihenfolge, ohne dass wir
den Odoo-Datenbestand oder den Picking-Flow riskant umbauen.
"""
from __future__ import annotations

import re
from typing import Any


_GENERIC_SLOT_PATTERN = re.compile(r"([A-Z]+)[-_]?(\d+)", re.IGNORECASE)


def _letters_to_rank(value: str) -> int:
    if not value:
        return 99
    total = 0
    for char in value.upper():
        if "A" <= char <= "Z":
            total = (total * 26) + (ord(char) - 64)
    return total or 99


def _extract_prefixed_number(location: str, prefix: str) -> int:
    match = re.search(rf"{prefix}\s*(\d+)", location, re.IGNORECASE)
    return int(match.group(1)) if match else 0


def _location_parts(location: str) -> list[str]:
    return [part.strip() for part in (location or "").split("/") if part and part.strip()]


def _zone_key(location: str) -> tuple[int, str]:
    lower = (location or "").lower()
    if "links" in lower:
        return (0, "links")
    if "mitte" in lower:
        return (1, "mitte")
    if "rechts" in lower:
        return (2, "rechts")

    parts = _location_parts(location)
    label = parts[-2].lower() if len(parts) >= 2 else lower
    return (9, label or "unbekannt")


def _location_coordinate(location: str) -> tuple[int, int, int, int]:
    parts = _location_parts(location)
    terminal = parts[-1].upper() if parts else ""
    zone_rank, _ = _zone_key(location)

    side_token = terminal.split("-")[0] if terminal else ""
    side_rank = _letters_to_rank(side_token)
    aisle = _extract_prefixed_number(terminal, "E")
    position = _extract_prefixed_number(terminal, "P")

    if not aisle and not position:
        generic_match = _GENERIC_SLOT_PATTERN.search(terminal)
        if generic_match:
            side_rank = _letters_to_rank(generic_match.group(1))
            position = int(generic_match.group(2))

    return (zone_rank, side_rank, aisle, position)


def _location_sort_key(line: dict[str, Any]) -> tuple[Any, ...]:
    location = line.get("location_src") or ""
    zone_rank, zone_label = _zone_key(location)
    coord = _location_coordinate(location)
    return (
        bool(line.get("picked")),
        zone_rank,
        zone_label,
        coord[1],
        coord[2],
        coord[3],
        location.lower(),
        (line.get("product_name") or "").lower(),
    )


def _travel_steps(previous_location: str | None, current_location: str) -> int:
    if not previous_location:
        return 0

    prev_coord = _location_coordinate(previous_location)
    current_coord = _location_coordinate(current_location)
    return sum(abs(a - b) for a, b in zip(prev_coord, current_coord))


def _zone_label(location: str) -> str:
    parts = _location_parts(location)
    if len(parts) >= 2:
        return parts[-2]
    return location or "Unbekannt"


def build_route_plan(move_lines: list[dict[str, Any]]) -> dict[str, Any]:
    """Create a predictable picking route based on location strings."""
    ordered_lines = sorted(move_lines, key=_location_sort_key)
    remaining_lines = [line for line in ordered_lines if not line.get("picked")]
    completed_count = len(ordered_lines) - len(remaining_lines)

    previous_location: str | None = None
    estimated_travel_steps = 0
    stops: list[dict[str, Any]] = []
    zone_sequence: list[str] = []

    for index, line in enumerate(remaining_lines, start=1):
        location = line.get("location_src") or ""
        step_cost = _travel_steps(previous_location, location)
        estimated_travel_steps += step_cost
        zone_name = _zone_label(location)
        if zone_name and zone_name not in zone_sequence:
            zone_sequence.append(zone_name)

        stops.append(
            {
                "sequence": index,
                "move_line_id": line["id"],
                "product_name": line.get("product_name", ""),
                "location_src": location,
                "estimated_steps_from_previous": step_cost,
            }
        )
        previous_location = location

    next_stop = remaining_lines[0] if remaining_lines else None

    return {
        "strategy": "zone-first-shortest-walk",
        "total_stops": len(ordered_lines),
        "completed_stops": completed_count,
        "remaining_stops": len(remaining_lines),
        "estimated_travel_steps": estimated_travel_steps,
        "next_move_line_id": next_stop["id"] if next_stop else None,
        "next_location_src": next_stop.get("location_src") if next_stop else None,
        "next_product_name": next_stop.get("product_name") if next_stop else None,
        "zone_sequence": zone_sequence,
        "stops": stops,
        "ordered_move_lines": remaining_lines,
    }
