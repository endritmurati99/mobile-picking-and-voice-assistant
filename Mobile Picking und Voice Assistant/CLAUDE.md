# CLAUDE.md — Mobiler Picking-Assistent mit Voice-Picking

> **Dieses Dokument ist die einzige Wahrheitsquelle für dieses Projekt.**
> Jede Architekturentscheidung ist begründet. Abweichungen erfordern explizite Begründung.

---

## Projekt-Identität

| Feld | Wert |
|------|------|
| **Name** | LogILab Mobile Picking Assistant |
| **Typ** | Bachelorarbeit-PoC (Design Science Research) |
| **Stack** | Odoo 18 Community · FastAPI · Vosk STT · n8n · Caddy · PostgreSQL · PWA |
| **Sprache** | Python (Backend + Odoo), TypeScript/JavaScript (PWA), YAML (Infra) |
| **Zielgeräte** | iPhone (Safari), Android (Chrome), Bluetooth-HID-Scanner |
| **Deployment** | Lokaler Docker-Stack im LAN, kein Cloud, kein Internet erforderlich |
| **Lizenz** | Nur Odoo Community Edition — kein Enterprise verfügbar |

---

## Harte Architekturregeln (nicht verhandelbar)

1. **Odoo ist System of Record.** Alle Stamm- und Bewegungsdaten leben in Odoo. Keine Schatten-Datenbanken.
2. **n8n ist Orchestrator, NICHT App-Backend.** n8n verarbeitet keine Echtzeit-Requests der PWA. Keine Session-State in n8n. Keine Binärdaten (Fotos) durch n8n routen.
3. **Das App-Backend (FastAPI) ist die einzige API-Schicht für die PWA.** Die PWA spricht nie direkt mit Odoo oder n8n.
4. **HTTPS ist zwingend im LAN.** Ohne HTTPS kein `getUserMedia()`, kein `MediaRecorder`, kein Service Worker. Caddy + mkcert, keine Ausnahme.
5. **n8n liegt NICHT im Voice-Pfad.** Der heiße Pfad (STT→Intent→TTS) läuft über App-Backend → Vosk. n8n wird nur per Fire-and-Forget-Webhook für Folgeaktionen getriggert.
6. **Touch ist immer Fallback.** Jede Voice-Interaktion hat ein Touch-Äquivalent. Voice ist Enhancement, nicht Voraussetzung.
7. **Keine externen Cloud-Dienste.** Alles läuft lokal. Kein OpenAI, kein Google STT, kein Deepgram. Vosk ist die STT-Engine.
8. **Kein Scope Creep.** Der MVP ist: Pick-Schritt sehen → Scan/Voice bestätigen → Quality Alert mit Foto erstellen. Nichts darüber hinaus.

---

## Projektstruktur

```
picking-assistant/
├── CLAUDE.md                          # ← Dieses Dokument
├── docker-compose.yml                 # Gesamter Stack
├── .env                               # Environment Variables (NICHT committen)
├── .env.example                       # Template für .env
├── .gitignore
├── Makefile                           # Convenience-Commands
│
├── infrastructure/
│   ├── caddy/
│   │   └── Caddyfile                  # Reverse Proxy + HTTPS
│   ├── certs/
│   │   ├── .gitkeep
│   │   └── README.md                  # Anleitung: mkcert-Zertifikate generieren
│   └── scripts/
│       ├── setup-certs.sh             # mkcert-Zertifikate generieren
│       ├── seed-odoo.py               # Odoo Seed-Daten via JSON-RPC
│       └── test-api.py                # API-Rauchtest-Script
│
├── odoo/
│   ├── odoo.conf                      # Odoo Server-Konfiguration
│   ├── Dockerfile                     # Odoo 18 + Custom Addons
│   └── addons/
│       └── quality_alert_custom/      # Custom Quality Module
│           ├── __init__.py
│           ├── __manifest__.py
│           ├── models/
│           │   ├── __init__.py
│           │   └── quality_alert.py   # Datenmodell
│           ├── views/
│           │   └── quality_alert_views.xml
│           ├── security/
│           │   ├── ir.model.access.csv
│           │   └── quality_alert_security.xml
│           └── data/
│               └── quality_alert_data.xml  # Default-Stages
│
├── backend/
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── app/
│   │   ├── __init__.py
│   │   ├── main.py                    # FastAPI Entry Point
│   │   ├── config.py                  # Settings aus Environment
│   │   ├── dependencies.py            # Dependency Injection
│   │   │
│   │   ├── routers/
│   │   │   ├── __init__.py
│   │   │   ├── pickings.py            # GET /api/pickings, POST /api/pickings/:id/confirm
│   │   │   ├── quality.py             # POST /api/quality-alerts
│   │   │   ├── voice.py               # POST /api/voice/recognize, WebSocket /api/voice/stream
│   │   │   ├── scan.py                # POST /api/scan/validate
│   │   │   └── health.py              # GET /api/health
│   │   │
│   │   ├── services/
│   │   │   ├── __init__.py
│   │   │   ├── odoo_client.py         # JSON-RPC Client für Odoo
│   │   │   ├── vosk_client.py         # Vosk STT Integration
│   │   │   ├── intent_engine.py       # Voice-Kommando → Aktion Mapping
│   │   │   ├── n8n_webhook.py         # Fire-and-Forget Webhook Client
│   │   │   └── picking_service.py     # Business Logic für Picking-Operationen
│   │   │
│   │   ├── models/
│   │   │   ├── __init__.py
│   │   │   ├── picking.py             # Pydantic Models für Pickings
│   │   │   ├── quality.py             # Pydantic Models für Quality Alerts
│   │   │   └── voice.py               # Pydantic Models für Voice I/O
│   │   │
│   │   └── utils/
│   │       ├── __init__.py
│   │       ├── audio.py               # Audio-Format-Konvertierung (MP4/WebM → WAV)
│   │       └── barcode.py             # Barcode-Validierung
│   │
│   └── tests/
│       ├── __init__.py
│       ├── conftest.py
│       ├── test_odoo_client.py
│       ├── test_intent_engine.py
│       └── test_picking_service.py
│
├── pwa/
│   ├── index.html                     # SPA Entry Point
│   ├── manifest.json                  # PWA Manifest
│   ├── sw.js                          # Service Worker (Offline-Cache)
│   ├── css/
│   │   └── app.css                    # Mobile-First CSS
│   ├── js/
│   │   ├── app.js                     # Haupt-App-Logik, Router
│   │   ├── api.js                     # Backend-API-Client
│   │   ├── scanner.js                 # HID-Scanner + Kamera-Scanner
│   │   ├── voice.js                   # TTS (Browser) + Audio Recording
│   │   ├── camera.js                  # Foto-Capture für Quality Alerts
│   │   ├── ui.js                      # UI-Komponenten und State
│   │   └── pwa.js                     # PWA-Installation, Offline-Handling
│   └── icons/
│       ├── icon-192.png
│       └── icon-512.png
│
├── n8n/
│   └── workflows/
│       ├── pick-confirmed.json        # Workflow: Pick bestätigt → Notification
│       ├── quality-alert-created.json # Workflow: Alert erstellt → QM benachrichtigen
│       └── daily-report.json          # Workflow: Täglicher Status-Report
│
└── docs/
    ├── ARCHITECTURE.md                # Architektur-Dokumentation
    ├── SETUP.md                       # Einrichtungsanleitung
    ├── EVALUATION.md                  # Evaluationsplan für Bachelorarbeit
    ├── VOICE_COMMANDS.md              # Voice-Kommando-Referenz
    └── DECISIONS.md                   # Architecture Decision Records
```

