"""
Cluster-/Batch-Picking — mehrere stock.picking gebuendelt in einem Rundgang.

Odoo 18: echter stock.picking.batch (action_confirm / action_done).
Box-Zuordnung: jedes Picking erhaelt eine logische Box-Nummer/-Farbe UND ein echtes,
wiederverwendbares stock.quant.package, das als result_package_id (Ziel-Package) auf
allen Move-Lines des Pickings gesetzt wird (Box N <-> Order N <-> 1 Package). Beim
action_done landen die Waren physisch in diesem Package - das definierende Merkmal des
Cluster-Pickings laut Odoo-Doku.
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
        try:
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
        except OdooAPIError as exc:
            # #14: Sichtbares Service-Logging statt stiller 500er-Propagation.
            logger.error("suggest_batches: Odoo-Abfrage fehlgeschlagen: %s", exc)
            raise

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

        # IDOR-/State-Schutz: nur eigene-faehige Pickings zulassen - assigned und
        # noch keinem Batch zugeordnet (analog suggest_batches). picking_ids=[(6,0,..)]
        # ist ein REPLACE, daher duerfen NUR gescopte IDs in die vals.
        allowed = await self._odoo.search_read(
            "stock.picking",
            [("id", "in", ids), ("state", "=", "assigned"), ("batch_id", "=", False)],
            ["id", "company_id"],
            limit=len(ids),
        )
        allowed_ids = [p["id"] for p in allowed]
        if not allowed_ids:
            return {"error": "Keine gueltigen Pickings fuer diesen Batch.", "forbidden": True}

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
        except OdooAPIError as exc:
            logger.error("create_batch: Package-Zuweisung fehlgeschlagen (batch %s): %s",
                         batch_id, exc)

        return await self.get_batch(batch_id, picker_identity=picker_identity)

    async def _assign_packages(self, allowed_ids: list[int]) -> None:
        """Je Picking ein reusable stock.quant.package anlegen und als result_package_id
        auf dessen Move-Lines schreiben. Stabile Reihenfolge ueber box_index."""
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
            package_id = await self._odoo.create(
                "stock.quant.package",
                {"name": f"CLUSTER-B{box_index}/{picking_name}", "package_use": "reusable"},
            )
            await self._odoo.write(
                "stock.move.line", line_ids, {"result_package_id": package_id})

    @staticmethod
    def _owner_id(batch: dict[str, Any]) -> int | None:
        owner = batch.get("user_id")
        return owner[0] if isinstance(owner, list) else owner

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
        if owner_id is not None and owner_id != requester_id:
            return False
        return True

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
             "result_package_id"],
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
                "quantity_done": raw.get("quantity", 0) if move.get("picked") else 0,
                "picked": bool(move.get("picked")),
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
        scanned_barcode="", quantity=0, serial_number="", picker_identity=None,
    ) -> dict[str, Any]:
        """Position bestaetigen: Menge (+ optional Serial) schreiben, OHNE Validierung.

        Anders als confirm_pick_line wird hier KEIN button_validate ausgeloest -
        der ganze Batch wird spaeter gesammelt via validate_batch abgeschlossen.
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

        # #9: product.product nur EINMAL lesen (barcode + tracking) und fuer beide
        # Checks (Barcode-Match und Serial/Tracking) wiederverwenden.
        product: dict[str, Any] = {}
        if product_id and (scanned_barcode or (serial_number or "").strip()):
            products = await self._odoo.search_read(
                "product.product", [("id", "=", product_id)], ["barcode", "tracking"])
            product = products[0] if products else {}

        if product_id and scanned_barcode:
            expected = product.get("barcode")
            if expected and scanned_barcode != expected:
                self._emit_cluster_confirm(False, batch_id, picking_id, move_line_id, product_id, False, t0)
                return {"success": False, "message": f"Falscher Artikel. Erwartet: {expected}",
                        "progress": None}

        qty = quantity if quantity > 0 else line.get("quantity", 1.0)
        line_values: dict[str, Any] = {"quantity": qty}

        recorded_serial = ""
        serial_clean = (serial_number or "").strip()
        if serial_clean and product_id and product.get("tracking") in ("serial", "lot"):
            line_values["lot_name"] = serial_clean
            recorded_serial = serial_clean

        # #1: Beide Writes in try/except - bei OdooAPIError kein HTTP 500, sondern
        # Fehler-Telemetrie + success:False (Teil-Write bleibt zwar moeglich, aber
        # der Picker bekommt eine klare Fehlermeldung statt eines 500ers).
        try:
            await self._odoo.write("stock.move.line", [move_line_id], line_values)
            if move_id:
                await self._odoo.write("stock.move", [move_id], {"picked": True})
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
