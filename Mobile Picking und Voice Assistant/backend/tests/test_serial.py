from app.utils.serial import reconcile_serials
from app.services.serial_validation import build_serial_move_line_values


def test_reconcile_detects_missing_unknown_and_duplicates():
    # Versendet 1,2,3,4 — zurück kommt 1,5,5 (Prof-Beispiel CPU)
    result = reconcile_serials(["1", "2", "3", "4"], ["1", "5", "5"])
    assert result == {
        "ok": False,
        "missing": ["2", "3", "4"],
        "unknown": ["5"],
        "duplicates": ["5"],
    }


def test_reconcile_ok_when_identical():
    result = reconcile_serials(["A1", "A2"], ["A2", "A1"])
    assert result == {"ok": True, "missing": [], "unknown": [], "duplicates": []}


def test_reconcile_empty_inputs():
    assert reconcile_serials([], []) == {"ok": True, "missing": [], "unknown": [], "duplicates": []}


def test_reconcile_strips_whitespace():
    assert reconcile_serials([" A1 "], ["A1"]) == {"ok": True, "missing": [], "unknown": [], "duplicates": []}


class FakeOdoo:
    def __init__(self, *, quant_quantity=1, reserved_quantity=0):
        self.quant_quantity = quant_quantity
        self.reserved_quantity = reserved_quantity
        self.calls = []

    async def search_read(self, model, domain, fields, limit=None):
        self.calls.append((model, domain, fields, limit))
        if model == "stock.lot":
            lot_name = next(value for field, op, value in domain if field == "name" and op == "=")
            if lot_name == "LOT-1":
                return [{"id": 11, "name": "LOT-1", "product_id": [42, "Produkt"]}]
            return []
        if model == "stock.quant":
            return [{
                "quantity": self.quant_quantity,
                "reserved_quantity": self.reserved_quantity,
                "location_id": [7, "WH/Stock"],
            }]
        return []


def test_lot_tracking_requires_existing_lot_at_source_location():
    import asyncio

    missing = asyncio.run(build_serial_move_line_values(
        FakeOdoo(),
        product_id=42,
        tracking="lot",
        serial_number="",
        quantity=2,
        location_id=7,
    ))
    assert missing["ok"] is False
    assert missing["code"] == "lot_required"

    unavailable = asyncio.run(build_serial_move_line_values(
        FakeOdoo(quant_quantity=0),
        product_id=42,
        tracking="lot",
        serial_number="LOT-1",
        quantity=2,
        location_id=7,
    ))
    assert unavailable["ok"] is False
    assert unavailable["code"] == "lot_not_available"

    valid = asyncio.run(build_serial_move_line_values(
        FakeOdoo(quant_quantity=2),
        product_id=42,
        tracking="lot",
        serial_number="LOT-1",
        quantity=2,
        location_id=7,
    ))
    assert valid == {
        "ok": True,
        "values": {"lot_id": 11},
        "recorded_serial": "LOT-1",
    }


def test_lot_tracking_rejects_fully_reserved_stock():
    import asyncio

    result = asyncio.run(build_serial_move_line_values(
        FakeOdoo(quant_quantity=1, reserved_quantity=1),
        product_id=42,
        tracking="lot",
        serial_number="LOT-1",
        quantity=1,
        location_id=7,
    ))

    assert result["ok"] is False
    assert result["code"] == "lot_not_available"


def test_lot_tracking_accepts_own_reserved_lot():
    import asyncio

    result = asyncio.run(build_serial_move_line_values(
        FakeOdoo(quant_quantity=1, reserved_quantity=1),
        product_id=42,
        tracking="lot",
        serial_number="LOT-1",
        quantity=1,
        location_id=7,
        existing_lot_id=11,
    ))

    assert result["ok"] is True
    assert result["values"] == {"lot_id": 11}


def test_lot_tracking_rejects_insufficient_available_quantity():
    import asyncio

    result = asyncio.run(build_serial_move_line_values(
        FakeOdoo(quant_quantity=1, reserved_quantity=0),
        product_id=42,
        tracking="lot",
        serial_number="LOT-1",
        quantity=2,
        location_id=7,
    ))

    assert result["ok"] is False
    assert result["code"] == "lot_not_available"


def test_serial_tracking_rejects_fully_reserved_stock():
    import asyncio

    result = asyncio.run(build_serial_move_line_values(
        FakeOdoo(quant_quantity=1, reserved_quantity=1),
        product_id=42,
        tracking="serial",
        serial_number="LOT-1",
        quantity=1,
        location_id=7,
    ))

    assert result["ok"] is False
    assert result["code"] == "serial_not_available"


def test_serial_tracking_accepts_own_reserved_serial():
    import asyncio

    result = asyncio.run(build_serial_move_line_values(
        FakeOdoo(quant_quantity=1, reserved_quantity=1),
        product_id=42,
        tracking="serial",
        serial_number="LOT-1",
        quantity=1,
        location_id=7,
        existing_lot_id=11,
    ))

    assert result["ok"] is True
    assert result["values"] == {"lot_id": 11}
