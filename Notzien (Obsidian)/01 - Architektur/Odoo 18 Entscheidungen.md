---
title: Odoo 18 Entscheidungen
tags:
  - architecture
  - odoo
  - adr
aliases:
  - Odoo ADR
  - Odoo API Entscheidungen
---

# Odoo 18 Entscheidungen (ADR)

> [!abstract] Architecture Decision Records
> Alle technischen Entscheidungen rund um die Odoo-Integration — mit Begründungen.
> Diese Entscheidungen sind bindend und dürfen nur mit expliziter Begründung geändert werden.

Übergeordnete Architektur: [[System Architektur]] | Endpunkt-Details: [[API Dokumentation]] | Überblick: [[00 - Projekt Übersicht]]

---

## ADR-001: JSON-RPC statt XML-RPC

**Status:** Akzeptiert

**Kontext:**
Odoo 18 Community bietet zwei externe APIs: XML-RPC (Legacy) und JSON-RPC. Die PWA-Backend-Kommunikation läuft über `httpx` (async Python-Client).

**Entscheidung:** JSON-RPC über den Endpunkt `/jsonrpc`

**Begründung:**
- `httpx` ist ein async-HTTP-Client — XML-RPC hingegen nutzt `xmlrpc.client` (blockierend)
- JSON-RPC-Antworten sind direkt als Python-Dict verfügbar, kein XML-Parsing
- JSON-RPC unterstützt den gleichen `execute_kw`-Mechanismus wie XML-RPC
- Zukunftssicher: Odoo 19 REST API ist ebenfalls JSON-basiert

> [!warning] Nicht Odoo 19 REST
> Ab Odoo 19 gibt es eine neue Bearer-Token REST API. **Diese existiert in 18.0 Community NICHT.**
> Kein `Authorization: Bearer ...` Header — stattdessen API-Key als Passwort in `execute_kw`.

**Aufruf-Schema:**
```python
POST /jsonrpc
{
  "jsonrpc": "2.0",
  "method": "call",
  "params": {
    "service": "object",
    "method": "execute_kw",
    "args": [db, uid, api_key, model, method, args, kwargs]
  }
}
```

---

## ADR-002: API-Key statt Passwort

**Status:** Akzeptiert

**Kontext:**
Odoo 18 unterstützt API-Keys für externe Clients (Odoo Settings → User → Account Security → API-Keys).

**Entscheidung:** `ODOO_API_KEY` als Credential, nicht das Admin-Passwort

**Begründung:**
- API-Keys sind widerrufbar ohne Passwortänderung
- Separate Keys pro Client möglich (Backend, Seed-Script, etc.)
- Kein Klartext-Admin-Passwort im `.env`
- Odoo 18 akzeptiert API-Key als `password`-Parameter in `authenticate` und als `api_key`-Parameter in `execute_kw`

**Setup:**
1. Odoo → Einstellungen → Benutzer → `admin` → Account Security
2. "Neuen API-Key erstellen" → Wert in `.env` als `ODOO_API_KEY` eintragen
3. Key wird nur einmal angezeigt — sofort sichern!

---

## ADR-003: Odoo 18 Breaking Changes — Feldnamen

**Status:** Akzeptiert (Pflicht, keine Alternative)

> [!danger] Diese Fehler sind schwer zu debuggen
> Odoo gibt keinen Fehler zurück wenn man `qty_done` schreibt — der Wert wird still ignoriert.
> Immer `quantity` verwenden.

| Odoo 16 (falsch) | Odoo 18 (korrekt) | Modell |
| ---------------- | ----------------- | ------ |
| `qty_done` | `quantity` | `stock.move.line` |
| `move_lines` | `move_ids` | `stock.picking` |
| `stock.production.lot` | `stock.lot` | Chargen/Seriennummern |
| `product_uom_qty` | `product_uom_qty` | `stock.move` (unverändert) |

**Implementierungsregel:**
```python
# ✅ Korrekt (Odoo 18)
await odoo.write("stock.move.line", [line_id], {"quantity": qty})

# ❌ Falsch (Odoo 16 — wird still ignoriert!)
await odoo.write("stock.move.line", [line_id], {"qty_done": qty})
```

---

## ADR-004: button_validate Wizard-Trap

**Status:** Akzeptiert

**Kontext:**
`stock.picking.button_validate()` gibt in manchen Fällen kein `True` zurück, sondern ein `dict` mit einer Wizard-Action (z.B. wenn Backorder-Dialog erscheint).

**Entscheidung:** Context mit `skip_immediate` und `skip_backorder` übergeben

**Implementierung:**
```python
result = await self._odoo.call_method(
    "stock.picking", "button_validate", [picking_id],
    context={"skip_immediate": True, "skip_backorder": True}
)
# result kann True oder dict sein — beide Fälle behandeln
if isinstance(result, dict):
    # Wizard wurde trotzdem aufgerufen — als Erfolg werten wenn kein Fehler
    pass
```

**Warum passiert das?**
- `skip_immediate`: Verhindert "Sofort-Bestätigung" Dialog bei teilweise erledigten Pickings
- `skip_backorder`: Verhindert "Backorder erstellen?" Dialog
- Ohne diese Flags: Picking bleibt in `assigned` Status stecken

---

## ADR-005: quality.alert.custom statt Enterprise-Modul

**Status:** Akzeptiert

**Kontext:**
Das offizielle Odoo Quality-Modul (`quality_control`) ist nur in der Enterprise Edition verfügbar. Das Projekt verwendet Community Edition.

**Entscheidung:** Eigenes Custom-Modul `quality_alert_custom` implementiert

**Umfang:**
- `quality.alert.custom` — Hauptmodell mit Stage-Workflow
- `quality.alert.stage.custom` — Kanban-Stages (Neu / In Bearbeitung / Erledigt)
- `api_create_alert()` — Atomic API-Methode für externes Backend
- Foto-Speicherung als `ir.attachment` (Base64-kodiert)
- Sequenz `QA/XXXX` für automatische Referenznummern

**Aufruf vom Backend:**
```python
result = await odoo.call_method(
    "quality.alert.custom", "api_create_alert", [],
    args=[{
        "description": "Beschreibung",
        "picking_id": 42,
        "priority": "2",
        "photo_base64": "...",   # Base64 String, nicht Bytes!
        "photo_filename": "foto.jpg"
    }]
)
# → {"alert_id": 1, "name": "QA/0001"}
```

> [!caution] Base64 ist ein String, keine Bytes
> `ir.attachment.datas` erwartet einen Base64-kodierten **String** (nicht `bytes`).
> In Python: `base64.b64encode(photo_bytes).decode("utf-8")`

---

## Weiterführend

- [[System Architektur]] — Gesamtarchitektur
- [[API Dokumentation]] — Endpoint-Spezifikationen
- [[Voice Intent Engine]] — Voice-Pipeline ADRs
- [[PWA Implementierungshinweise]] — Frontend ADRs
