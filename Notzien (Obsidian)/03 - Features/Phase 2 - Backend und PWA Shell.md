---
title: Phase 2 - Backend und PWA Shell
tags:
  - phase
  - backend
  - pwa
status: in-progress
---

# Phase 2 - Backend und PWA Shell

> [!todo] Current state
> The backend is technically working and the smoke tests pass.
> The next meaningful step is to run the app against a real open picking in `masterfischer`.

Overview: [[00 - Projekt Übersicht]] | API: [[API Dokumentation]] | PWA details: [[PWA Implementierungshinweise]] | Next: [[Phase 3 - Barcode Scanning]]

---

## Verified today

- `GET /api/health` works
- `GET /api/pickings` works technically
- `GET /api/pickings/{id}` works
- `POST /api/pickings/{id}/confirm-line` works
- `POST /api/scan/validate` works
- `python infrastructure/scripts/test-api.py --base-url https://localhost` passes with `7/7`
- One full test picking was completed successfully in the fallback database `picking`

---

## Important technical notes

- The backend is no longer pointed at `picking`; it now uses `masterfischer`.
- In the current Odoo 18 setup, picking completion is tracked through `stock.move.picked`.
- `stock.move.line.quantity_done` is not used in the current backend logic.
- The app currently returns an empty list from `/api/pickings` because `masterfischer` has no open pickings in state `assigned`.

---

## Current endpoint status

| Endpoint | Status |
| -------- | ------ |
| `GET /api/health` | OK |
| `GET /api/pickings` | OK technically, empty on `masterfischer` right now |
| `GET /api/pickings/{id}` | OK |
| `POST /api/pickings/{id}/confirm-line` | OK |
| `POST /api/scan/validate` | OK |
| `POST /api/quality-alerts` | Pending full end-to-end test |
| `POST /api/voice/recognize` | Pending real audio test |

---

## Tomorrow's test order

### First

- [ ] Create or release one real picking in `masterfischer`
- [ ] Reload `https://localhost/`
- [ ] Confirm that the picking appears in the PWA

### Then

- [ ] Open the picking detail screen in the PWA
- [ ] Test one real confirm-line action
- [ ] Test one quality alert from the app
- [ ] Test the voice endpoint with real microphone input

---

## Mobile test checklist

### iOS Safari

- [ ] `https://<LAN-IP>/` opens correctly
- [ ] TLS certificate is trusted
- [ ] Picking list is visible
- [ ] Picking detail opens
- [ ] Quality photo capture works
- [ ] Voice button is visible and usable

### Android Chrome

- [ ] `https://<LAN-IP>/` opens correctly
- [ ] PWA install works
- [ ] Picking list is visible
- [ ] Quality photo capture works
- [ ] Voice permission appears

---

## Risks / open issues

- The app cannot yet be validated on real business flow until `masterfischer` has an open assigned picking.
- The backend still uses a temporary password fallback instead of a real API key.
- The addon source code for `logilab`, `MQTT_Barcode`, and `mqtt_listener` is not yet present in the project tree.

---

## Related notes

- [[02 - Daily Notes/2026-03-21]]
- [[Phase 1 - Odoo Datenmodell]]
- [[Phase 3 - Barcode Scanning]]
- [[Voice Intent Engine]]
- [[PWA Implementierungshinweise]]
