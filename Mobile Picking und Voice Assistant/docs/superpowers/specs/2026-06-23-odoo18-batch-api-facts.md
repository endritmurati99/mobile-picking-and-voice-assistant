# Odoo 18 `stock.picking.batch` — Verifizierte API-Fakten

- **Datum:** 2026-06-23
- **Quelle:** Multi-Agent-Verifikation gegen `odoo/odoo@18.0` (raw GitHub source). Hohe Konfidenz.
- **Zweck:** Grundlage für `cluster_service.py` (siehe Plan `2026-06-23-cluster-picking.md`).
  Bei Debugging zuerst hier prüfen, bevor Odoo-Verhalten angezweifelt wird.

## Bestätigte Fakten (quellenverifiziert)

| # | Thema | Bestätigt |
|---|-------|-----------|
| 1 | **create-Vals** | `company_id` mitgeben (required → sonst `_check_company`), `user_id`, `picking_ids`. **`name` weglassen** (Sequenz `picking.batch` füllt; bei `is_wave` → `picking.wave`). NIE `name='New'`. |
| 2 | **action_confirm([id])** | draft → in_progress: bestätigt Member-Pickings, `_check_company()`, setzt `state='in_progress'`, returnt `True`. |
| 3 | **action_done([id])** | validiert alle nicht-leeren/nicht-fertigen Member-Pickings via `button_validate()`; `state` → `'done'` über `_compute_state`. **Returnt oft ein Wizard-Action-Dict, NICHT `True`.** |
| 4 | **Pickings zuordnen** | (a) Batch `picking_ids=[(6,0,[ids])]` (replace) / `[(4,id,0)]` (link); (b) je Picking `write({'batch_id': <id>})`. `batch_id` = inverse Many2one (`check_company=True`). |
| 5 | **Move-Line-Menge** | Feld **`quantity`** (Float). **`qty_done` existiert NICHT** in v18 (in 17 umbenannt). |
| 6 | **move.picked** | echtes stored Boolean; rein indikativ — schreiben validiert/bewegt NICHT. |
| 7 | **quantity+picked OHNE button_validate** | validiert NICHT automatisch; Picking bleibt **`'assigned'`**. `'done'` nur via `_action_done`/`button_validate`. |
| 8 | **Wizard unterdrücken** | Kontext: `skip_backorder=True` + Policy `picking_ids_not_to_backorder=[ids]` („No Backorder") ODER `cancel_backorder=False` (Backorders auto-anlegen). `skip_sms=True` optional. `action_done` injiziert bereits `skip_sanity_check=True`. |
| 9 | **Serial/Lot** | `lot_name` (Char) auf Move-Line → Odoo legt `stock.lot` **bei Validierung** an (nicht beim Schreiben). `lot_id` (int) nur für bestehende Lots. |
| 10 | **Serial-Bedingungen** | Auto-Create gated auf `picking_type.use_create_lots=True`; Lot-Logik nur bei `product.tracking in ('serial','lot')`. Serial braucht **1 Move-Line/Stück, qty=1.0**. `lot_name` auf untracked → still ignoriert. |
| 11 | **Modul** | Modell aus Addon **`stock_picking_batch`** („Batch Transfer"). **NICHT auto-installiert** — muss aktiviert sein (Inventory-Feature „Batch Transfers"). |

## Engineering-Gotchas (im Code beachten)

- **`action_done`-Rückgabe ist evtl. ein Wizard** (`dict` mit `res_model`) → erkennen und behandeln, sonst hängt der Batch still bei `assigned`. → `validate_batch` prüft auf `dict.res_model`.
- **Backorder ist der eigentliche Blocker** bei Teilmengen (`picking_type.create_backorder == 'ask'`). Persistenter Fix: Operation-Type auf `'always'`/`'never'`. Backend-seitig: Kontext-Flags.
- **`state` nie direkt schreiben** (computed). Nur action_confirm/done/cancel.
- **Serials selbst splitten** — die „qty=1 für Serial"-Regel lebt in onchange, die bei `write()` NICHT feuert. 1 Zeile/Serial.
- **`picked=True` blockiert Re-Reservierung** — nicht zu früh setzen, wenn unreserve nötig sein könnte (für unseren Flow ok).
- **company-Konsistenz** — alle Member-Pickings müssen zur Batch-Company passen (`_check_company`). Darum `company_id` von den Pickings übernehmen.

## VOR erstem echten Lauf gegen `masterfischer` verifizieren

1. Modul `stock_picking_batch` installiert? (`ir.module.module` state)
2. `picking_type.use_create_lots` / `use_existing_lots` je Operation-Type (entscheidet `lot_name`-Auto-Create).
3. `picking_type.create_backorder` (`ask`/`always`/`never`) je Operation-Type.
4. RPC-User in `stock.group_production_lot` (für Lot-Anlage) + passende Stock-Gruppen.
5. Partial-Pick-Batch end-to-end: schließt non-interaktiv ab (kein Wizard-Dict, kein UserError)?
6. Batch flippt nach Abschluss aller Pickings automatisch auf `'done'` (nicht stuck bei `in_progress`)?
