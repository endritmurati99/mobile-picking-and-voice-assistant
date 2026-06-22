"""Soll/Ist-Abgleich von Seriennummern (Retouren-Prüfung)."""
from collections import Counter
from typing import TypedDict


class ReconcileResult(TypedDict):
    ok: bool
    missing: list[str]
    unknown: list[str]
    duplicates: list[str]


def reconcile_serials(shipped: list[str], returned: list[str]) -> ReconcileResult:
    shipped_counter = Counter(s.strip() for s in shipped if s and s.strip())
    returned_counter = Counter(s.strip() for s in returned if s and s.strip())
    missing = sorted(s for s in shipped_counter if returned_counter[s] == 0)
    unknown = sorted(s for s in returned_counter if shipped_counter[s] == 0)
    # duplicates: serials returned more than once (shipped-side duplicates are out of scope)
    duplicates = sorted(s for s, c in returned_counter.items() if c > 1)
    ok = not missing and not unknown and not duplicates
    return {"ok": ok, "missing": missing, "unknown": unknown, "duplicates": duplicates}
