# Mobile Picking und Voice Assistant

> Bachelor thesis proof-of-concept — hybrid, voice-assisted mobile picking system built on Odoo 18 Community, FastAPI, n8n and a Progressive Web App. Runs entirely on-premises; no cloud or internet required.

---

## What it does

Warehouse pickers open the PWA on any mobile device, select their profile, and work through picking orders step by step. Each position can be confirmed by barcode scan, touch or voice command. Exceptions — damaged goods, stock shortages — trigger Quality Alerts or replenishment transfers in Odoo automatically via n8n.

```
Barcode scan / Touch / Voice
        ↓
   FastAPI (Python 3.12)
        ↓
   Odoo 18 JSON-RPC  ←→  n8n Orchestrator
        ↓
   PWA (TTS confirmation)
```

---

## Architecture at a glance

| Layer | Technology | Status |
|-------|------------|--------|
| Mobile PWA | HTML5 · Web Speech API · HID Scanner | ✅ Production-ready |
| HTTPS Proxy | Caddy 2 + mkcert | ✅ Running |
| App Backend | FastAPI 0.111 · Python 3.12 | ✅ Production-ready |
| STT Engine | faster-whisper (local, no cloud) | ✅ Integrated |
| Orchestrator | n8n (CQRS flows, async + sync) | 🔵 Flows built, import pending |
| ERP | Odoo 18.0 Community | ✅ Configured |
| Database | PostgreSQL 16 | ✅ Running |
| Quality Module | `quality_alert_custom` (custom addon) | ✅ Stable |

---

## Key features

### Voice Picking
- Whisper STT running locally — no data leaves the network
- 3-stage intent engine: exact match → regex → Levenshtein fuzzy
- Surface-aware intents (`VoiceSurface.LIST` vs `VoiceSurface.DETAIL`)
- `POST /api/voice/assist` — context-aware TTS answers enriched with Odoo stock data and Obsidian knowledge notes
- Separate async `shortage-reported` event when a picker reports missing stock

### Picking Workflow
- Soft claiming with heartbeats — two devices cannot work the same order simultaneously
- Idempotency keys on all write requests — no double bookings on retry or reconnect
- Guided line-by-line flow with route optimisation (zone + slot sort)
- Product images on demand via `GET /api/products/{id}/image` (cached, JPEG/PNG auto-detected)

### n8n CQRS Integration
All n8n flows share a common envelope (`event_name`, `schema_version`, `correlation_id`, `occurred_at`, `picker`, `device_id`, `picking_context`, `payload`):

| Workflow | Mode | What it does |
|----------|------|--------------|
| `pick-confirmed` | async | Fires on picking completion |
| `quality-alert-created` | async | Triggers AI assessment, writes back via FastAPI |
| `voice-exception-query` | sync | Answers voice exceptions with AI context |
| `shortage-reported` | async | Creates real internal replenishment transfer in Odoo |

n8n writes back to Odoo **only** through internal FastAPI command endpoints — never directly.

### Security
- Strict picker validation: only `active=True, share=False` Odoo users allowed
- `X-N8N-Callback-Secret` with `secrets.compare_digest` (constant-time, no timing leak)
- All write endpoints require `Idempotency-Key` header
- Odoo replenishment transfer is idempotent — safe for n8n retries

---

## Project structure

```
Mobile Picking und Voice Assistant/
├── backend/               # FastAPI application
│   ├── app/
│   │   ├── routers/       # pickings, voice, quality, obsidian, n8n_internal
│   │   ├── services/      # picking_service, mobile_workflow, n8n_webhook, whisper_client
│   │   ├── models/        # Pydantic models (n8n, obsidian)
│   │   └── schemas/
│   └── tests/             # 50+ pytest tests (37 backend + 13 voice)
├── pwa/                   # Progressive Web App
│   ├── js/                # app.js, api.js, voice.js, scanner.js, ui.js, voice-runtime.mjs
│   ├── css/
│   ├── index.html
│   └── sw.js              # Service Worker
├── odoo/
│   └── addons/
│       ├── picking_assistant_core/     # Claim fields, idempotency log, replenishment API
│       └── quality_alert_custom/       # Quality alert model + Kanban + Chatter
├── n8n/
│   └── workflows/         # pick-confirmed, quality-alert-created, voice-exception-query, shortage-reported
├── e2e/                   # Playwright end-to-end tests + visual baselines
├── infrastructure/
│   └── scripts/           # seed-odoo.py, verify-workflows.py, migrate-product-images.py
└── docker-compose.yml
```

