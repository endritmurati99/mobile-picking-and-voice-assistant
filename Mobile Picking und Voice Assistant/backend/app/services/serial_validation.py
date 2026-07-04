"""Serial/lot validation helpers for picking confirmations."""
from __future__ import annotations

from math import isclose
from typing import Any


def _quantity_as_float(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _stock_quantity(quant: dict[str, Any], *, include_reserved: bool = False) -> float:
    quantity = _quantity_as_float(quant.get("quantity"))
    if include_reserved:
        return quantity
    return quantity - _quantity_as_float(quant.get("reserved_quantity"))


def _has_required_stock(
    quants: list[dict[str, Any]],
    *,
    required_quantity: float,
    include_reserved: bool,
) -> bool:
    usable_quantity = sum(
        _stock_quantity(quant, include_reserved=include_reserved)
        for quant in quants
    )
    return usable_quantity + 1e-9 >= required_quantity


async def build_serial_move_line_values(
    odoo,
    *,
    product_id: int | None,
    tracking: str | None,
    serial_number: str,
    quantity: float,
    location_id: int | None,
    existing_lot_id: int | None = None,
) -> dict[str, Any]:
    """Return move-line values for a scanned serial/lot or a validation error.

    Serial-tracked products are strict: the picker must scan one existing Odoo
    serial number for exactly one unit. Lot-tracked products keep the previous
    additive behavior because one lot can cover multiple units.
    """
    tracking = (tracking or "none").strip()
    serial_clean = (serial_number or "").strip()

    if tracking == "lot":
        if not serial_clean:
            return {
                "ok": False,
                "code": "lot_required",
                "serial_required": True,
                "message": "Chargennummer erforderlich: Bitte die verwendete Charge scannen.",
            }
        if not product_id:
            return {
                "ok": False,
                "code": "lot_product_missing",
                "serial_not_found": True,
                "message": "Charge kann nicht validiert werden: Produkt fehlt an der Position.",
            }
        lots = await odoo.search_read(
            "stock.lot",
            [("product_id", "=", product_id), ("name", "=", serial_clean)],
            ["id", "name", "product_id"],
            limit=2,
        )
        if not lots:
            return {
                "ok": False,
                "code": "lot_not_found",
                "serial_not_found": True,
                "message": f"Charge {serial_clean} ist fuer dieses Produkt in Odoo nicht vorhanden.",
            }
        if len(lots) > 1:
            return {
                "ok": False,
                "code": "lot_ambiguous",
                "serial_not_found": True,
                "message": f"Charge {serial_clean} ist in Odoo mehrfach vorhanden. Bitte pruefen.",
            }
        lot_id = lots[0].get("id")
        if existing_lot_id is not None and int(existing_lot_id) != int(lot_id):
            return {
                "ok": False,
                "code": "lot_mismatch",
                "serial_mismatch": True,
                "message": "Die gescannte Charge passt nicht zur reservierten Position.",
            }
        if location_id is not None:
            quants = await odoo.search_read(
                "stock.quant",
                [("product_id", "=", product_id), ("lot_id", "=", lot_id), ("location_id", "=", location_id)],
                ["quantity", "reserved_quantity", "location_id"],
                limit=20,
            )
            required_quantity = max(_quantity_as_float(quantity), 1.0)
            has_stock = _has_required_stock(
                quants,
                required_quantity=required_quantity,
                include_reserved=existing_lot_id is not None,
            )
            if not has_stock:
                return {
                    "ok": False,
                    "code": "lot_not_available",
                    "serial_not_available": True,
                    "message": (
                        f"Charge {serial_clean} ist am aktuellen Lagerplatz nicht in "
                        f"ausreichender Menge verfuegbar."
                    ),
                }
        return {
            "ok": True,
            "values": {"lot_id": lot_id},
            "recorded_serial": serial_clean,
        }

    if tracking != "serial":
        return {"ok": True, "values": {}, "recorded_serial": ""}

    if not serial_clean:
        return {
            "ok": False,
            "code": "serial_required",
            "serial_required": True,
            "message": "Seriennummer erforderlich: Bitte das konkrete Exemplar scannen.",
        }

    if not isclose(_quantity_as_float(quantity), 1.0):
        return {
            "ok": False,
            "code": "serial_quantity_mismatch",
            "serial_quantity_mismatch": True,
            "message": "Serialisierte Produkte muessen einzeln mit genau einer Seriennummer bestaetigt werden.",
        }

    if not product_id:
        return {
            "ok": False,
            "code": "serial_product_missing",
            "serial_not_found": True,
            "message": "Seriennummer kann nicht validiert werden: Produkt fehlt an der Position.",
        }

    lots = await odoo.search_read(
        "stock.lot",
        [("product_id", "=", product_id), ("name", "=", serial_clean)],
        ["id", "name", "product_id"],
        limit=2,
    )
    if not lots:
        return {
            "ok": False,
            "code": "serial_not_found",
            "serial_not_found": True,
            "message": f"Seriennummer {serial_clean} ist fuer dieses Produkt in Odoo nicht vorhanden.",
        }
    if len(lots) > 1:
        return {
            "ok": False,
            "code": "serial_ambiguous",
            "serial_not_found": True,
            "message": f"Seriennummer {serial_clean} ist in Odoo mehrfach vorhanden. Bitte pruefen.",
        }

    lot_id = lots[0].get("id")
    if existing_lot_id is not None and int(existing_lot_id) != int(lot_id):
        return {
            "ok": False,
            "code": "serial_mismatch",
            "serial_mismatch": True,
            "message": "Die gescannte Seriennummer passt nicht zur reservierten Position.",
        }

    if location_id is not None:
        quants = await odoo.search_read(
            "stock.quant",
            [("product_id", "=", product_id), ("lot_id", "=", lot_id), ("location_id", "=", location_id)],
            ["quantity", "reserved_quantity", "location_id"],
            limit=20,
        )
        has_stock = _has_required_stock(
            quants,
            required_quantity=1.0,
            include_reserved=existing_lot_id is not None,
        )
        if not has_stock:
            return {
                "ok": False,
                "code": "serial_not_available",
                "serial_not_available": True,
                "message": f"Seriennummer {serial_clean} ist am aktuellen Lagerplatz nicht verfuegbar.",
            }

    return {
        "ok": True,
        "values": {"lot_id": lot_id},
        "recorded_serial": serial_clean,
    }