---

## Komponentenspezifikationen

### 1. Docker Compose Stack

```yaml
# docker-compose.yml
# HINWEIS: .env-Datei muss vor erstem Start existieren (siehe .env.example)

version: "3.8"

services:
  # ── Reverse Proxy ──────────────────────────────────────────
  caddy:
    image: caddy:2-alpine
    restart: unless-stopped
    ports:
      - "443:443"
      - "80:80"
    volumes:
      - ./infrastructure/caddy/Caddyfile:/etc/caddy/Caddyfile
      - ./infrastructure/certs:/certs:ro
      - caddy_data:/data
      - caddy_config:/config
    networks:
      - picking-net

  # ── PostgreSQL ─────────────────────────────────────────────
  db:
    image: postgres:16-alpine
    restart: unless-stopped
    environment:
      POSTGRES_USER: ${POSTGRES_USER:-odoo}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:?POSTGRES_PASSWORD muss gesetzt sein}
      POSTGRES_DB: postgres
    volumes:
      - pg_data:/var/lib/postgresql/data
      - ./infrastructure/scripts/init-n8n-db.sql:/docker-entrypoint-initdb.d/init-n8n-db.sql
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ${POSTGRES_USER:-odoo}"]
      interval: 10s
      timeout: 5s
      retries: 5
    networks:
      - picking-net

  # ── Odoo 18 Community ─────────────────────────────────────
  odoo:
    build:
      context: ./odoo
      dockerfile: Dockerfile
    restart: unless-stopped
    depends_on:
      db:
        condition: service_healthy
    environment:
      HOST: db
      PORT: 5432
      USER: ${POSTGRES_USER:-odoo}
      PASSWORD: ${POSTGRES_PASSWORD}
    volumes:
      - odoo_data:/var/lib/odoo
      - ./odoo/odoo.conf:/etc/odoo/odoo.conf:ro
      - ./odoo/addons:/mnt/extra-addons:ro
    networks:
      - picking-net

  # ── App-Backend (FastAPI) ──────────────────────────────────
  backend:
    build:
      context: ./backend
      dockerfile: Dockerfile
    restart: unless-stopped
    depends_on:
      - odoo
      - vosk
    environment:
      ODOO_URL: http://odoo:8069
      ODOO_DB: ${ODOO_DB:-picking}
      ODOO_USER: ${ODOO_USER:-admin}
      ODOO_API_KEY: ${ODOO_API_KEY:?ODOO_API_KEY muss gesetzt sein}
      VOSK_URL: ws://vosk:2700
      N8N_WEBHOOK_BASE: http://n8n:5678/webhook
      N8N_WEBHOOK_SECRET: ${N8N_WEBHOOK_SECRET}
      CORS_ORIGINS: "https://${LAN_HOST:-localhost}"
      LOG_LEVEL: ${LOG_LEVEL:-info}
    networks:
      - picking-net

  # ── Vosk STT Server (Deutsch) ──────────────────────────────
  vosk:
    image: alphacep/kaldi-de:latest
    restart: unless-stopped
    networks:
      - picking-net
    # HINWEIS: Vosk braucht ~2 GB RAM beim Start für das deutsche Modell.
    # Kein Port-Mapping nötig — nur intern über Docker-Netzwerk erreichbar.
    # Der WebSocket-Server läuft intern auf Port 2700.

  # ── n8n ────────────────────────────────────────────────────
  n8n:
    image: n8nio/n8n:latest
    restart: unless-stopped
    depends_on:
      db:
        condition: service_healthy
    environment:
      DB_TYPE: postgresdb
      DB_POSTGRESDB_HOST: db
      DB_POSTGRESDB_PORT: 5432
      DB_POSTGRESDB_DATABASE: n8n
      DB_POSTGRESDB_USER: ${POSTGRES_USER:-odoo}
      DB_POSTGRESDB_PASSWORD: ${POSTGRES_PASSWORD}
      N8N_ENCRYPTION_KEY: ${N8N_ENCRYPTION_KEY:?N8N_ENCRYPTION_KEY muss gesetzt sein}
      WEBHOOK_URL: https://${LAN_HOST:-localhost}/n8n/
      N8N_PATH: /n8n/
      N8N_HOST: 0.0.0.0
      N8N_PORT: 5678
      EXECUTIONS_PROCESS: main
      EXECUTIONS_DATA_PRUNE: "true"
      EXECUTIONS_DATA_MAX_AGE: 168
      GENERIC_TIMEZONE: Europe/Berlin
    volumes:
      - n8n_data:/home/node/.n8n
    networks:
      - picking-net

  # ── PWA Static Server ──────────────────────────────────────
  pwa:
    image: caddy:2-alpine
    restart: unless-stopped
    volumes:
      - ./pwa:/srv:ro
      - ./infrastructure/caddy/Caddyfile.pwa:/etc/caddy/Caddyfile
    networks:
      - picking-net

volumes:
  pg_data:
  odoo_data:
  caddy_data:
  caddy_config:
  n8n_data:

networks:
  picking-net:
    driver: bridge
```

### 2. Caddy Konfiguration

```caddyfile
# infrastructure/caddy/Caddyfile
# WICHTIG: {$LAN_HOST} muss als Environment Variable gesetzt sein (z.B. 192.168.1.100)

{$LAN_HOST}:443 {
    tls /certs/cert.pem /certs/key.pem

    # PWA Frontend
    handle /* {
        reverse_proxy pwa:80
    }

    # App-Backend API
    handle /api/* {
        reverse_proxy backend:8000
    }

    # Odoo Web (nur für Admin-Zugriff, nicht für mobile App)
    handle /odoo/* {
        uri strip_prefix /odoo
        reverse_proxy odoo:8069
    }

    # n8n Editor + Webhooks (nur Admin)
    handle /n8n/* {
        uri strip_prefix /n8n
        reverse_proxy n8n:5678
    }

    # Logging
    log {
        output stdout
        format console
    }
}

# HTTP → HTTPS Redirect
{$LAN_HOST}:80 {
    redir https://{$LAN_HOST}{uri} permanent
}
```

```caddyfile
# infrastructure/caddy/Caddyfile.pwa
# Static File Server für die PWA

:80 {
    root * /srv
    file_server
    try_files {path} /index.html

    header {
        # Service Worker Scope
        Service-Worker-Allowed "/"
        # Cache-Control für Entwicklung
        Cache-Control "no-cache, no-store, must-revalidate"
    }
}
```

### 3. Odoo Konfiguration

```ini
; odoo/odoo.conf
[options]
db_host = db
db_port = 5432
db_user = odoo
db_password = False
; db_password wird über Environment Variable gesetzt

addons_path = /mnt/extra-addons,/usr/lib/python3/dist-packages/odoo/addons

; Sicherheit
admin_passwd = False
dbfilter = ^picking$
list_db = False
proxy_mode = True

; Performance (PoC-Einstellungen, nicht Produktion)
workers = 2
max_cron_threads = 1
limit_memory_hard = 2684354560
limit_memory_soft = 2147483648
limit_time_cpu = 600
limit_time_real = 1200

; Logging
log_level = info
log_handler = :INFO
```