---

## Quick start

### Prerequisites
- Docker Desktop
- `mkcert` installed locally (for HTTPS certificates)

### 1. Clone and configure

```bash
git clone https://github.com/endritmurati99/mobile-picking-and-voice-assistant.git
cd "mobile-picking-and-voice-assistant/Mobile Picking und Voice Assistant"
cp .env.example .env
# Edit .env — set ODOO_URL, ODOO_DB, ODOO_PASSWORD, N8N_CALLBACK_SECRET, WHISPER_MODEL
```

### 2. Generate local certificates

```bash
mkcert -install
mkcert <your-lan-ip>
# Copy the generated cert/key files to infrastructure/certs/
```

### 3. Start the stack

```bash
docker compose up -d
```

### 4. Install Odoo addons

```bash
docker compose exec odoo odoo -c /etc/odoo/odoo.conf \
  -d masterfischer --http-port=8070 \
  -i picking_assistant_core,quality_alert_custom \
  --stop-after-init
docker compose restart odoo
```

### 5. Seed test data (optional)

```bash
python infrastructure/scripts/seed-odoo.py --bom-mode
```

### 6. Open the PWA

```
https://<your-lan-ip>/
```

---

## Services

| Service | URL |
|---------|-----|
| PWA | `https://<LAN-IP>/` |
| API docs | `https://<LAN-IP>/api/docs` |
| Odoo | `http://<HOST>:8069` |
| n8n | `https://<LAN-IP>/n8n/` |

---

## Running tests

```bash
# Backend unit + integration tests
cd "Mobile Picking und Voice Assistant"
pip install -r backend/requirements.txt
pytest backend/tests/ -v

# PWA unit tests
node --experimental-vm-modules node_modules/.bin/jest pwa/js/tests/

# End-to-end (Playwright)
npx playwright test
```

---

## Environment variables (`.env`)

| Variable | Description |
|----------|-------------|
| `ODOO_URL` | Odoo base URL, e.g. `http://odoo:8069` |
| `ODOO_DB` | Active database name (`masterfischer`) |
| `ODOO_PASSWORD` | Odoo admin password |
| `N8N_WEBHOOK_BASE_URL` | n8n webhook base URL |
| `N8N_CALLBACK_SECRET` | Shared secret for internal n8n callbacks |
| `WHISPER_MODEL` | Whisper model size (`tiny` / `base` / `small`) |
| `OBSIDIAN_PATH` | Path to Obsidian vault (for context search) |
| `MOBILE_CLAIM_TTL_SECONDS` | Claim expiry in seconds (default: 120) |
| `MOBILE_IDEMPOTENCY_TTL_SECONDS` | Idempotency log retention (default: 86400) |

---

## Context

This project was built as a **Bachelor thesis proof of concept** for the LogILab at Hochschule Fulda. The goal was to validate whether a fully local, voice-assisted picking assistant is feasible on standard mobile hardware without cloud dependencies.

**Research questions:**
- Can Whisper STT run fast enough on-premises for warehouse use?
- Does a PWA on iOS Safari / Android Chrome satisfy warehouse UX requirements?
- Can n8n orchestrate exception handling (quality alerts, replenishment) without blocking the picking flow?

All three questions were answered positively in the current build.

---

## License

Academic / internal use. No production deployment without explicit permission.
