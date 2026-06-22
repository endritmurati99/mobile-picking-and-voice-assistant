---
title: Odoo
tags:
  - odoo
  - system-of-record
  - quality-alert
  - jsonrpc
  - inventory
  - projekt-wiki
created: 2026-06-22
---

# Odoo

> [!info] Worum geht es hier?
> Diese Notiz beschreibt die Rolle von **Odoo** im Projekt "Mobile Picking und Voice Assistant". Odoo ist das **System of Record** – also die eine, verbindliche Datenbank, in der alle Geschäftsdaten (Pickings, Quality Alerts, Produkte, Nutzer) leben. Es gibt bewusst **keine zweite, parallele Datenbank**. Das Backend (FastAPI) spricht ausschließlich per **JSON-RPC** mit Odoo.

Verwandte Notizen: [[00 - Start Hier]] · [[02 - Architektur & Diagramm erklärt]] · [[05 - Backend (FastAPI)]] · [[07 - n8n]] · [[08 - PWA & Voice-Pfad]] · [[10 - Glossar]]

---

## 1. Rolle: System of Record

> [!note] Analogie
> Stell dir Odoo als das **zentrale Hauptbuch** vor. Alle anderen Komponenten (PWA, FastAPI, n8n) sind nur "Schreibkräfte und Boten" – sie tragen Informationen ein oder lesen sie aus, aber die **Wahrheit** über den Zustand eines Pickings oder eines Quality Alerts steht immer in Odoo.

**Kern-Invariante:** Odoo ist das **System of Record**. Keine Shadow-DB, keine parallele Geschäftsdatenbank. Jede Statusänderung (z. B. ein Quality Alert wechselt von "Neu" auf "Erledigt") wird direkt in Odoo geschrieben und von dort wieder gelesen.

Praktische Konsequenzen:
- Das Backend hält **keinen eigenen, dauerhaften Geschäftszustand**; es ist eine Vermittlungsschicht (Bridge).
- Konsistenz, Berechtigungen, Historie (Chatter) und Workflow-Stages werden von Odoo verwaltet.

---

## 2. Zugriff: JSON-RPC über `odoo_client`

Das Backend kommuniziert mit Odoo über das **JSON-RPC-2.0-Protokoll**. Die gesamte Logik dafür kapselt eine Client-Klasse.

**Datei:** `backend/app/services/odoo_client.py`

### Transport

| Eigenschaft | Wert |
|-------------|------|
| Protokoll | JSON-RPC 2.0 |
| Endpoint | `{odoo_url}/jsonrpc` |
| Service `common` | Authentifizierung (`common.authenticate()`) |
| Service `object` | Datenoperationen (`object.execute_kw()`) |
| HTTP-Bibliothek | `httpx` (asynchron) |

### Timeout-Handling

```python
_ODOO_TIMEOUT = httpx.Timeout(connect=5.0, read=30.0, write=10.0, pool=5.0)
```

> [!info] Warum strukturiertes Timeout?
> Statt eines pauschalen Flat-Timeouts (z. B. 120 s) werden einzelne Phasen (Verbindungsaufbau, Lesen, Schreiben, Pool) getrennt begrenzt. Das verhindert, dass eine hängende Odoo-Antwort den asynchronen Event-Loop des Backends blockiert.

### Methoden des Clients

| Methode | Signatur | Zweck |
|---------|----------|-------|
| `authenticate()` | async | Login via `common.authenticate()` (API-Key oder Passwort); hält UID + Secret |
| `execute_kw(model, method, args, kwargs)` | async | Kern-Wrapper um `object.execute_kw()` |
| `search_read(model, domain, fields, limit)` | async | Kombinierte Suche + Lesen (Default-Limit 100) |
| `create(model, vals)` | async | Datensatz anlegen → liefert Record-ID |
| `write(model, ids, vals)` | async | Datensätze aktualisieren (ID-Liste + Update-Dict) |
| `call_method(model, method, ids, args, context)` | async | Beliebige Modell-Methoden aufrufen |

**Fehlerbehandlung:** Klasse `OdooAPIError` extrahiert `error.data.message` aus der Odoo-Antwort und macht sie als Python-Exception verfügbar.

