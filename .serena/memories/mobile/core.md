# Mobile Picking und Voice Assistant Core

- Module root: `Mobile Picking und Voice Assistant/`.
- Architecture invariant: PWA talks only to FastAPI `/api/*`; no direct PWA calls to Odoo or n8n.
- Odoo remains system of record for products, stock, pickings, partners, and business state. No shadow business database.
- n8n is downstream orchestration only; not in picking/voice hot path.
- Main zones: `backend/` FastAPI and Odoo JSON-RPC bridge; `pwa/` mobile Vanilla JS/CSS/HTML; `e2e/` Playwright/a11y/visual tests; `odoo/` custom add-ons/config; `n8n/workflows/` workflow JSON; `infrastructure/` Docker/Caddy/seed/smoke scripts; `docs/` technical docs.
- For Odoo/n8n work, read `AGENTS.md`: local CLI-first, read/auth before writes, prefer `--json`.