```dockerfile
# odoo/Dockerfile
FROM odoo:18.0

# Custom Addons werden über Volume gemountet
# Hier nur falls zusätzliche Python-Pakete nötig sind
USER root
# RUN pip3 install --no-cache-dir some-package
USER odoo
```

### 4. Custom Quality Module

```python
# odoo/addons/quality_alert_custom/__manifest__.py
{
    "name": "Quality Alert Custom",
    "version": "18.0.1.0.0",
    "category": "Inventory/Quality",
    "summary": "Leichtgewichtiges Quality-Alert-Modul für Community Edition",
    "description": """
        Ersetzt das Enterprise-Quality-Modul mit einem minimalen Datenmodell
        für die mobile Qualitätsfallerfassung im Picking-Prozess.
        
        Features:
        - Quality Alert mit Foto, Beschreibung, Schweregrad
        - Verknüpfung zu Picking, Produkt, Lagerort
        - Einfacher Status-Workflow (Neu → In Bearbeitung → Erledigt)
        - Chatter-Integration (mail.thread)
        - Vollständig über JSON-RPC/XML-RPC API ansprechbar
    """,
    "depends": ["stock", "mail"],
    "data": [
        "security/quality_alert_security.xml",
        "security/ir.model.access.csv",
        "data/quality_alert_data.xml",
        "views/quality_alert_views.xml",
    ],
    "installable": True,
    "application": True,
    "license": "LGPL-3",
}
```

```python
# odoo/addons/quality_alert_custom/__init__.py
from . import models
```

```python
# odoo/addons/quality_alert_custom/models/__init__.py
from . import quality_alert
```

```python
# odoo/addons/quality_alert_custom/models/quality_alert.py
from odoo import models, fields, api


class QualityAlertStage(models.Model):
    _name = "quality.alert.stage.custom"
    _description = "Quality Alert Stage"
    _order = "sequence, id"

    name = fields.Char(required=True)
    sequence = fields.Integer(default=10)
    fold = fields.Boolean(default=False)


class QualityAlert(models.Model):
    _name = "quality.alert.custom"
    _description = "Quality Alert"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "create_date desc"

    name = fields.Char(
        string="Referenz",
        required=True,
        copy=False,
        readonly=True,
        default=lambda self: self.env["ir.sequence"].next_by_code(
            "quality.alert.custom"
        ) or "NEU",
    )
    description = fields.Text(string="Beschreibung", required=True)
    
    # Verknüpfungen
    picking_id = fields.Many2one(
        "stock.picking",
        string="Transfer",
        ondelete="set null",
        tracking=True,
    )
    product_id = fields.Many2one(
        "product.product",
        string="Produkt",
        ondelete="set null",
        tracking=True,
    )
    location_id = fields.Many2one(
        "stock.location",
        string="Lagerort",
        ondelete="set null",
    )
    lot_id = fields.Many2one(
        "stock.lot",
        string="Charge/Seriennummer",
        ondelete="set null",
    )
    
    # Workflow
    stage_id = fields.Many2one(
        "quality.alert.stage.custom",
        string="Status",
        tracking=True,
        group_expand="_read_group_stage_ids",
        default=lambda self: self._get_default_stage(),
    )
    priority = fields.Selection(
        [("0", "Normal"), ("1", "Niedrig"), ("2", "Hoch"), ("3", "Kritisch")],
        string="Priorität",
        default="0",
        tracking=True,
    )
    user_id = fields.Many2one(
        "res.users",
        string="Erfasst von",
        default=lambda self: self.env.user,
    )
    
    # Foto — wird als ir.attachment angehängt, nicht als Binary-Feld.
    # Das vereinfacht die API-Integration (Attachment über Standard-Mechanismus).
    # Zusätzliches Binary-Feld für schnellen Inline-Zugriff:
    photo = fields.Binary(string="Foto", attachment=True)
    photo_filename = fields.Char(string="Dateiname")

    def _get_default_stage(self):
        return self.env["quality.alert.stage.custom"].search(
            [], order="sequence asc", limit=1
        )

    @api.model
    def _read_group_stage_ids(self, stages, domain, order):
        """Alle Stages in Kanban-View anzeigen, auch leere."""
        return self.env["quality.alert.stage.custom"].search([])

    # ── API-Methoden für externes Backend ────────────────────
    
    @api.model
    def api_create_alert(self, vals):
        """
        Atomare Methode für die externe Alert-Erstellung.
        Erstellt Alert + optional Foto-Attachment in einer Transaktion.
        
        :param vals: dict mit mindestens 'description'.
                     Optional: 'picking_id', 'product_id', 'location_id',
                     'priority', 'photo_base64', 'photo_filename'
        :return: dict mit alert_id, name
        """
        photo_b64 = vals.pop("photo_base64", None)
        photo_filename = vals.pop("photo_filename", None)
        
        alert = self.create(vals)
        
        if photo_b64 and photo_filename:
            self.env["ir.attachment"].create({
                "name": photo_filename,
                "type": "binary",
                "datas": photo_b64,
                "res_model": self._name,
                "res_id": alert.id,
                "mimetype": "image/jpeg",
            })
        
        return {
            "alert_id": alert.id,
            "name": alert.name,
        }
```

```xml
<!-- odoo/addons/quality_alert_custom/security/quality_alert_security.xml -->
<?xml version="1.0" encoding="utf-8"?>
<odoo>
    <record id="module_category_quality" model="ir.module.category">
        <field name="name">Qualitätsmanagement</field>
    </record>

    <record id="group_quality_user" model="res.groups">
        <field name="name">Qualitäts-Nutzer</field>
        <field name="category_id" ref="module_category_quality"/>
    </record>

    <record id="group_quality_manager" model="res.groups">
        <field name="name">Qualitäts-Manager</field>
        <field name="category_id" ref="module_category_quality"/>
        <field name="implied_ids" eval="[(4, ref('group_quality_user'))]"/>
    </record>
</odoo>
```

```csv
# odoo/addons/quality_alert_custom/security/ir.model.access.csv
id,name,model_id:id,group_id:id,perm_read,perm_write,perm_create,perm_unlink
access_quality_alert_user,quality.alert.custom.user,model_quality_alert_custom,group_quality_user,1,1,1,0
access_quality_alert_manager,quality.alert.custom.manager,model_quality_alert_custom,group_quality_manager,1,1,1,1
access_quality_alert_stage_user,quality.alert.stage.custom.user,model_quality_alert_stage_custom,group_quality_user,1,0,0,0
access_quality_alert_stage_manager,quality.alert.stage.custom.manager,model_quality_alert_stage_custom,group_quality_manager,1,1,1,1
```