> [!warning] Odoo-18-Feldnamen (häufige Stolperfalle)
> In den Kommentaren des Clients (`odoo_client.py`, ca. Zeile 5–7) sind zwei Odoo-18-Community-Besonderheiten dokumentiert, die sich von älteren Versionen unterscheiden:
> - `stock.move.line`: Feld heißt **`quantity`** (NICHT `qty_done`).
> - `stock.picking`: Feld heißt **`move_ids`** (NICHT `move_lines`).

---

## 3. Genutzte Odoo-Standardmodelle

Das Projekt verlässt sich stark auf bestehende Odoo-Standardmodelle und ergänzt nur ein einziges Custom-Addon (siehe Abschnitt 4).

| Modell | Kontext im Projekt | Verknüpfung / Feldhinweis |
|--------|--------------------|---------------------------|
| **stock.picking** | Transfer / Beleg (das eigentliche Picking) | Verlinkt via `picking_id` im Custom-Modell; Feld `move_ids` |
| **stock.move.line** | Bewegungsdetail (Zeile eines Transfers) | Feld `quantity` (Odoo 18) |
| **product.product** | Produkt-Stammdaten | Verlinkt via `product_id` |
| **stock.location** | Lagerort | Verlinkt via `location_id` |
| **stock.lot** | Charge / Seriennummer | Verlinkt via `lot_id` |
| **res.users** | Nutzer-Account | Verlinkt via `user_id`, Default = eingeloggter User |
| **mail.activity** | Aufgaben / Termine (Activities) | Geerbt über `mail.activity.mixin` |
| **mail.thread** | Chatter / Nachrichtenverlauf | Geerbt über `mail.thread`; `tracking=True` erzeugt Einträge |
| **ir.attachment** | Datei-Anhänge (Fotos) | `res_model=quality.alert.custom`, `res_id=alert.id` |
| **ir.sequence** | Nummernkreise | Code `quality.alert.custom`, Format `QA/0001` |
| **ir.ui.view** | Frontend-Layouts | Kanban (gruppiert nach `stage_id`), Form |
| **ir.model.access** | Zugriffskontrolle (CSV) | RWCD-Rechte je Gruppe/Modell |
| **res.groups** | Benutzergruppen | `group_quality_user`, `group_quality_manager` |

> [!note] Warum so viele Standardmodelle?
> Je mehr Standard-Odoo wiederverwendet wird, desto weniger eigener Code muss gepflegt werden – und desto näher bleibt das Projekt an Odoos eingebauten Funktionen (Berechtigungen, Historie, Aktivitäten). Das Custom-Addon erweitert Odoo nur dort, wo es nötig ist.

---

## 4. Custom-Addon: `quality_alert_custom`

**Pfad:** `odoo/addons/quality_alert_custom/`

### Manifest

**Datei:** `odoo/addons/quality_alert_custom/__manifest__.py`

| Schlüssel | Wert |
|-----------|------|
| `name` | "Quality Alert Custom" |
| `version` | "18.0.1.1.0" |
| `category` | "Inventory/Quality" |
| `depends` | `["stock", "mail"]` |

> [!info] Geerbte Mixins
> Das Hauptmodell erbt zwei Odoo-Standard-Mixins:
> - **`mail.thread`** → Chatter (Nachrichtenverlauf, automatische Tracking-Einträge).
> - **`mail.activity.mixin`** → Aktivitäten / Aufgaben (z. B. "Foto prüfen bis morgen").
> Daraus erklärt sich die Abhängigkeit von `mail` im Manifest.

### Verzeichnisstruktur

```
odoo/addons/quality_alert_custom/
├── __init__.py                # Import models
├── __manifest__.py            # Addon-Deklaration (v18.0.1.1.0)
├── models/
│   ├── __init__.py            # Import quality_alert
│   └── quality_alert.py       # QualityAlert + QualityAlertStage
├── security/
│   ├── ir.model.access.csv    # RWCD-Rechte je Gruppe/Modell
│   └── quality_alert_security.xml  # Gruppen + Kategorisierung
├── data/
│   └── quality_alert_data.xml # Sequenz + 3 Stages (Neu/InBearb./Erledigt)
├── views/
│   └── quality_alert_views.xml # Kanban (stage_id), Form (Header, Fotos)
└── static/
    └── description/
        └── icon.png
```

### 4.1 Modell `quality.alert.custom` (Hauptmodell)

