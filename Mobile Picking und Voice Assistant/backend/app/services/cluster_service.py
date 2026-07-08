"""
Cluster-/Batch-Picking — mehrere stock.picking gebuendelt in einem Rundgang.

Odoo 18/19: echter stock.picking.batch (action_confirm / action_done).
Box-Zuordnung: jedes Picking erhaelt eine logische Box-Nummer/-Farbe UND ein echtes,
wiederverwendbares Ziel-Package, das als result_package_id auf allen Move-Lines des
Pickings gesetzt wird (Box N <-> Order N <-> 1 Package). Beim
action_done landen die Waren physisch in diesem Package - das definierende Merkmal des
Cluster-Pickings laut Odoo-Doku.
picking_service.py bleibt unberuehrt; Route-Sort wird wiederverwendet.

Verifizierte Odoo-18-Fakten siehe docs/superpowers/specs/2026-06-23-odoo18-batch-api-facts.md.
Odoo 19 nutzt fuer Packages ``stock.package`` statt ``stock.quant.package``.
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
from app.services.serial_validation import build_serial_move_line_values

logger = logging.getLogger(__name__)

# Farbtokens passend zum PWA-Designsystem (Akzent-Palette, zyklisch).
BOX_PALETTE: list[str] = ["#A299FF", "#FF8A7E", "#6FD3C7", "#F4C77B", "#7EA8FF", "#C58BFF"]
PACKAGE_MODEL_ODOO19 = "stock.package"
PACKAGE_MODEL_LEGACY = "stock.quant.package"
PACKAGE_MODEL_CANDIDATES = (PACKAGE_MODEL_ODOO19, PACKAGE_MODEL_LEGACY)
CLUSTER_MIN_ORDERS = 2
CLUSTER_RECOMMENDED_MIN_ORDERS = 4
CLUSTER_MAX_ORDERS = 8


def assign_boxes(picking_ids: list[int]) -> dict[int, dict[str, Any]]:
    """Deterministische Box-Nummer + Farbe je Picking (1-based, nach picking_id sortiert)."""
    box_map: dict[int, dict[str, Any]] = {}
    for index, picking_id in enumerate(sorted(set(picking_ids))):
        box_map[picking_id] = {
            "box_index": index + 1,
            "box_color": BOX_PALETTE[index % len(BOX_PALETTE)],
        }
    return box_map


def validate_cluster_capacity(picking_ids: list[int]) -> dict[str, Any]:
    unique_ids = sorted({int(pid) for pid in (picking_ids or [])})
    count = len(unique_ids)
    if count < CLUSTER_MIN_ORDERS:
        return {
            "ok": False,
            "code": "cluster_capacity",
            "message": f"Cluster braucht mindestens {CLUSTER_MIN_ORDERS} Auftraege.",
            "picking_ids": unique_ids,
        }
    if count > CLUSTER_MAX_ORDERS:
        return {
            "ok": False,
            "code": "cluster_capacity",
            "message": f"Cluster erlaubt maximal {CLUSTER_MAX_ORDERS} Auftraege pro Wagen.",
            "picking_ids": unique_ids,
        }
    return {"ok": True, "picking_ids": unique_ids, "count": count}


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


def _many2one_id(value: Any) -> int | None:
    if isinstance(value, (list, tuple)) and value:
        candidate = value[0]
        return candidate if isinstance(candidate, int) and not isinstance(candidate, bool) else None
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    return None


def _many2one_name(value: Any) -> str:
    if isinstance(value, (list, tuple)) and len(value) > 1:
        return str(value[1] or "").strip()
    return ""


def _date_key(value: Any) -> str:
    raw = str(value or "").strip()
    return raw[:10] if len(raw) >= 10 else ""


def _clean_product_name(display_name: str) -> str:
    """Odoo-'[ref] '-Prefix aus dem Produktnamen entfernen."""
    return re.sub(r"^\[.*?\]\s*", "", display_name or "")


def _line_is_picked(raw_line: dict[str, Any], move: dict[str, Any]) -> bool:
    if "picked" in raw_line:
        return bool(raw_line.get("picked"))
    return bool(move.get("picked"))


def _is_missing_batch_field_error(exc: OdooAPIError) -> bool:
    message = str(exc)
    return (
        "Invalid field" in message
        and "stock.picking" in message
        and "batch_id" in message
    )


def _cluster_candidates_from_pickings(
    pickings: list[dict[str, Any]],
    lines: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    lines_by_picking: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for line in lines:
        picking_id = _many2one_id(line.get("picking_id"))
        if picking_id is not None:
            lines_by_picking[picking_id].append(line)

    candidates: list[dict[str, Any]] = []
    for picking in pickings:
        picking_id = int(picking["id"])
        picking_lines = lines_by_picking.get(picking_id, [])
        first_location = ""
        product_ids: set[int] = set()
        for line in picking_lines:
            if not first_location:
                first_location = _many2one_name(line.get("location_id"))
            product_id = _many2one_id(line.get("product_id"))
            if product_id is not None:
                product_ids.add(product_id)
        candidates.append({
            "id": picking_id,
            "name": picking.get("name") or "",
            "company_id": _many2one_id(picking.get("company_id")),
            "delivery_date": _date_key(picking.get("date_deadline") or picking.get("scheduled_date")),
            "partner_name": _many2one_name(picking.get("partner_id")),
            "primary_zone": _zone_of(first_location),
            "product_ids": sorted(product_ids),
            "line_count": len(picking_lines),
        })
    return candidates


def build_cluster_rule_report(candidates: list[dict[str, Any]]) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []
    reasons: list[str] = []

    capacity = validate_cluster_capacity([c["id"] for c in candidates])
    if not capacity["ok"]:
        errors.append(capacity["code"])

    companies = {c.get("company_id") for c in candidates if c.get("company_id") is not None}
    if len(companies) > 1:
        errors.append("mixed_company")

    delivery_dates = {c.get("delivery_date") for c in candidates if c.get("delivery_date")}
    if len(delivery_dates) > 1:
        errors.append("mixed_delivery_date")

    product_sets = [set(c.get("product_ids", [])) for c in candidates]
    overlap = set.intersection(*product_sets) if product_sets and all(product_sets) else set()
    if len(candidates) > 1 and not overlap:
        errors.append("no_product_overlap")

    zones = [c.get("primary_zone") for c in candidates if c.get("primary_zone")]
    if len(set(zones)) == 1 and zones:
        reasons.append(f"Zone {zones[0]}")
    if delivery_dates:
        reasons.append(f"Ausliefertag {sorted(delivery_dates)[0]}")
    if overlap:
        reasons.append(f"{len(overlap)} gemeinsame Produkte")

    score = 0
    if not errors:
        score += 40
    if delivery_dates:
        score += 20
    if zones and len(set(zones)) == 1:
        score += 20
    score += min(20, len(overlap) * 5)

    count = len(candidates)
    if CLUSTER_MIN_ORDERS <= count < CLUSTER_RECOMMENDED_MIN_ORDERS:
        warnings.append(
            f"{count} Auftraege sind gueltig, empfohlen sind "
            f"{CLUSTER_RECOMMENDED_MIN_ORDERS}-{CLUSTER_MAX_ORDERS}."
        )

    return {
        "eligible": not errors,
        "errors": errors,
        "warnings": warnings,
        "reasons": reasons,
        "score": min(score, 100),
        "product_overlap_count": len(overlap),
        "delivery_date": sorted(delivery_dates)[0] if len(delivery_dates) == 1 else "",
    }


class ClusterService:
    def __init__(self, odoo, n8n):
        self._odoo = odoo
        self._n8n = n8n
        self._package_model_name: str | None = None

    async def suggest_batches(self, picker_identity=None) -> list[dict[str, Any]]:
        """Offene assigned-Pickings ohne Batch nach Lagerzone gruppieren."""
        try:
            try:
                pickings = await self._odoo.search_read(
                    "stock.picking",
                    [("state", "=", "assigned"), ("batch_id", "=", False)],
                    ["name", "batch_id", "company_id", "scheduled_date", "date_deadline", "partner_id"],
                    limit=100,
                )
            except OdooAPIError as exc:
                if not _is_missing_batch_field_error(exc):
                    raise
                logger.warning(
                    "suggest_batches: stock.picking.batch_id nicht verfuegbar; keine Cluster-Vorschlaege: %s",
                    exc,
                )
                return []
            if not pickings:
                return []

            picking_ids = [p["id"] for p in pickings]
            name_by_id = {p["id"]: p["name"] for p in pickings}
            lines = await self._odoo.search_read(
                "stock.move.line",
                [("picking_id", "in", picking_ids)],
                ["picking_id", "location_id", "product_id"],
                limit=max(500, len(picking_ids) * 20),
            )
        except OdooAPIError as exc:
            # #14: Sichtbares Service-Logging statt stiller 500er-Propagation.
            logger.error("suggest_batches: Odoo-Abfrage fehlgeschlagen: %s", exc)
            raise

        candidates = _cluster_candidates_from_pickings(pickings, lines)
        groups: dict[tuple[str, str], dict[str, Any]] = defaultdict(
            lambda: {"candidates": [], "line_count": 0}
        )
        for candidate in candidates:
            key = (candidate.get("delivery_date") or "", candidate.get("primary_zone") or "Unbekannt")
            groups[key]["candidates"].append(candidate)
            groups[key]["line_count"] += candidate.get("line_count", 0)

        result = []
        for (_delivery_date, zone), data in groups.items():
            grouped_candidates = data["candidates"]
            report = build_cluster_rule_report(grouped_candidates)
            if not report["eligible"]:
                continue
            pids = sorted(candidate["id"] for candidate in grouped_candidates)
            result.append(
                {
                    "zone": zone,
                    "delivery_date": report["delivery_date"],
                    "picking_ids": pids,
                    "order_count": len(pids),
                    "line_count": data["line_count"],
                    "picking_names": [name_by_id[p] for p in pids],
                    "score": report["score"],
                    "reasons": report["reasons"],
                    "warnings": report["warnings"],
                    "product_overlap_count": report["product_overlap_count"],
                }
            )
        result.sort(key=lambda g: (-g["score"], -g["order_count"], g["zone"]))
        return result

    async def create_batch(self, picking_ids, picker_identity=None) -> dict[str, Any]:
        """Echten stock.picking.batch anlegen und bestaetigen (draft -> in_progress)."""
        if not picking_ids:
            raise ValueError("picking_ids darf nicht leer sein")
        capacity = validate_cluster_capacity(picking_ids)
        if not capacity["ok"]:
            return {
                "success": False,
                "error": capacity["message"],
                "message": capacity["message"],
                "code": capacity["code"],
            }
        ids = capacity["picking_ids"]

        # IDOR-/State-Schutz: nur eigene-faehige Pickings zulassen - assigned und
        # noch keinem Batch zugeordnet (analog suggest_batches). picking_ids=[(6,0,..)]
        # ist ein REPLACE, daher duerfen NUR gescopte IDs in die vals.
        try:
            allowed = await self._odoo.search_read(
                "stock.picking",
                [("id", "in", ids), ("state", "=", "assigned"), ("batch_id", "=", False)],
                ["id", "name", "company_id", "scheduled_date", "date_deadline", "partner_id", "batch_id"],
                limit=len(ids),
            )
        except OdooAPIError as exc:
            if not _is_missing_batch_field_error(exc):
                logger.error("create_batch: Picking-Scope-Abfrage fehlgeschlagen: %s", exc)
                return {"error": f"Batch-Scope-Abfrage fehlgeschlagen: {exc}"}
            logger.error("create_batch: stock_picking_batch nicht verfuegbar: %s", exc)
            return {
                "success": False,
                "error": "Cluster-Picking ist in dieser Odoo-Instanz nicht verfuegbar.",
                "message": "Cluster-Picking ist in dieser Odoo-Instanz nicht verfuegbar.",
                "code": "stock_picking_batch_unavailable",
                "unavailable": True,
            }
        allowed_ids = [p["id"] for p in allowed]
        if not allowed_ids:
            return {"error": "Keine gueltigen Pickings fuer diesen Batch.", "forbidden": True}
        allowed_capacity = validate_cluster_capacity(allowed_ids)
        if not allowed_capacity["ok"]:
            return {
                "success": False,
                "error": allowed_capacity["message"],
                "message": allowed_capacity["message"],
                "code": allowed_capacity["code"],
            }
        allowed_ids = allowed_capacity["picking_ids"]

        candidate_lines = await self._odoo.search_read(
            "stock.move.line",
            [("picking_id", "in", allowed_ids)],
            ["picking_id", "location_id", "product_id"],
            limit=max(500, len(allowed_ids) * 20),
        )
        candidates = _cluster_candidates_from_pickings(allowed, candidate_lines)
        report = build_cluster_rule_report(candidates)
        if not report["eligible"]:
            code = report["errors"][0]
            messages = {
                "mixed_company": "Cluster darf keine Pickings aus mehreren Companies enthalten.",
                "mixed_delivery_date": "Cluster-Pickings brauchen denselben Ausliefertag.",
                "no_product_overlap": "Cluster braucht Produktueberlappung zwischen den Auftraegen.",
                "cluster_capacity": f"Cluster braucht mindestens {CLUSTER_MIN_ORDERS} Auftraege.",
            }
            message = messages.get(code, "Cluster-Auswahl ist fachlich nicht gueltig.")
            return {
                "success": False,
                "error": message,
                "message": message,
                "code": code,
                "eligibility": report,
            }

        company_id = None
        for picking in allowed:
            if picking.get("company_id"):
                company_id = picking["company_id"][0]
                break

        # 'name' bewusst weglassen -> Odoo-Sequenz 'picking.batch' fuellt es.
        vals: dict[str, Any] = {"picking_ids": [(6, 0, allowed_ids)]}
        if company_id is not None:
            vals["company_id"] = company_id
        if picker_identity and getattr(picker_identity, "user_id", None):
            vals["user_id"] = picker_identity.user_id

        try:
            batch_id = await self._odoo.create("stock.picking.batch", vals)
        except OdooAPIError as exc:
            logger.error("create_batch: Anlegen fehlgeschlagen: %s", exc)
            return {"error": f"Batch-Anlage fehlgeschlagen: {exc}"}

        try:
            await self._odoo.call_method("stock.picking.batch", "action_confirm", [batch_id])
        except OdooAPIError as exc:
            logger.error("create_batch: action_confirm fehlgeschlagen (batch %s): %s",
                         batch_id, exc)
            # Kompensieren: keinen verwaisten Draft-Batch hinterlassen.
            try:
                await self._odoo.call_method(
                    "stock.picking.batch", "action_cancel", [batch_id])
            except OdooAPIError as cancel_exc:
                logger.error("create_batch: kompensierendes action_cancel fehlgeschlagen "
                             "(batch %s): %s", batch_id, cancel_exc)
            return {"error": f"Batch-Bestaetigung fehlgeschlagen: {exc}"}

        # Ziel-Packages je Picking anlegen (Box N <-> Order N <-> 1 Package) und als
        # result_package_id auf die Move-Lines schreiben. Best-effort: ein Package-Glitch
        # darf den (bereits bestaetigten) Batch nie zerstoeren - daher hier KEIN
        # action_cancel und KEIN raise, nur loggen und weitermachen.
        try:
            await self._assign_packages(allowed_ids)
        except Exception as exc:  # noqa: BLE001 - best-effort: bestaetigter Batch muss ueberleben
            logger.error("create_batch: Package-Zuweisung fehlgeschlagen (batch %s): %s",
                         batch_id, exc)

        return await self.get_batch(batch_id, picker_identity=picker_identity)

    async def _assign_packages(self, allowed_ids: list[int]) -> None:
        """Je Picking ein Ziel-Package anlegen und als result_package_id schreiben.

        Odoo 19 nennt das Modell ``stock.package``; Odoo 18 verwendet
        ``stock.quant.package`` mit ``package_use``. Die Reihenfolge bleibt stabil
        ueber box_index.
        """
        box_map = assign_boxes(allowed_ids)
        pickings = await self._odoo.search_read(
            "stock.picking", [("id", "in", allowed_ids)], ["name"],
            limit=len(allowed_ids) or 1,
        )
        name_by_picking = {p["id"]: p["name"] for p in pickings}

        lines = await self._odoo.search_read(
            "stock.move.line", [("picking_id", "in", allowed_ids)], ["id", "picking_id"],
            limit=max(500, len(allowed_ids) * 20),
        )
        line_ids_by_picking: dict[int, list[int]] = defaultdict(list)
        for line in lines:
            picking_id = line["picking_id"][0] if line.get("picking_id") else None
            if picking_id is not None:
                line_ids_by_picking[picking_id].append(line["id"])

        for picking_id in sorted(allowed_ids, key=lambda pid: box_map[pid]["box_index"]):
            line_ids = line_ids_by_picking.get(picking_id)
            if not line_ids:
                continue
            box_index = box_map[picking_id]["box_index"]
            picking_name = name_by_picking.get(picking_id) or f"P{picking_id}"
            package_id = await self._create_cluster_package(
                f"CLUSTER-B{box_index}/{picking_name}")
            await self._odoo.write(
                "stock.move.line", line_ids, {"result_package_id": package_id})

    async def _resolve_package_model(self) -> str:
        if self._package_model_name:
            return self._package_model_name

        try:
            records = await self._odoo.search_read(
                "ir.model",
                [("model", "in", list(PACKAGE_MODEL_CANDIDATES))],
                ["model"],
                limit=len(PACKAGE_MODEL_CANDIDATES),
            )
        except OdooAPIError as exc:
            logger.warning("Package-Modell konnte nicht ueber ir.model gelesen werden: %s", exc)
            self._package_model_name = PACKAGE_MODEL_LEGACY
            return self._package_model_name

        available = {record.get("model") for record in records}
        if PACKAGE_MODEL_ODOO19 in available:
            self._package_model_name = PACKAGE_MODEL_ODOO19
        elif PACKAGE_MODEL_LEGACY in available:
            self._package_model_name = PACKAGE_MODEL_LEGACY
        else:
            logger.warning("Kein bekanntes Odoo-Package-Modell gefunden; nutze Legacy-Fallback.")
            self._package_model_name = PACKAGE_MODEL_LEGACY
        return self._package_model_name

    @staticmethod
    def _package_create_values(model: str, name: str) -> dict[str, Any]:
        vals: dict[str, Any] = {"name": name}
        if model == PACKAGE_MODEL_LEGACY:
            vals["package_use"] = "reusable"
        return vals

    async def _create_cluster_package(self, name: str) -> int:
        primary = await self._resolve_package_model()
        candidates = [primary] + [m for m in PACKAGE_MODEL_CANDIDATES if m != primary]
        last_error: OdooAPIError | None = None

        for model in candidates:
            try:
                package_id = await self._odoo.create(
                    model, self._package_create_values(model, name))
            except OdooAPIError as exc:
                last_error = exc
                logger.warning("Package-Anlage ueber %s fehlgeschlagen: %s", model, exc)
                continue

            self._package_model_name = model
            return package_id

        raise last_error or OdooAPIError("Kein Odoo-Package-Modell verfuegbar")

    @staticmethod
    def _owner_id(batch: dict[str, Any]) -> int | None:
        owner = batch.get("user_id")
        return owner[0] if isinstance(owner, list) else owner

    @staticmethod
    def _carton_matches(scanned: str, package_id: int, package_name: str | None) -> bool:
        """True, wenn der bestaetigte Karton dem Ziel-Package entspricht.

        Akzeptiert den Package-Namen (case-insensitiv, getrimmt) ODER die
        Package-ID als String (z. B. wenn die PWA per Tippen die ID sendet).
        """
        s = (scanned or "").strip().lower()
        if not s:
            return False
        if package_name and s == package_name.strip().lower():
            return True
        return s == str(package_id)

    def _is_authorized(self, batch: dict[str, Any], picker_identity) -> bool:
        """Fail-closed Zugriffsregel fuer einen Batch.

        Ein Zugriff erfordert (1) einen bekannten Picker und (2) - falls der Batch
        einem Picker zugewiesen ist - dass es derselbe ist. Fehlt der Picker oder
        passt der Owner nicht, wird der Zugriff verweigert (kein fail-open ueber
        unbekannte Identitaet oder ownerlose Batches).
        """
        requester_id = getattr(picker_identity, "user_id", None) if picker_identity else None
        if requester_id is None:
            return False
        owner_id = self._owner_id(batch)
        if owner_id is None:
            return False
        return owner_id == requester_id

    async def get_batch(self, batch_id: int, picker_identity=None) -> dict[str, Any]:
        """Batch mit gemergter, route-sortierter Sammelliste + Box-Tags + Fortschritt."""
        batches = await self._odoo.search_read(
            "stock.picking.batch", [("id", "=", batch_id)],
            ["name", "state", "picking_ids", "user_id"], limit=1,
        )
        if not batches:
            return {"error": "Batch nicht gefunden"}

        batch = batches[0]
        # Fail-closed Ownership-Gate (Paritaet zu confirm_cluster_line/validate_batch).
        if not self._is_authorized(batch, picker_identity):
            return {"error": "Kein Zugriff auf diesen Batch.", "forbidden": True}

        picking_ids = batch.get("picking_ids", []) or []
        pickings = await self._odoo.search_read(
            "stock.picking", [("id", "in", picking_ids)], ["name"],
            limit=len(picking_ids) or 1,
        ) if picking_ids else []
        name_by_picking = {p["id"]: p["name"] for p in pickings}
        box_map = assign_boxes(picking_ids)

        raw_lines = await self._odoo.search_read(
            "stock.move.line", [("picking_id", "in", picking_ids)],
            ["picking_id", "product_id", "quantity", "move_id", "location_id",
             "picked", "result_package_id"],
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
        # Ziel-Package je Picking (alle Lines eines Pickings teilen ein Package).
        package_by_picking: dict[int, dict[str, Any]] = {}
        for raw in raw_lines:
            picking_id = raw["picking_id"][0] if raw.get("picking_id") else None
            move = move_map.get(raw["move_id"][0] if raw.get("move_id") else None, {})
            product_id = raw["product_id"][0] if raw.get("product_id") else None
            product = product_map.get(product_id, {})
            picked = _line_is_picked(raw, move)
            location = raw["location_id"][1] if raw.get("location_id") else ""
            loc_parts = [part.strip() for part in location.split("/") if part.strip()]
            # result_package_id ist [id, name] oder False (fehlt -> None, abwaertskompatibel).
            result_package = raw.get("result_package_id")
            package_id = result_package[0] if result_package else None
            package_name = result_package[1] if result_package else None
            if picking_id is not None and package_id is not None:
                package_by_picking.setdefault(
                    picking_id, {"package_id": package_id, "package_name": package_name})
            lines_by_picking[picking_id].append({
                "id": raw["id"],
                "product_id": product_id,
                "product_name": _clean_product_name(raw["product_id"][1]) if raw.get("product_id") else "",
                "product_barcode": product.get("barcode"),
                "product_sku": product.get("default_code") or "",
                "tracking": product.get("tracking"),
                "quantity_demand": move.get("product_uom_qty", raw.get("quantity", 0)),
                "quantity_done": raw.get("quantity", 0) if picked else 0,
                "picked": picked,
                "location_src": location,
                "location_src_short": loc_parts[-1] if loc_parts else location,
                "package_id": package_id,
                "package_name": package_name,
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
                 "box_index": box_map[pid]["box_index"], "box_color": box_map[pid]["box_color"],
                 "package_id": package_by_picking.get(pid, {}).get("package_id"),
                 "package_name": package_by_picking.get(pid, {}).get("package_name")}
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
        scanned_barcode="", quantity=0, serial_number="", scanned_package="",
        picker_identity=None,
    ) -> dict[str, Any]:
        """Position bestaetigen: Menge (+ optional Serial) schreiben, OHNE Validierung.

        Anders als confirm_pick_line wird hier KEIN button_validate ausgeloest -
        der ganze Batch wird spaeter gesammelt via validate_batch abgeschlossen.

        Empfaengerkarton-Bestaetigung (Put-to-Box / Verwechslungsschutz): hat die
        Move-Line ein Ziel-Package (``result_package_id``, der Cluster-Normalfall),
        muss ``scanned_package`` den richtigen Karton treffen (Name ODER Package-ID).
        Fehlt die Bestaetigung -> ``carton_required``; falscher Karton -> ``wrong_package``;
        in beiden Faellen wird NICHTS geschrieben. Lines ohne Ziel-Package bleiben
        rueckwaertskompatibel ohne Karton-Zwang.
        """
        t0 = time.monotonic()
        # IDOR-Schutz + Ownership-Gate in EINER Query: die Move-Line MUSS zu picking_id
        # gehoeren, dieses Picking zum batch_id, und der Batch dem anfragenden Picker.
        # Der Owner-Filter ist unbedingt (fail-closed, siehe Guard unten). Sonst koennte
        # ein Client eine fremde move_line_id einschleusen oder fremd schreiben.
        requester_id = getattr(picker_identity, "user_id", None) if picker_identity else None
        # #10: Fail-closed wie _is_authorized - ohne bekannten Picker kein Schreibzugriff.
        if requester_id is None:
            self._emit_cluster_confirm(False, batch_id, picking_id, move_line_id, None, False, t0)
            return {"success": False,
                    "message": "Kein Zugriff auf diesen Batch.",
                    "forbidden": True,
                    "progress": None}
        domain = [
            ("id", "=", move_line_id),
            ("picking_id", "=", picking_id),
            ("picking_id.batch_id", "=", batch_id),
            ("picking_id.batch_id.user_id", "=", requester_id),
        ]
        lines = await self._odoo.search_read(
            "stock.move.line",
            domain,
            ["id", "product_id", "quantity", "move_id", "location_id",
             "result_package_id", "lot_id"],
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
        location_id = line["location_id"][0] if line.get("location_id") else None
        existing_lot_id = line["lot_id"][0] if line.get("lot_id") else None

        # #9: product.product nur EINMAL lesen (barcode + tracking) und fuer beide
        # Checks (Barcode-Match und Serial/Tracking) wiederverwenden.
        product: dict[str, Any] = {}
        if product_id:
            products = await self._odoo.search_read(
                "product.product", [("id", "=", product_id)], ["barcode", "tracking"])
            product = products[0] if products else {}

        if product_id and scanned_barcode:
            expected = product.get("barcode")
            if expected and scanned_barcode != expected:
                self._emit_cluster_confirm(False, batch_id, picking_id, move_line_id, product_id, False, t0)
                return {"success": False, "message": f"Falscher Artikel. Erwartet: {expected}",
                        "progress": None}

        # Empfaengerkarton-Bestaetigung (Put-to-Box / Verwechslungsschutz, Akzeptanz #3+#4):
        # Hat die Line ein Ziel-Package, muss der bestaetigte Karton passen, sonst KEIN Write.
        expected_pkg = line.get("result_package_id")
        expected_pkg_id = expected_pkg[0] if expected_pkg else None
        expected_pkg_name = expected_pkg[1] if expected_pkg else None
        if expected_pkg_id is not None:
            scanned_carton = (scanned_package or "").strip()
            if not scanned_carton:
                self._emit_cluster_confirm(
                    False, batch_id, picking_id, move_line_id, product_id, False, t0,
                    carton_ok=False)
                return {"success": False, "carton_required": True,
                        "expected_package_name": expected_pkg_name,
                        "message": f"Bitte Empfängerkarton bestätigen: {expected_pkg_name}",
                        "progress": None}
            if not self._carton_matches(scanned_carton, expected_pkg_id, expected_pkg_name):
                self._emit_cluster_confirm(
                    False, batch_id, picking_id, move_line_id, product_id, False, t0,
                    carton_ok=False)
                return {"success": False, "wrong_package": True,
                        "expected_package_name": expected_pkg_name,
                        "message": f"Falscher Karton! Erwartet: {expected_pkg_name}",
                        "progress": None}

        qty = quantity if quantity > 0 else line.get("quantity", 1.0)
        line_values: dict[str, Any] = {"quantity": qty, "picked": True}

        serial_result = await build_serial_move_line_values(
            self._odoo,
            product_id=product_id,
            tracking=product.get("tracking"),
            serial_number=serial_number,
            quantity=qty,
            location_id=location_id,
            existing_lot_id=existing_lot_id,
        )
        if not serial_result["ok"]:
            self._emit_cluster_confirm(False, batch_id, picking_id, move_line_id, product_id, False, t0)
            return {
                "success": False,
                "message": serial_result["message"],
                "progress": None,
                **{k: v for k, v in serial_result.items() if k not in {"ok", "message", "values", "recorded_serial"}},
            }
        line_values.update(serial_result.get("values", {}))
        recorded_serial = serial_result.get("recorded_serial", "")

        # #1: Beide Writes in try/except - bei OdooAPIError kein HTTP 500, sondern
        # Fehler-Telemetrie + success:False (Teil-Write bleibt zwar moeglich, aber
        # der Picker bekommt eine klare Fehlermeldung statt eines 500ers).
        try:
            await self._odoo.write("stock.move.line", [move_line_id], line_values)
        except OdooAPIError as exc:
            logger.error("confirm_cluster_line: Write fehlgeschlagen (batch %s, line %s): %s",
                         batch_id, move_line_id, exc)
            self._emit_cluster_confirm(
                False, batch_id, picking_id, move_line_id, product_id, bool(recorded_serial), t0)
            return {"success": False,
                    "message": f"Bestaetigung fehlgeschlagen: {exc}",
                    "progress": None}

        self._emit_cluster_confirm(
            True, batch_id, picking_id, move_line_id, product_id, bool(recorded_serial), t0)

        # #7: Write ist bereits erfolgreich - der nachgelagerte Progress-Read ist
        # best effort. Schlaegt er fehl, bleibt success:True mit progress:None statt
        # einen 500er zu werfen (sonst Doppel-Confirm-Risiko).
        progress = None
        try:
            batch = await self.get_batch(batch_id, picker_identity=picker_identity)
            progress = batch.get("progress")
        except OdooAPIError as exc:
            logger.error("confirm_cluster_line: Progress-Read fehlgeschlagen (batch %s): %s",
                         batch_id, exc)

        return {"success": True, "message": "Bestätigt.", "recorded_serial": recorded_serial,
                "progress": progress}

    async def validate_batch(self, batch_id, picker_identity=None) -> dict[str, Any]:
        """Ganzen Batch gesammelt abschliessen via action_done (+ n8n-Event)."""
        t0 = time.monotonic()
        # #5: 'state' mitlesen, um einen bereits abgeschlossenen Batch frueh zu erkennen.
        batches = await self._odoo.search_read(
            "stock.picking.batch", [("id", "=", batch_id)],
            ["picking_ids", "user_id", "state"], limit=1)
        if not batches:
            self._emit_batch_validate(False, batch_id, "not_found", t0)
            return {"success": False, "batch_complete": False, "message": "Batch nicht gefunden."}
        batch = batches[0]
        member_ids = batch.get("picking_ids", []) or []

        # Fail-closed Ownership-Gate: nur der zugewiesene Picker darf den Batch
        # (destruktiv) abschliessen; ohne bekannten Picker wird verweigert.
        if not self._is_authorized(batch, picker_identity):
            self._emit_batch_validate(False, batch_id, "auth_denied", t0)
            return {"success": False, "batch_complete": False, "forbidden": True,
                    "message": "Kein Zugriff auf diesen Batch."}

        # #5: Doppel-Tap / Race gegen Button-Disable - bereits abgeschlossen ist idempotent ok.
        if batch.get("state") == "done":
            self._emit_batch_validate(True, batch_id, "already_done", t0)
            return {"success": True, "batch_complete": True,
                    "message": "Batch bereits abgeschlossen."}

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
            logger.error("validate_batch: action_done fehlgeschlagen (batch %s): %s",
                         batch_id, exc)
            self._emit_batch_validate(False, batch_id, "odoo_error", t0)
            return {"success": False, "batch_complete": False,
                    "message": f"Batch-Abschluss fehlgeschlagen: {exc}"}

        # action_done gibt bei offenen Rueckfragen ein Wizard-Action-Dict zurueck.
        if isinstance(result, dict) and result.get("res_model"):
            logger.warning("validate_batch: Wizard erforderlich (batch %s, model %s)",
                           batch_id, result.get("res_model"))
            self._emit_batch_validate(False, batch_id, "wizard", t0)
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
            self._emit_batch_validate(True, batch_id, "success_degraded", t0)
            return {"success": True, "batch_complete": True, "integration_status": "degraded",
                    "integration_error": event.error,
                    "message": "Batch abgeschlossen, n8n-Folgeprozess degradiert."}
        self._emit_batch_validate(True, batch_id, "success", t0)
        return {"success": True, "batch_complete": True, "message": "Batch abgeschlossen."}

    def _emit_cluster_confirm(self, success, batch_id, picking_id, move_line_id,
                              product_id, serial_recorded, t0, carton_ok=True):
        """Strukturiertes cluster_confirm-Telemetrie-Event (analog serial_confirm).

        ``carton_ok`` macht die Verwechslungsschutz-Quote messbar: False markiert
        einen abgewiesenen Confirm wegen fehlendem/falschem Empfaengerkarton.
        """
        logger.info(json.dumps({
            "event_type": "cluster_confirm",
            "batch_id": batch_id,
            "picking_id": picking_id,
            "move_line_id": move_line_id,
            "product_id": product_id,
            "success": success,
            "serial_recorded": serial_recorded,
            "carton_ok": carton_ok,
            "latency_ms": int((time.monotonic() - t0) * 1000),
        }, ensure_ascii=False))

    def _emit_batch_validate(self, success, batch_id, outcome, t0):
        """Strukturiertes batch_validate-Telemetrie-Event (analog cluster_confirm).

        Invariante: validate_batch emittiert genau ein Event pro Aufruf auf JEDEM
        Exit-Pfad (success/wizard/auth_denied/not_found/already_done/odoo_error),
        damit die Batch-Abschluss-Erfolgsrate eine echte Rate ueber alle Versuche ist.
        """
        logger.info(json.dumps({
            "event_type": "batch_validate",
            "batch_id": batch_id,
            "success": success,
            "outcome": outcome,
            "latency_ms": int((time.monotonic() - t0) * 1000),
        }, ensure_ascii=False))
