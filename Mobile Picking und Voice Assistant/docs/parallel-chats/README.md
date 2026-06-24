# Parallele Claude-Code-Chats — Koordination

Erstellt: 2026-06-23. Basis-Branch für **alle drei**: `feat/seriennummer-bestaetigung`
(Das Serial-Feature ist noch **nicht** in `main` — main ist 38 Commits zurück.)

## Aufteilung

| Chat | Branch | Besitzt (darf ändern) | Aufgabe |
|------|--------|----------------------|---------|
| 1 | `fix/telemetry-und-cleanup` | `backend/**` | Telemetrie-Metrik-Fix (Review-Issue 2) + Backend-Cleanups (Issue 3, 4) |
| 2 | `fix/pwa-bulk-serial` | `pwa/js/app.js`, `pwa/css/app.css` | Bulk-Confirm Serien-Dropout (Issue 1) + Escape/Backdrop-Handler (Issue 5) |
| 3 | `feat/cluster-picking` | NEUE Module + `pwa/` (Cluster-UI) | Cluster-Picking Feature inkl. Frontend-Design |

## Konfliktpunkt (wichtig)

- **Chat 1 ⟂ Chat 2**: keine gemeinsamen Dateien → echt parallel, kein Konflikt.
- **Chat 2 ↔ Chat 3**: beide fassen `pwa/js/app.js` an. Chat 2 ändert nur `handleConfirmAll`
  + Modal-Handler (lokal). Chat 3 fügt **neue** Cluster-Funktionen/Views additiv hinzu.
  Git merged das meist automatisch; falls nicht, ist die Auflösung trivial.
- **Chat 1 ↔ Chat 3**: Chat 3 legt Backend-Logik in **neue** Dateien
  (`cluster_service.py`, `routers/cluster.py`) → kein Konflikt mit `picking_service.py`.

## Empfohlene Lande-Reihenfolge

1. **Chat 1 + Chat 2** zuerst zurück auf `feat/seriennummer-bestaetigung` mergen
   → damit ist das Serial-Feature fertig & merge-reif für `main`.
2. **Chat 3** (Cluster) danach rebasen/mergen — größeres eigenständiges Feature.

## Quelle der Aufgaben

Final-Review (22.06.) Verdict „With fixes": 2 wichtige Punkte + Minors.
Plan: `docs/superpowers/plans/2026-06-22-seriennummer-bestaetigung.md`
Future-Feature-Specs: `Projekt-Wiki/05 - Future Functions/`