**Datei:** `odoo/addons/quality_alert_custom/models/quality_alert.py` (Zeilen 15–190)

**Kernfelder:**

| Feld | Typ | Hinweis |
|------|-----|---------|
| `name` | Char | Sequenz-generiert (`QA/0001`), readonly |
| `description` | Text | Picker-Meldung (erforderlich) |
| `picking_id` | Many2one → `stock.picking` | `ondelete="set null"`, `tracking=True` |
| `product_id` | Many2one → `product.product` | `ondelete="set null"`, `tracking=True` |
| `location_id` | Many2one → `stock.location` | Lagerort |
| `lot_id` | Many2one → `stock.lot` | Charge / Seriennummer |
| `stage_id` | Many2one → `quality.alert.stage.custom` | Workflow-Status, `tracking=True` |
| `priority` | Selection | `[0=Normal, 1=Niedrig, 2=Hoch, 3=Kritisch]`, Default 0, `tracking=True` |
| `user_id` | Many2one → `res.users` | "Erfasst von", Default = eingeloggter User |

**KI-Felder (automatische Auswertung über n8n):**

| Feld | Typ | Hinweis |
|------|-----|---------|
| `ai_disposition` | Selection | `[sellable, rework, quarantine, scrap]`, `tracking=True` |
| `ai_confidence` | Float | Vertrauenswert 0–1, `tracking=True` |
| `ai_summary` | Text | System-Begründung, `tracking=True` |
| `ai_enhanced_description` | Text | Systembeschreibung |
| `ai_photo_analysis` | Text | Fotoanalyse-Ergebnis |
| `ai_recommended_action` | Text | Empfohlene Aktion, `tracking=True` |
| `ai_last_analyzed_at` | Datetime | Analysiert am, `tracking=True` |
| `ai_provider` | Char | Provider (z. B. Claude, OpenAI) |
| `ai_model` | Char | Modell-ID |
| `ai_evaluation_status` | Selection | `[pending, completed, failed]`, `tracking=True` |
| `ai_failure_reason` | Char | Fehlergrund (bei `failed`) |

**Foto-Felder:**

| Feld | Typ | Hinweis |
|------|-----|---------|
| `photo` | Binary | `attachment=True` |
| `photo_filename` | Char | Dateiname |
| `photo_count` | Integer | berechnet via `_compute_photo_count()` |
| `photo_gallery` | Html | berechnet via `_compute_photo_gallery()` |

**Geerbte Felder (aus `mail.thread` + `mail.activity.mixin`):** `message_ids` (Chatter), `activity_ids` (Aktivitäten), `activity_user_id`, `activity_summary`, `activity_date_deadline`.

**Wichtige Methoden:**

```python
api_create_alert(vals)   # Atomare externe Methode (Zeile 162–189)
# - akzeptiert Fotos als Liste {data_b64, filename}
#   oder einzelnes photo_base64 + photo_filename
# - nutzt sudo() (Autorisierung erfolgt auf FastAPI-Ebene)
# - legt ir.attachment-Einträge für alle Fotos an

_compute_photo_count()   # zählt ir.attachment mit mimetype "image"
_compute_photo_gallery() # baut HTML-Grid aus Attachment-Bildern

action_set_in_progress() # stage → "In Bearbeitung"
action_set_done()        # stage → "Erledigt"
```

**Sequenz (`ir.sequence`):** Code `quality.alert.custom`, Prefix `QA/`, Padding 4 Stellen → `QA/0001`, `QA/0002`, …

### 4.2 Modell `quality.alert.stage.custom` (Workflow-Stages)

**Datei:** `odoo/addons/quality_alert_custom/models/quality_alert.py` (Zeilen 5–13)

| Feld | Typ |
|------|-----|
| `name` | Char (required) |
| `sequence` | Integer (Default 10) |
| `fold` | Boolean (Default False) |

**Vordefinierte Stages** (`data/quality_alert_data.xml`):

| Reihenfolge | Name | sequence | fold | XML-ID |
|-------------|------|----------|------|--------|
| 1 | Neu | 10 | – | `stage_new` |
| 2 | In Bearbeitung | 20 | – | `stage_in_progress` |
| 3 | Erledigt | 30 | True | `stage_done` |