```xml
<!-- odoo/addons/quality_alert_custom/data/quality_alert_data.xml -->
<?xml version="1.0" encoding="utf-8"?>
<odoo noupdate="1">
    <!-- Sequenz für automatische Referenznummern -->
    <record id="seq_quality_alert" model="ir.sequence">
        <field name="name">Quality Alert</field>
        <field name="code">quality.alert.custom</field>
        <field name="prefix">QA/</field>
        <field name="padding">4</field>
    </record>

    <!-- Standard-Stages -->
    <record id="stage_new" model="quality.alert.stage.custom">
        <field name="name">Neu</field>
        <field name="sequence">10</field>
    </record>
    <record id="stage_in_progress" model="quality.alert.stage.custom">
        <field name="name">In Bearbeitung</field>
        <field name="sequence">20</field>
    </record>
    <record id="stage_done" model="quality.alert.stage.custom">
        <field name="name">Erledigt</field>
        <field name="sequence">30</field>
        <field name="fold">True</field>
    </record>
</odoo>
```

```xml
<!-- odoo/addons/quality_alert_custom/views/quality_alert_views.xml -->
<?xml version="1.0" encoding="utf-8"?>
<odoo>
    <!-- Kanban View -->
    <record id="quality_alert_view_kanban" model="ir.ui.view">
        <field name="name">quality.alert.custom.kanban</field>
        <field name="model">quality.alert.custom</field>
        <field name="arch" type="xml">
            <kanban default_group_by="stage_id" class="o_kanban_small_column">
                <field name="name"/>
                <field name="priority"/>
                <field name="product_id"/>
                <field name="user_id"/>
                <field name="stage_id"/>
                <templates>
                    <t t-name="kanban-card">
                        <field name="priority" widget="priority"/>
                        <field name="name"/>
                        <field name="product_id"/>
                        <div class="o_kanban_record_bottom">
                            <field name="user_id" widget="many2one_avatar_user"/>
                        </div>
                    </t>
                </templates>
            </kanban>
        </field>
    </record>

    <!-- Form View -->
    <record id="quality_alert_view_form" model="ir.ui.view">
        <field name="name">quality.alert.custom.form</field>
        <field name="model">quality.alert.custom</field>
        <field name="arch" type="xml">
            <form>
                <header>
                    <field name="stage_id" widget="statusbar" clickable="1"/>
                </header>
                <sheet>
                    <group>
                        <group>
                            <field name="name"/>
                            <field name="priority" widget="priority"/>
                            <field name="user_id"/>
                        </group>
                        <group>
                            <field name="picking_id"/>
                            <field name="product_id"/>
                            <field name="location_id"/>
                            <field name="lot_id"/>
                        </group>
                    </group>
                    <notebook>
                        <page string="Beschreibung">
                            <field name="description"/>
                            <field name="photo" widget="image"/>
                        </page>
                    </notebook>
                </sheet>
                <chatter/>
            </form>
        </field>
    </record>

    <!-- Tree View -->
    <record id="quality_alert_view_tree" model="ir.ui.view">
        <field name="name">quality.alert.custom.tree</field>
        <field name="model">quality.alert.custom</field>
        <field name="arch" type="xml">
            <tree>
                <field name="name"/>
                <field name="product_id"/>
                <field name="picking_id"/>
                <field name="priority"/>
                <field name="stage_id"/>
                <field name="user_id"/>
                <field name="create_date"/>
            </tree>
        </field>
    </record>

    <!-- Action + Menü -->
    <record id="quality_alert_action" model="ir.actions.act_window">
        <field name="name">Quality Alerts</field>
        <field name="res_model">quality.alert.custom</field>
        <field name="view_mode">kanban,tree,form</field>
    </record>

    <menuitem id="menu_quality_root" name="Qualität" sequence="25"/>
    <menuitem id="menu_quality_alerts"
              name="Quality Alerts"
              parent="menu_quality_root"
              action="quality_alert_action"
              sequence="10"/>
</odoo>
```

### 5. App-Backend (FastAPI)

```dockerfile
# backend/Dockerfile
FROM python:3.12-slim

WORKDIR /app

# System-Abhängigkeiten für Audio-Konvertierung
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ ./app/

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--log-level", "info"]
```

```txt
# backend/requirements.txt
fastapi==0.115.*
uvicorn[standard]==0.34.*
python-multipart==0.0.*
httpx==0.28.*
websockets==14.*
pydantic==2.*
pydantic-settings==2.*
python-jose[cryptography]==3.*
```

```python
# backend/app/config.py
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Odoo
    odoo_url: str = "http://odoo:8069"
    odoo_db: str = "picking"
    odoo_user: str = "admin"
    odoo_api_key: str  # Pflichtfeld, keine Default
    
    # Vosk
    vosk_url: str = "ws://vosk:2700"
    
    # n8n
    n8n_webhook_base: str = "http://n8n:5678/webhook"
    n8n_webhook_secret: str = ""
    
    # App
    cors_origins: str = "https://localhost"
    log_level: str = "info"
    
    class Config:
        env_file = ".env"


settings = Settings()
```

```python
# backend/app/main.py
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.routers import pickings, quality, voice, scan, health

app = FastAPI(
    title="Picking Assistant API",
    version="0.1.0",
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins.split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router, prefix="/api", tags=["health"])
app.include_router(pickings.router, prefix="/api", tags=["pickings"])
app.include_router(quality.router, prefix="/api", tags=["quality"])
app.include_router(voice.router, prefix="/api", tags=["voice"])
app.include_router(scan.router, prefix="/api", tags=["scan"])
```

```python
# backend/app/services/odoo_client.py
"""
Odoo JSON-RPC Client.

WICHTIG: Odoo 18 Community nutzt JSON-RPC (nicht JSON-2, das ist erst ab Odoo 19).
Authentifizierung erfolgt über API-Key statt Passwort.
Jeder RPC-Call ist eine eigene Datenbank-Transaktion in Odoo.

Feldnamen Odoo 18:
  - stock.move.line: 'quantity' (NICHT 'qty_done' — das war Odoo 16!)
  - stock.picking: 'move_ids' (NICHT 'move_lines' — das war Odoo 16!)
"""
import httpx
from typing import Any
from app.config import settings


class OdooClient:
    def __init__(self):
        self._url = settings.odoo_url
        self._db = settings.odoo_db
        self._uid = None
        self._client = httpx.AsyncClient(timeout=30.0)
    
    async def _json_rpc(self, service: str, method: str, args: list) -> Any:
        """Low-level JSON-RPC call."""
        payload = {
            "jsonrpc": "2.0",
            "method": "call",
            "params": {
                "service": service,
                "method": method,
                "args": args,
            },
            "id": 1,
        }
        resp = await self._client.post(f"{self._url}/jsonrpc", json=payload)
        resp.raise_for_status()
        result = resp.json()
        if result.get("error"):
            raise OdooAPIError(result["error"])
        return result.get("result")
    
    async def authenticate(self) -> int:
        """Authentifizierung und UID abrufen."""
        self._uid = await self._json_rpc(
            "common", "authenticate",
            [self._db, settings.odoo_user, settings.odoo_api_key, {}]
        )
        if not self._uid:
            raise OdooAPIError("Authentifizierung fehlgeschlagen")
        return self._uid
    
    async def execute_kw(
        self, model: str, method: str, args: list, kwargs: dict | None = None
    ) -> Any:
        """Standard execute_kw Aufruf."""
        if not self._uid:
            await self.authenticate()
        return await self._json_rpc(
            "object", "execute_kw",
            [
                self._db,
                self._uid,
                settings.odoo_api_key,
                model,
                method,
                args,
                kwargs or {},
            ]
        )
    
    async def search_read(
        self, model: str, domain: list, fields: list, limit: int = 100
    ) -> list[dict]:
        return await self.execute_kw(
            model, "search_read", [domain],
            {"fields": fields, "limit": limit}
        )
    
    async def create(self, model: str, vals: dict) -> int:
        return await self.execute_kw(model, "create", [vals])
    
    async def write(self, model: str, ids: list[int], vals: dict) -> bool:
        return await self.execute_kw(model, "write", [ids, vals])
    
    async def call_method(self, model: str, method: str, ids: list[int], args=None):
        """Beliebige Modell-Methode aufrufen (z.B. button_validate)."""
        call_args = [ids] + (args or [])
        return await self.execute_kw(model, method, call_args)


class OdooAPIError(Exception):
    """Odoo API Fehler."""
    def __init__(self, error_data):
        if isinstance(error_data, dict):
            self.message = error_data.get("data", {}).get("message", str(error_data))
        else:
            self.message = str(error_data)
        super().__init__(self.message)
```

