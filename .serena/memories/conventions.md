# Conventions

- Preserve architecture invariants from `mem:mobile/core`: PWA -> FastAPI only, Odoo as source of record, n8n downstream only.
- Keep mobile PWA touch-first; voice/scan must have touch fallback.
- Avoid external cloud services in core workflow; STT/TTS are local/browser fallback.
- Use existing project wrappers/CLIs for Odoo and n8n work from `AGENTS.md`; write operations require explicit user approval.
- Keep code changes scoped to relevant zone. If touching UI, expect Playwright/a11y/visual checks; if touching workflow contracts, expect workflow verification.