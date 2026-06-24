# START-PROMPT — Chat 1: Backend Telemetrie-Fix + Cleanups

> Öffne einen neuen Claude-Code-Chat im Projektordner
> `C:\Users\endri\Desktop\Bachelor\Mobile Picking und Voice Assistant`
> und füge den folgenden Text als erste Nachricht ein.

---

Du arbeitest am Bachelorarbeit-Projekt „LogILab Mobile Picking Assistant" (siehe CLAUDE.md im Projektroot). Lies zuerst CLAUDE.md.

**Dein Branch:** Lege `fix/telemetry-und-cleanup` an, abzweigend von `feat/seriennummer-bestaetigung`:
```
git checkout feat/seriennummer-bestaetigung && git checkout -b fix/telemetry-und-cleanup
```

**Dein Datei-Besitz:** Du darfst NUR unter `backend/**` arbeiten. Fasse `pwa/**` nicht an (das macht ein paralleler Chat). Lege keine neuen Cluster-Module an.

**Kontext:** Das Serial-Feature wurde gebaut und final reviewt (Verdict „With fixes"). Du behebst die Backend-Befunde.

## Aufgaben

**1. (Wichtig — Review-Issue 2) Telemetrie-Metrik kann keine Fehler messen.**
Das `serial_confirm`-Telemetrie-Event wird nur bei Erfolg mit hartkodiertem `success=True` emittiert. Dadurch ist `success_rate` in `backend/app/utils/telemetry.py` (`summarize_serial_events`, ~Zeile 11-21) strukturell nicht aussagekräftig.
- Finde die Emit-Stelle (vermutlich in `backend/app/services/picking_service.py`).
- Emittiere auch **Fehler-Events** (`success=False`) bei fehlgeschlagenem Serial-Schreiben/Confirm — ODER, falls echte Fehlerpfade im PoC nicht sauber erreichbar sind, dokumentiere die Metrik-Grenze explizit (Docstring + kurzer Hinweis für die Thesis-Auswertung in `docs/EVALUATION.md`). Entscheide nach Code-Lage; bevorzugt echte Fehler-Events.

**2. (Klein — Issue 3) Redundante Odoo-Writes** in `backend/app/services/picking_service.py` (Serial-Pfad schreibt ggf. doppelt). Zusammenfassen, Verhalten unverändert.

**3. (Klein — Issue 4) Test-/Schema-Lücken:**
- Whitespace-Only-Serial-Test ergänzen (`backend/tests/test_serial.py` oder `test_picking_service.py`).
- Schema-Konsistenz der Success-Responses prüfen (`recorded_serial` auf allen `success=True`-Pfaden — Normal- und Degraded-Pfad).

## Vorgehen
- Nutze TDD wo sinnvoll (Skill `superpowers:test-driven-development`).
- Tests laufen lassen: `cd backend && python -m pytest tests/test_serial.py tests/test_telemetry.py tests/test_picking_service.py -q`
- Odoo-18-Feldnamen beachten: `quantity` (nicht `qty_done`), `lot_name` fürs Serial.
- Am Ende: Code-Review anfordern (Skill `superpowers:requesting-code-review`), dann committen. **Nicht mergen** — ich merge nach Lande-Reihenfolge.

Berichte am Ende: was geändert, Testergebnis, ob Issue 2 als Fehler-Events oder als dokumentierte Grenze gelöst wurde.