```python
# backend/app/services/intent_engine.py
"""
Voice-Intent-Engine.

Matcht Vosk-Transkripte auf Picking-Kommandos.
Verwendet kontextabhängiges Matching: Je nach aktuellem Schritt im Picking-Flow
werden nur gültige Kommandos akzeptiert.

KEINE NLP-Library, KEINE KI — nur Regex + Levenshtein für Robustheit.
"""
import re
from dataclasses import dataclass
from enum import Enum


class PickingContext(Enum):
    """Aktueller Schritt im Voice-Picking-Flow."""
    IDLE = "idle"
    AWAITING_LOCATION_CHECK = "awaiting_location_check"    # Prüfziffer erwartet
    AWAITING_QUANTITY_CONFIRM = "awaiting_quantity_confirm"  # Mengenbestätigung
    AWAITING_COMMAND = "awaiting_command"                    # Allgemeines Kommando


@dataclass
class Intent:
    action: str          # z.B. "confirm", "next", "problem", "quantity"
    value: str | None    # z.B. "5" bei Menge, "47" bei Prüfziffer
    confidence: float    # 0.0–1.0
    raw_text: str


# Kommando-Patterns (Deutsch)
PATTERNS = {
    "confirm": [
        r"\b(bestätigt|bestätige|bestätigen|ja|korrekt|stimmt|richtig|okay|ok)\b",
    ],
    "next": [
        r"\b(nächster|nächste|weiter|skip|überspringen)\b",
    ],
    "previous": [
        r"\b(zurück|vorheriger|vorherige)\b",
    ],
    "problem": [
        r"\b(problem|fehler|defekt|beschädigt|kaputt|fehlt|mangel)\b",
    ],
    "photo": [
        r"\b(foto|photo|bild|kamera|aufnahme)\b",
    ],
    "repeat": [
        r"\b(wiederholen|nochmal|noch\s*mal|bitte\s*was|wie\s*bitte)\b",
    ],
    "pause": [
        r"\b(pause|stopp|stop|halt|warten)\b",
    ],
    "done": [
        r"\b(fertig|abgeschlossen|ende|beenden)\b",
    ],
    "help": [
        r"\b(hilfe|help|was\s*kann\s*ich)\b",
    ],
}

# Zahlwörter → Ziffern
GERMAN_NUMBERS = {
    "null": "0", "eins": "1", "zwei": "2", "drei": "3", "vier": "4",
    "fünf": "5", "sechs": "6", "sieben": "7", "acht": "8", "neun": "9",
    "zehn": "10", "elf": "11", "zwölf": "12",
}


def recognize_intent(text: str, context: PickingContext) -> Intent:
    """
    Erkennt Intent aus Vosk-Transkript.
    
    Priorisierung:
    1. Zahlenwerte (im passenden Kontext)
    2. Exakte Kommando-Matches
    3. Fuzzy-Match als Fallback
    """
    text_lower = text.strip().lower()
    
    if not text_lower:
        return Intent("unknown", None, 0.0, text)
    
    # Zahlen erkennen (Prüfziffer oder Menge)
    if context in (
        PickingContext.AWAITING_LOCATION_CHECK,
        PickingContext.AWAITING_QUANTITY_CONFIRM,
    ):
        number = _extract_number(text_lower)
        if number is not None:
            action = (
                "check_digit" if context == PickingContext.AWAITING_LOCATION_CHECK
                else "quantity"
            )
            return Intent(action, str(number), 0.95, text)
    
    # Kommando-Patterns matchen
    for action, patterns in PATTERNS.items():
        for pattern in patterns:
            if re.search(pattern, text_lower):
                return Intent(action, None, 0.9, text)
    
    return Intent("unknown", None, 0.0, text)


def _extract_number(text: str) -> int | None:
    """Extrahiert Zahl aus Text (Ziffern oder deutsche Zahlwörter)."""
    # Direkte Ziffern
    digits = re.findall(r"\d+", text)
    if digits:
        return int(digits[0])
    
    # Deutsche Zahlwörter
    for word, digit in GERMAN_NUMBERS.items():
        if word in text:
            return int(digit)
    
    return None
```

### 6. Environment-Template

```bash
# .env.example — Kopieren nach .env und Werte ausfüllen
# NIEMALS .env committen!

# ── PostgreSQL ───────────────────────────────────────────────
POSTGRES_USER=odoo
POSTGRES_PASSWORD=HIER_SICHERES_PASSWORT_SETZEN

# ── Odoo ─────────────────────────────────────────────────────
ODOO_DB=picking
ODOO_USER=admin
ODOO_API_KEY=WIRD_NACH_ODOO_SETUP_GENERIERT

# ── n8n ──────────────────────────────────────────────────────
# WICHTIG: Vor erstem Start generieren und SICHER aufbewahren!
# Verlust = alle n8n Credentials unwiederbringlich verloren.
# Generieren: openssl rand -hex 32
N8N_ENCRYPTION_KEY=HIER_GENERIEREN

# ── Netzwerk ─────────────────────────────────────────────────
# LAN-IP des Docker-Hosts (z.B. 192.168.1.100)
LAN_HOST=192.168.1.100

# ── n8n Webhook ──────────────────────────────────────────────
N8N_WEBHOOK_SECRET=HIER_GENERIEREN

# ── Logging ──────────────────────────────────────────────────
LOG_LEVEL=info
```

### 7. Hilfsskripte

```bash
#!/bin/bash
# infrastructure/scripts/setup-certs.sh
# Generiert mkcert-Zertifikate für lokales HTTPS

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CERT_DIR="$SCRIPT_DIR/../certs"

# LAN-IP aus .env oder Argument
LAN_HOST="${1:-${LAN_HOST:-}}"

if [ -z "$LAN_HOST" ]; then
    echo "Verwendung: $0 <LAN-IP>"
    echo "Beispiel:   $0 192.168.1.100"
    exit 1
fi

# Prüfe ob mkcert installiert ist
if ! command -v mkcert &> /dev/null; then
    echo "FEHLER: mkcert ist nicht installiert."
    echo "Installation:"
    echo "  macOS:   brew install mkcert"
    echo "  Linux:   https://github.com/FiloSottile/mkcert#installation"
    echo "  Windows: choco install mkcert"
    exit 1
fi

# Lokale CA installieren (einmalig)
mkcert -install

# Zertifikat generieren
mkcert \
    -cert-file "$CERT_DIR/cert.pem" \
    -key-file "$CERT_DIR/key.pem" \
    "$LAN_HOST" \
    localhost \
    127.0.0.1

echo ""
echo "✅ Zertifikate generiert in $CERT_DIR"
echo ""
echo "NÄCHSTER SCHRITT: CA-Zertifikat auf mobile Geräte übertragen"
echo "CA-Datei: $(mkcert -CAROOT)/rootCA.pem"
echo ""
echo "iOS:     Per AirDrop/Mail senden → Profil installieren → Einstellungen"
echo "         → Allgemein → Info → Zertifikatsvertrauenseinstellungen → aktivieren"
echo "Android: Einstellungen → Sicherheit → Zertifikat installieren → CA"
```