> [!info] XML-IDs
> Die XML-IDs (`stage_new`, `stage_in_progress`, `stage_done`) erlauben es dem Code, eine Stage stabil per `self.env.ref(...)` zu referenzieren – unabhängig von der Datenbank-internen Record-ID.

### 4.3 Security (Berechtigungen)

**Dateien:** `security/quality_alert_security.xml` + `security/ir.model.access.csv`

**Gruppen:**

| Gruppe (`res.groups`) | XML-ID | Rolle |
|-----------------------|--------|-------|
| Quality User | `group_quality_user` | Lesen, Schreiben, Erstellen (kein Löschen) |
| Quality Manager | `group_quality_manager` | Lesen, Schreiben, Erstellen, Löschen |

**Kategorisierung:** `ir.module.category` "Qualitätsmanagement". Alle internen User (`base.group_user`) erhalten automatisch die `group_quality_user`-Rechte.

**Access-Control (`ir.model.access.csv`, Spalten `R,W,C,D`):**

| ID | Modell | Gruppe | R | W | C | D |
|----|--------|--------|---|---|---|---|
| `access_quality_alert_user` | `quality.alert.custom` | `group_quality_user` | ✔ | ✔ | ✔ | – |
| `access_quality_alert_manager` | `quality.alert.custom` | `group_quality_manager` | ✔ | ✔ | ✔ | ✔ |
| `access_quality_alert_stage_user` | `quality.alert.stage.custom` | `group_quality_user` | ✔ | – | – | – |
| `access_quality_alert_stage_manager` | `quality.alert.stage.custom` | `group_quality_manager` | ✔ | ✔ | ✔ | ✔ |

> [!note] Lesart der CSV
> Die Spalten heißen exakt `id, name, model_id:id, group_id:id, perm_read, perm_write, perm_create, perm_unlink`. `perm_unlink` = Löschrecht. User dürfen Alerts also anlegen und bearbeiten, aber nur Manager dürfen löschen.

### 4.4 Data & Views

- **Data** (`data/quality_alert_data.xml`): definiert die Sequenz und die drei Stages (siehe 4.2).
- **Views** (`views/quality_alert_views.xml`):
  - **Kanban** – gruppiert nach `stage_id` (Spalten Neu / In Bearbeitung / Erledigt).
  - **Form** – Header mit Workflow-Buttons (`action_set_in_progress`, `action_set_done`) und einem Foto-Grid.

---

## 5. Konfiguration & aktive DB

**Datei:** `odoo/odoo.conf`

```ini
[options]
db_host = db                 # PostgreSQL-Container (Docker-DNS)
db_port = 5432
db_user = odoo
# db_password: vom Docker-Entrypoint via PASSWORD-Env gesetzt

addons_path = /mnt/extra-addons,/usr/lib/python3/dist-packages/odoo/addons
              # /mnt/extra-addons → quality_alert_custom

admin_passwd = PickingPoc2024!
dbfilter = ^(picking|masterfischer)$   # nur diese DBs zulässig
list_db = True
proxy_mode = True            # Betrieb hinter Reverse-Proxy

workers = 2                  # Worker-Prozesse
max_cron_threads = 1         # Cron-Threads (n8n-Webhooks)
limit_memory_hard = 2684354560   # 2.5 GB
limit_memory_soft = 2147483648   # 2.0 GB
limit_time_cpu = 600         # CPU-Timeout: 10 min
limit_time_real = 1200       # Real-Timeout: 20 min
```

> [!info] Aktive Datenbank: `masterfischer`
> Der `dbfilter` lässt genau zwei Datenbanken zu: `picking` und `masterfischer`. Die produktiv genutzte / aktive DB im Projekt ist **`masterfischer`** – hier leben die realen Pickings und Quality Alerts. (Mehr zu Containern/Netzwerk in [[03 - Docker & Container]].)

---

## 6. Wie Pickings & Quality Alerts in Odoo leben

### Pickings

Ein **Picking** ist ein `stock.picking`-Datensatz (Transfer/Beleg) mit zugehörigen `stock.move.line`-Zeilen. Das Backend liest Pickings typischerweise per `search_read("stock.picking", ...)` und greift auf Bewegungen über `move_ids` zu (Odoo-18-Feldname).

### Quality Alerts

