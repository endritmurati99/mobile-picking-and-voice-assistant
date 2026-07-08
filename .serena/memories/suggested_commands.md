# Suggested Commands

Run from `Mobile Picking und Voice Assistant/` unless noted.

- `git -C /mnt/c/Users/endri/Desktop/Bachelor status --short` before edits.
- `make install-backend-deps` installs Python test deps into `backend/.deps/`.
- `make install-ui-deps` installs npm deps and Chromium for Playwright; Makefile uses Windows command shims `npm.cmd` and `npx.cmd`.
- `make up`, `make down`, `make logs`, `make logs-backend`, `make logs-odoo` control the Docker stack.
- `make seed` runs `infrastructure/scripts/seed-odoo.py` against local Odoo using `.env` values.
- `npm run test:voice` runs PWA JS unit tests.
- `npm run test:ui`, `npm run test:a11y`, `npm run capture:visual` are direct Node alternatives to Make targets.
- `make test`, `make test-ui`, `make test-visual`, `make test-visual-diff`, `make test-a11y`, `make verify-workflows`, `make verify-stack` cover individual verification layers.