```python
# infrastructure/scripts/seed-odoo.py
"""
Seed-Daten für Odoo 18 Community.

Erstellt Mindest-Testdaten für den Picking-PoC:
- Lagerorte mit Barcodes und Prüfziffern
- Produkte mit EAN-Barcodes
- Test-Pickings im Status 'assigned'

Verwendung:
    python seed-odoo.py --url http://localhost:8069 --db picking --user admin --api-key <key>
"""
import argparse
import json
import sys
from xmlrpc.client import ServerProxy


def main():
    parser = argparse.ArgumentParser(description="Odoo Seed-Daten")
    parser.add_argument("--url", default="http://localhost:8069")
    parser.add_argument("--db", default="picking")
    parser.add_argument("--user", default="admin")
    parser.add_argument("--api-key", required=True)
    args = parser.parse_args()

    # Verbindung
    common = ServerProxy(f"{args.url}/xmlrpc/2/common")
    uid = common.authenticate(args.db, args.user, args.api_key, {})
    if not uid:
        print("FEHLER: Authentifizierung fehlgeschlagen")
        sys.exit(1)
    
    models = ServerProxy(f"{args.url}/xmlrpc/2/object")
    
    def execute(model, method, *a, **kw):
        return models.execute_kw(args.db, uid, args.api_key, model, method, list(a), kw)

    print("🏭 Erstelle Lagerorte...")
    
    # Hauptlager finden (existiert per Default)
    wh_ids = execute("stock.warehouse", "search", [("code", "=", "WH")])
    wh_id = wh_ids[0] if wh_ids else None
    
    # Lagerorte
    locations = [
        {"name": "Regal A-01", "barcode": "LOC-A01", "usage": "internal"},
        {"name": "Regal A-02", "barcode": "LOC-A02", "usage": "internal"},
        {"name": "Regal B-01", "barcode": "LOC-B01", "usage": "internal"},
        {"name": "Regal B-02", "barcode": "LOC-B02", "usage": "internal"},
        {"name": "Regal C-01", "barcode": "LOC-C01", "usage": "internal"},
    ]
    
    # Parent-Location finden (WH/Stock)
    stock_loc = execute(
        "stock.location", "search_read",
        [("name", "=", "Stock"), ("usage", "=", "internal")],
        fields=["id"], limit=1
    )
    parent_id = stock_loc[0]["id"] if stock_loc else False
    
    loc_ids = {}
    for loc in locations:
        existing = execute(
            "stock.location", "search",
            [("barcode", "=", loc["barcode"])]
        )
        if existing:
            loc_ids[loc["barcode"]] = existing[0]
            print(f"  ↳ {loc['name']} existiert bereits")
        else:
            lid = execute("stock.location", "create", {
                **loc,
                "location_id": parent_id,
            })
            loc_ids[loc["barcode"]] = lid
            print(f"  ✅ {loc['name']} erstellt (ID: {lid})")

    print("\n📦 Erstelle Produkte...")
    
    products = [
        {"name": "Schraube M8x40",    "barcode": "4006381333931", "default_code": "SCR-M8-40"},
        {"name": "Mutter M8 DIN934",   "barcode": "4006381333948", "default_code": "NUT-M8"},
        {"name": "Unterlegscheibe M8", "barcode": "4006381333955", "default_code": "WSH-M8"},
        {"name": "Winkel 40x40",       "barcode": "5901234123457", "default_code": "ANG-40"},
        {"name": "Gewindestange M8",   "barcode": "7622210100528", "default_code": "ROD-M8"},
    ]
    
    prod_ids = {}
    for prod in products:
        existing = execute(
            "product.product", "search",
            [("barcode", "=", prod["barcode"])]
        )
        if existing:
            prod_ids[prod["barcode"]] = existing[0]
            print(f"  ↳ {prod['name']} existiert bereits")
        else:
            pid = execute("product.product", "create", {
                "name": prod["name"],
                "barcode": prod["barcode"],
                "default_code": prod["default_code"],
                "type": "product",
                "tracking": "none",
            })
            prod_ids[prod["barcode"]] = pid
            print(f"  ✅ {prod['name']} erstellt (ID: {pid})")

    print("\n📋 Erstelle Test-Pickings...")
    
    # Picking-Type für interne Transfers finden
    pick_type = execute(
        "stock.picking.type", "search_read",
        [("code", "=", "internal")],
        fields=["id", "default_location_src_id", "default_location_dest_id"],
        limit=1
    )
    
    if not pick_type:
        # Fallback: Outgoing
        pick_type = execute(
            "stock.picking.type", "search_read",
            [("code", "=", "outgoing")],
            fields=["id", "default_location_src_id", "default_location_dest_id"],
            limit=1
        )
    
    if pick_type:
        pt = pick_type[0]
        picking_id = execute("stock.picking", "create", {
            "picking_type_id": pt["id"],
            "location_id": pt["default_location_src_id"][0] if pt["default_location_src_id"] else parent_id,
            "location_dest_id": pt["default_location_dest_id"][0] if pt["default_location_dest_id"] else loc_ids.get("LOC-C01", parent_id),
            "move_ids": [
                (0, 0, {
                    "name": "Schraube M8x40",
                    "product_id": prod_ids["4006381333931"],
                    "product_uom_qty": 10,
                    "location_id": loc_ids.get("LOC-A01", parent_id),
                    "location_dest_id": loc_ids.get("LOC-C01", parent_id),
                }),
                (0, 0, {
                    "name": "Mutter M8 DIN934",
                    "product_id": prod_ids["4006381333948"],
                    "product_uom_qty": 10,
                    "location_id": loc_ids.get("LOC-A02", parent_id),
                    "location_dest_id": loc_ids.get("LOC-C01", parent_id),
                }),
                (0, 0, {
                    "name": "Winkel 40x40",
                    "product_id": prod_ids["5901234123457"],
                    "product_uom_qty": 5,
                    "location_id": loc_ids.get("LOC-B01", parent_id),
                    "location_dest_id": loc_ids.get("LOC-C01", parent_id),
                }),
            ],
        })
        
        # Picking bestätigen → Status 'assigned'
        execute("stock.picking", "action_confirm", [picking_id])
        execute("stock.picking", "action_assign", [picking_id])
        
        print(f"  ✅ Picking erstellt und zugewiesen (ID: {picking_id})")
    else:
        print("  ⚠️ Kein Picking-Typ gefunden — manuell erstellen")

    print("\n🎉 Seed-Daten komplett!")
    print(f"   Lagerorte: {len(loc_ids)}")
    print(f"   Produkte:  {len(prod_ids)}")
    print(f"   Pickings:  1")


if __name__ == "__main__":
    main()
```

