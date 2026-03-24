---
title: API Dokumentation
tags:
  - api
  - documentation
---

# API Dokumentation

> [!tip] Swagger UI
> Nach Stack-Start verfügbar unter: `https://<LAN-IP>/api/docs`

## FastAPI Backend (`/api`)

### Endpoints

| Methode | Pfad | Beschreibung |
| ------- | ---- | ------------ |
| `GET` | `/api/health` | Health Check |
| `GET` | `/api/pickings` | Offene Pickings (state=assigned) |
| `GET` | `/api/pickings/{id}` | Picking-Details + optimierte Rest-Route |
| `GET` | `/api/pickings/{id}/route-plan` | Deterministische Routenempfehlung fuer offene Positionen |
| `POST` | `/api/pickings/{id}/confirm-line` | Zeile per Scan bestätigen |
| `POST` | `/api/quality-alerts` | Quality Alert + Foto erstellen |
| `POST` | `/api/voice/recognize` | Audio → Transkript + Intent |
| `POST` | `/api/scan/validate` | Barcode gegen Erwartungswert prüfen |

### `POST /api/pickings/{id}/confirm-line`

**Query-Parameter:**
- `move_line_id` (int) — ID der `stock.move.line`
- `scanned_barcode` (str) — gescannter Barcode
- `quantity` (float, default 0) — bestätigte Menge

**Response:**
```json
{
  "success": true,
  "message": "Bestätigt.",
  "picking_complete": false
}
```

### `GET /api/pickings/{id}/route-plan`

**Beschreibung:**
- berechnet eine nachvollziehbare Picking-Reihenfolge aus `location_src`
- liefert nur noch offene Positionen als aktive Stopps
- nutzt aktuell die deterministische Heuristik `zone-first-shortest-walk`

**Response:**
```json
{
  "strategy": "zone-first-shortest-walk",
  "total_stops": 5,
  "completed_stops": 1,
  "remaining_stops": 4,
  "estimated_travel_steps": 9,
  "next_move_line_id": 501,
  "next_location_src": "WH/Stock/Lager Links/L-E1-P1",
  "next_product_name": "Brick 2x2 orange",
  "zone_sequence": ["Lager Links", "Lager Rechts"],
  "stops": [
    {
      "sequence": 1,
      "move_line_id": 501,
      "product_name": "Brick 2x2 orange",
      "location_src": "WH/Stock/Lager Links/L-E1-P1",
      "estimated_steps_from_previous": 0
    }
  ]
}
```

### `POST /api/quality-alerts`

**Form-Data:**
- `description` (str, required)
- `picking_id` (int, optional)
- `product_id` (int, optional)
- `priority` (str: "0"=Normal, "2"=Hoch, "3"=Kritisch)
- `photo` (file, optional, JPEG)

### `POST /api/voice/recognize`

**Form-Data:**
- `audio` (file) — WebM/Opus (Android) oder MP4/AAC (iOS)
- `context` (str) — `idle` | `awaiting_location_check` | `awaiting_quantity_confirm` | `awaiting_command`

**Response:**
```json
{
  "text": "bestätigt",
  "intent": "confirm",
  "value": null,
  "confidence": 0.9
}
```

## Odoo JSON-RPC

### Authentifizierung
```python
uid = await client._json_rpc("common", "authenticate",
    [db, user, api_key, {}])
```

### stock.picking laden
```python
pickings = await client.search_read(
    "stock.picking",
    [("state", "=", "assigned")],
    ["name", "partner_id", "scheduled_date", "state", "move_ids"]
)
```

### Picking validieren
```python
await client.call_method(
    "stock.picking", "button_validate", [picking_id],
    context={"skip_immediate": True, "skip_backorder": True}
)
```

### Quality Alert erstellen
```python
result = await client.call_method(
    "quality.alert.custom", "api_create_alert", [],
    args=[{"description": "...", "photo_base64": "...", "photo_filename": "..."}]
)
```

## n8n Webhooks

| Pfad | Auslöser | Payload |
| ---- | -------- | ------- |
| `POST /webhook/pick-confirmed` | Picking abgeschlossen | `{picking_id, completed_by}` |
| `POST /webhook/quality-alert-created` | Alert erstellt | `{alert_id, name, picking_id, priority}` |
