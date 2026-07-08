# Tech Stack

- Backend: Python FastAPI under `Mobile Picking und Voice Assistant/backend/app`, pytest tests under `backend/tests`.
- Frontend: mobile PWA in plain HTML/CSS/Vanilla JS under `pwa/`; no framework detected.
- UI/e2e: Playwright with `@playwright/test`; a11y via `@axe-core/playwright`.
- Runtime stack: Docker Compose services include Caddy, PostgreSQL, Odoo, FastAPI backend, Whisper/Piper, n8n, and PWA.
- Package metadata is at `Mobile Picking und Voice Assistant/package.json`; Node scripts include Playwright and PWA JS tests.
- Backend test deps install into `backend/.deps/` from `backend/requirements-dev.txt` and tests run with `PYTHONPATH=.deps`.