### 8. Makefile

```makefile
# Makefile — Convenience-Commands für den Picking-Assistenten

.PHONY: help setup up down logs seed test clean

SHELL := /bin/bash

help: ## Hilfe anzeigen
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

# ── Setup ────────────────────────────────────────────────────

setup: ## Erstmalige Einrichtung (Zertifikate, .env, Docker Build)
	@echo "1️⃣  Prüfe .env..."
	@test -f .env || (cp .env.example .env && echo "⚠️  .env erstellt — bitte Werte ausfüllen!" && exit 1)
	@echo "2️⃣  Generiere Zertifikate..."
	@bash infrastructure/scripts/setup-certs.sh $${LAN_HOST}
	@echo "3️⃣  Baue Docker Images..."
	docker compose build
	@echo "✅ Setup abgeschlossen. Nächster Schritt: make up"

# ── Docker ───────────────────────────────────────────────────

up: ## Stack starten
	docker compose up -d
	@echo "⏳ Warte auf Odoo..."
	@sleep 10
	@echo "✅ Stack läuft. Odoo: https://$${LAN_HOST}/odoo/ | n8n: https://$${LAN_HOST}/n8n/"

down: ## Stack stoppen
	docker compose down

restart: ## Stack neustarten
	docker compose restart

logs: ## Logs aller Services anzeigen
	docker compose logs -f --tail=50

logs-backend: ## Nur Backend-Logs
	docker compose logs -f --tail=50 backend

logs-odoo: ## Nur Odoo-Logs
	docker compose logs -f --tail=50 odoo

# ── Daten ────────────────────────────────────────────────────

seed: ## Seed-Daten in Odoo laden
	@echo "📊 Lade Seed-Daten..."
	python infrastructure/scripts/seed-odoo.py \
		--url http://localhost:8069 \
		--db $${ODOO_DB:-picking} \
		--user $${ODOO_USER:-admin} \
		--api-key $${ODOO_API_KEY}

# ── Tests ────────────────────────────────────────────────────

test: ## Backend-Tests ausführen
	cd backend && python -m pytest tests/ -v

test-api: ## API-Rauchtest
	python infrastructure/scripts/test-api.py

# ── Wartung ──────────────────────────────────────────────────

clean: ## Alles entfernen (Volumes, Images)
	docker compose down -v --rmi local
	@echo "🗑️  Alles bereinigt."

shell-odoo: ## Odoo Shell öffnen
	docker compose exec odoo odoo shell -d $${ODOO_DB:-picking}

shell-backend: ## Backend Shell öffnen
	docker compose exec backend python

shell-db: ## PostgreSQL Shell öffnen
	docker compose exec db psql -U $${POSTGRES_USER:-odoo} -d $${ODOO_DB:-picking}
```

### 9. Git-Konfiguration

```gitignore
# .gitignore

# Environment
.env
*.env.local

# Zertifikate
infrastructure/certs/*.pem
infrastructure/certs/*.crt
infrastructure/certs/*.key

# Python
__pycache__/
*.py[cod]
*.egg-info/
.venv/
venv/

# Node
node_modules/

# Docker
docker-compose.override.yml

# IDE
.vscode/
.idea/
*.swp
*.swo

# OS
.DS_Store
Thumbs.db

# Odoo
odoo/filestore/

# n8n
.n8n/
```

---

## Phasen-Checkliste (Go/No-Go)

Jede Phase hat ein binäres Erfolgskriterium. Kein Code der nächsten Phase wird geschrieben, bevor das Kriterium der aktuellen Phase erfüllt ist.

### Phase 0: Infrastruktur (Tage 1–3)

- [ ] `.env` ausgefüllt
- [ ] `make setup` läuft fehlerfrei
- [ ] `make up` startet alle Container
- [ ] `https://<LAN-IP>/odoo/` zeigt Odoo-Login im mobilen Browser (iOS + Android)
- [ ] Grünes Schloss im Browser (kein Zertifikats-Fehler)
- [ ] `https://<LAN-IP>/n8n/` zeigt n8n-Setup-Wizard
- **Kill:** Zertifikat wird auf iOS trotz CA-Installation nicht akzeptiert → DNS-Lösung mit `.local`-Domain testen
- **NICHT BAUEN:** Backend-Code, PWA, Voice, Scanning

### Phase 1: Odoo-Datenmodell (Tage 4–6)

- [ ] Quality-Alert-Custom-Modul installiert und in Odoo-UI sichtbar
- [ ] `make seed` läuft fehlerfrei: 5 Lagerorte, 5 Produkte, 1 Picking
- [ ] JSON-RPC: `search_read` auf `stock.picking` gibt korrekte Daten
- [ ] JSON-RPC: `create` auf `quality.alert.custom` erstellt Alert
- [ ] JSON-RPC: `create` auf `ir.attachment` hängt Foto an Alert
- **Kill:** Custom Module installiert nicht → `__manifest__.py` Dependencies prüfen
- **NICHT BAUEN:** Frontend, Voice, Backend-Endpoints

### Phase 2: Backend + PWA-Shell (Tage 7–14)

- [ ] `GET /api/health` gibt 200 zurück
- [ ] `GET /api/pickings` gibt offene Pickings mit Move-Lines zurück
- [ ] `POST /api/pickings/:id/confirm` markiert Pick-Zeile als erledigt
- [ ] `POST /api/quality-alerts` erstellt Alert mit Foto in Odoo
- [ ] PWA: Pick-Liste wird auf dem Handy angezeigt
- [ ] PWA: Foto-Capture funktioniert auf iOS Safari und Chrome Android
- **Kill:** Odoo JSON-RPC instabil bei mehreren sequentiellen Calls → Connection-Pooling prüfen
- **NICHT BAUEN:** Voice, Barcode-Scanning, n8n-Workflows

### Phase 3: Barcode-Scanning (Tage 15–18)

- [ ] HID-Scanner: Scan wird in PWA erkannt und korrekt gematcht
- [ ] Kamera-Scan (Quagga2): Funktioniert als Fallback auf Android
- [ ] Touch-Eingabe: Manuelle Barcode-Eingabe als letzter Fallback
- [ ] Scan → automatischer Pick-Line-Match → Bestätigung
- **Kill:** Kein Scan-Weg funktioniert zuverlässig → nur Touch-Bestätigung (kein Blocker)
- **NICHT BAUEN:** Voice, n8n-Integration

### Phase 4: Voice-Picking (Tage 19–28)

- [ ] Vosk-Container antwortet auf WebSocket-Connection
- [ ] `POST /api/voice/recognize` transkribiert deutsches Audio korrekt
- [ ] TTS spricht Pick-Anweisung im Browser (iOS + Android)
- [ ] Intent-Engine erkennt "bestätigt", "nächster", "problem", Zahlen
- [ ] Vollständiger Voice-Loop: Anweisung → Spracheingabe → Aktion → nächste Anweisung
- [ ] Touch-Fallback erscheint nach 5s ohne Erkennung
- **Kill:** Vosk-Erkennung <60% für deutsche Kommandos → faster-whisper evaluieren
- **NICHT BAUEN:** n8n-Workflows, komplexe Voice-Flows

### Phase 5: n8n-Orchestrierung (Tage 29–33)