Ein **Quality Alert** ist ein `quality.alert.custom`-Datensatz. Er entsteht, wenn ein Picker beim Kommissionieren ein Problem meldet (z. B. beschädigte Ware). Der Alert verknüpft sich mit dem auslösenden Picking (`picking_id`), dem Produkt (`product_id`), dem Lagerort (`location_id`) und ggf. der Charge (`lot_id`).

### Chatter & Activities

> [!note] Warum landet alles im Chatter?
> Weil das Modell `mail.thread` erbt und viele Felder `tracking=True` haben, schreibt Odoo **jede Änderung automatisch in den Chatter** (z. B. "stage_id: Neu → In Bearbeitung", "ai_disposition: → scrap"). So entsteht eine lückenlose, nachvollziehbare Historie – inklusive der KI-Bewertungen, die n8n zurückschreibt.

- **Chatter** (`message_ids`): Nachrichtenverlauf + automatische Tracking-Einträge.
- **Activities** (`activity_ids`): planbare Aufgaben/Termine (über `mail.activity.mixin`), z. B. eine Erinnerung für den Qualitäts-Manager.
- **Fotos** (`ir.attachment`): hängen über `res_model=quality.alert.custom` / `res_id=alert.id` am Alert und werden im Foto-Grid angezeigt.

---

## 7. Datenfluss (End-to-End)

```
Picker meldet Problem
   → PWA (pwa/)
   → FastAPI (backend/)
   → OdooClient.create("quality.alert.custom", vals)   [JSON-RPC]
   → Odoo legt quality.alert.custom an + ir.attachment für Fotos
   → n8n-Webhook erhält Payload
   → Claude/Vision-API analysiert Foto
   → n8n schreibt KI-Felder zurück:
        OdooClient.write("quality.alert.custom",[id],
            {ai_disposition, ai_confidence, ai_summary, ...})
   → tracking=True → Chatter-Einträge entstehen
   → Frontend liest Alert via search_read()
   → Qualitäts-Manager entscheidet (sellable / rework / scrap)
   → action_set_done() → stage = "Erledigt"
```

**Integrationspunkte im Detail:**

1. **Alert-Erstellung:** `POST /api/quality/alert` → `OdooClient.create("quality.alert.custom", vals)` bzw. die atomare Methode `api_create_alert(vals)` (sudo, Foto-Handling in einem Schritt). Payload-Felder: `description, picking_id, product_id, location_id, lot_id, photo_base64, photo_filename, photos: [{data_b64, filename}, ...]`.
2. **Foto-Upload:** `ir.attachment.create()` mit `datas=base64`, `mimetype=image/jpeg`, `res_model=quality.alert.custom`, `res_id=alert.id`.
3. **Workflow-Übergänge:** `action_set_in_progress()` und `action_set_done()` setzen `stage_id`.
4. **KI-Ergebnisse (n8n):** `OdooClient.write(...)` schreibt die `ai_*`-Felder; `tracking=True` erzeugt Chatter-Einträge.
5. **Authentifizierung:** FastAPI nutzt `settings.odoo_user` + `settings.odoo_password` (oder `settings.odoo_api_key`); der `OdooClient` hält UID und Secret nach `authenticate()`.

---

## 8. Zentrale Dateipfade (Index)

| Zweck | Pfad (relativ zum Projekt) |
|-------|-----------------------------|
| Konfiguration | `odoo/odoo.conf` |
| Addon-Wurzel | `odoo/addons/quality_alert_custom/` |
| Manifest | `odoo/addons/quality_alert_custom/__manifest__.py` |
| Modelle | `odoo/addons/quality_alert_custom/models/quality_alert.py` |
| Security (CSV) | `odoo/addons/quality_alert_custom/security/ir.model.access.csv` |
| Security (XML) | `odoo/addons/quality_alert_custom/security/quality_alert_security.xml` |
| Data | `odoo/addons/quality_alert_custom/data/quality_alert_data.xml` |
| Views | `odoo/addons/quality_alert_custom/views/quality_alert_views.xml` |
| JSON-RPC-Client | `backend/app/services/odoo_client.py` |

> [!info] Weiterführend
> Backend-Details in [[05 - Backend (FastAPI)]] · KI-/Webhook-Pfad in [[07 - n8n]] · Begriffe in [[10 - Glossar]] · Gesamtbild in [[02 - Architektur & Diagramm erklärt]].
