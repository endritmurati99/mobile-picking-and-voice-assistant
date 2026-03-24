---
title: Phase 1 - Odoo Datenmodell
tags:
  - phase
  - odoo
  - database
status: in-progress
---

# Phase 1 - Odoo Datenmodell

> [!todo] Current state
> The technical Odoo setup is working.
> The project now uses the restored business database `masterfischer` as the primary database.

Overview: [[00 - Projekt Übersicht]] | Decisions: [[Odoo 18 Entscheidungen]] | Next: [[Phase 2 - Backend und PWA Shell]]

---

## Goal of this phase

At the end of this phase we want:

- A working Odoo 18 database for the project
- Installed custom module `quality_alert_custom`
- Real products and locations available in Odoo
- At least one picking order that can be used by the app
- Working backend authentication against Odoo

---

## Current project reality

- `masterfischer` is now the active business database.
- `picking` still exists as a fallback test database.
- `quality_alert_custom` is installed in `masterfischer`.
- The backend is already connected to `masterfischer`.
- Odoo login works at `http://localhost:8069/web/login?db=masterfischer`.
- Products are present in `masterfischer`.
- There are currently no open pickings in state `assigned`.

---

## What was done today

- Restored the backup `masterfischer_2025-03-25_13-28-44.zip`
- Imported SQL dump into PostgreSQL
- Copied the filestore into the Odoo container
- Extended `dbfilter` so both `picking` and `masterfischer` are visible
- Installed `quality_alert_custom` in `masterfischer`
- Switched the backend to `ODOO_DB=masterfischer`

---

## Admin access

- Odoo admin URL: `http://localhost:8069/web/login?db=masterfischer`
- Current working login: `admin / admin`

> [!warning] Admin path
> For setup and administration use the direct Odoo port `8069`.
> Do not rely on `/odoo/` behind Caddy for admin work.

---

## Open work in this phase

- [ ] Create or release at least one real picking in `masterfischer`
- [ ] Verify that the picking reaches state `assigned`
- [ ] Generate a real API key for the admin user
- [ ] Replace the temporary `.env` fallback with the real API key

---

## Tomorrow's first action

- Open `masterfischer` in Odoo
- Create or release one real transfer / picking
- Check that `/api/pickings` is no longer empty

---

## Related notes

- [[02 - Daily Notes/2026-03-21]]
- [[Phase 2 - Backend und PWA Shell]]
- [[API Dokumentation]]
- [[Odoo 18 Entscheidungen]]