- [ ] n8n Webhook empfängt Events vom Backend
- [ ] Workflow "Pick bestätigt" wird korrekt ausgelöst
- [ ] Workflow "Quality Alert erstellt" wird korrekt ausgelöst
- [ ] Error-Handling in n8n bei Odoo-Timeout
- **Kill:** Webhook-Routing hinter Caddy funktioniert nicht → `WEBHOOK_URL` prüfen
- **NICHT BAUEN:** Komplexe Approval-Flows, Reporting

### Phase 6: Integration + Lagertest (Tage 34–40)

- [ ] 20 Picks ohne Systemfehler
- [ ] Voice-Erkennungsrate >80% mit Headset
- [ ] Quality Alert mit Foto aus Live-Szenario
- [ ] System erholt sich von Odoo-Restart
- **Kill:** Voice im Lager unbrauchbar → Voice als "optional" deklarieren, Fokus auf Scan + Touch

### Phase 7: Härtung + Evaluation (Tage 41–52)

- [ ] SUS-Fragebogen vorbereitet und mit 10+ Teilnehmern durchgeführt
- [ ] NASA-TLX für beide Bedingungen (Papier vs. System) erhoben
- [ ] Picking-Zeiten und Fehlerquoten gemessen
- [ ] Setup-Dokumentation getestet (jemand anderes kann System aufsetzen)

---

## Befehle für Claude Code

### Projektstart
```bash
# Repository initialisieren
git init
git add -A
git commit -m "chore: project bootstrap"

# Environment einrichten
cp .env.example .env
# → .env manuell ausfüllen

# Zertifikate generieren
bash infrastructure/scripts/setup-certs.sh 192.168.1.100

# Stack starten
docker compose build
docker compose up -d

# Odoo initialisieren (erste DB erstellen über Web-UI)
# → https://192.168.1.100/odoo/web/database/manager

# Custom Module installieren
# → Odoo Apps → "Update Apps List" → "Quality Alert Custom" installieren

# Seed-Daten laden
python infrastructure/scripts/seed-odoo.py --url http://localhost:8069 --db picking --user admin --api-key <key>
```

### Entwicklung
```bash
# Backend lokal entwickeln (ohne Docker)
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# Tests
cd backend && python -m pytest tests/ -v

# Odoo Shell (für Debugging)
docker compose exec odoo odoo shell -d picking
```

---

## Technische Warnungen und bekannte Fallstricke

### Odoo 18 Feldnamen (Breaking Changes zu Odoo 16!)
```
stock.move.line.quantity     (Odoo 18) — NICHT qty_done (Odoo 16)
stock.picking.move_ids       (Odoo 18) — NICHT move_lines (Odoo 16)
stock.lot                    (Odoo 18) — NICHT stock.production.lot (Odoo 16)
```

### stock.picking.state ist COMPUTED
`state` auf `stock.picking` ist ein berechnetes Feld und kann NICHT direkt geschrieben werden. Statusänderungen nur über Methoden:
- `action_confirm()` — Draft → Waiting/Ready
- `action_assign()` — Check Availability
- `button_validate()` — Validate (kann Wizard-Action zurückgeben!)

### button_validate Wizard-Trap
`button_validate()` gibt manchmal eine `dict` (Wizard-Action) statt `True` zurück. Fix:
```python
context = {"skip_immediate": True, "skip_backorder": True}
result = odoo.call_method("stock.picking", "button_validate", [picking_id])
# Wenn result ein dict ist, Wizard mit Context erneut aufrufen
```

### iOS Safari PWA Kamera-Bugs
- Kamera-Permission wird bei Hash-Change widerrufen (WebKit Bug #215884)
- App als SPA ohne Page Reloads bauen
- `getUserMedia()` MUSS durch User-Geste ausgelöst werden

### iOS Safari SpeechRecognition
- Funktioniert NICHT in PWA-Standalone-Mode
- Auch im Browser unzuverlässig (Duplikate, Timeouts)
- DAHER: Server-Side STT mit Vosk, NICHT Browser-SpeechRecognition

### MediaRecorder Audio-Formate
```javascript
// iOS Safari: audio/mp4 (AAC)
// Chrome Android: audio/webm;codecs=opus
// Backend muss BEIDE Formate akzeptieren
// Vosk akzeptiert beide; ggf. ffmpeg für Konvertierung
```

### n8n hinter Reverse Proxy
`WEBHOOK_URL` MUSS gesetzt sein, sonst enthalten Webhook-URLs `http://localhost:5678` statt der externen URL. Immer setzen auf: `https://<LAN-IP>/n8n/`

### ir.attachment datas-Feld
Erwartet Base64-encoded **String** (nicht Bytes). In Python:
```python
import base64
datas = base64.b64encode(photo_bytes).decode("utf-8")
```

---

## Voice-Kommando-Referenz

| Kontext | Kommando | Intent | Beispiel |
|---------|----------|--------|----------|
| Standort-Check | Ziffern | `check_digit` | "vier sieben" → 47 |
| Standort-Check | "Wiederholen" | `repeat` | System sagt Standort erneut |
| Mengen-Bestätigung | "Bestätigt" | `confirm` | Menge korrekt |
| Mengen-Bestätigung | Zahlwort | `quantity` | "fünf" → Menge 5 |
| Mengen-Bestätigung | "Korrektur" | `problem` | Abweichung melden |
| Allgemein | "Nächster" | `next` | Nächster Pick-Schritt |
| Allgemein | "Zurück" | `previous` | Vorheriger Schritt |
| Allgemein | "Problem" | `problem` | Quality Alert starten |
| Allgemein | "Foto" | `photo` | Kamera öffnen |
| Allgemein | "Pause" | `pause` | Voice-Modus pausieren |
| Allgemein | "Fertig" | `done` | Picking abschließen |
| Allgemein | "Hilfe" | `help` | Verfügbare Kommandos ansagen |

---

## SQL: n8n-Datenbank initialisieren

```sql
-- infrastructure/scripts/init-n8n-db.sql
-- Wird automatisch beim ersten PostgreSQL-Start ausgeführt

CREATE DATABASE n8n;
GRANT ALL PRIVILEGES ON DATABASE n8n TO odoo;
```

---

## Evaluationsplan (Kurzversion)

### Design: Within-Subjects, 10–15 Teilnehmer

- **Bedingung A (Baseline):** Papier-Pickliste, manuelle Qualitätsmeldung
- **Bedingung B (System):** PWA mit Voice + Scan + Foto-Qualitätserfassung
- **Counterbalancing:** Hälfte startet mit A, Hälfte mit B

### Messgrößen

1. **Picking-Zeit pro Zeile** (System-Timestamps)
2. **Fehlerquote** (Post-hoc-Prüfung)
3. **Scan-Erfolgsrate** (System-Log)
4. **Quality-Report-Zeit** (Timestamp)
5. **SUS-Score** (Fragebogen nach Bedingung B)
6. **NASA-TLX Raw** (nach jeder Bedingung)
7. **Semi-strukturiertes Interview** (8 Fragen, 15 Min.)

### Statistik

- Gepaarte t-Tests (oder Wilcoxon bei Nicht-Normalverteilung)
- Effektstärken (Cohen's d)
- 95%-Konfidenzintervalle
- Deskriptive Statistik pro Messgröße
