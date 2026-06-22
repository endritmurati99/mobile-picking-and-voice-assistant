"""Soll/Ist-Abgleich von Seriennummern (Retouren-Prüfung)."""
from collections import Counter


def reconcile_serials(shipped: list[str], returned: list[str]) -> dict:
    shipped_counter = Counter(s.strip() for s in shipped if s and s.strip())
    returned_counter = Counter(s.strip() for s in returned if s and s.strip())
    missing = sorted(s for s in shipped_counter if returned_counter[s] == 0)
    unknown = sorted(s for s in returned_counter if shipped_counter[s] == 0)
    duplicates = sorted(s for s, c in returned_counter.items() if c > 1)
    ok = not missing and not unknown and not duplicates
    return {"ok": ok, "missing": missing, "unknown": unknown, "duplicates": duplicates}
