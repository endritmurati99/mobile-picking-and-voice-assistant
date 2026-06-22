from app.utils.serial import reconcile_serials


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
