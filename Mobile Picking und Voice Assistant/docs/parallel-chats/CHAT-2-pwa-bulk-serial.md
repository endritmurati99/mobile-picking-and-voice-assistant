# START-PROMPT — Chat 2: PWA Bulk-Confirm Serien-Fix

> Öffne einen neuen Claude-Code-Chat im Projektordner
> `C:\Users\endri\Desktop\Bachelor\Mobile Picking und Voice Assistant`
> und füge den folgenden Text als erste Nachricht ein.

---

Du arbeitest am Bachelorarbeit-Projekt „LogILab Mobile Picking Assistant" (siehe CLAUDE.md im Projektroot). Lies zuerst CLAUDE.md.

**Dein Branch:** Lege `fix/pwa-bulk-serial` an, abzweigend von `feat/seriennummer-bestaetigung`:
```
git checkout feat/seriennummer-bestaetigung && git checkout -b fix/pwa-bulk-serial
```

**Dein Datei-Besitz:** Du darfst NUR `pwa/js/app.js` und `pwa/css/app.css` ändern (plus E2E-Tests unter `e2e/`). Fasse `backend/**` nicht an (paralleler Chat).

**Kontext:** Das Serial-Feature ist gebaut; der Einzel-Scan-Confirm-Flow erfasst Seriennummern korrekt über ein Modal. Im finalen Review wurden zwei PWA-Lücken gefunden.

## Aufgaben

**1. (Wichtig — Review-Issue 1) Bulk-Confirm verschluckt Seriennummern.**
`handleConfirmAll(picking, lines, startIndex)` in `pwa/js/app.js` (~Zeile 2356) bestätigt mehrere Zeilen am Stück und umgeht dabei die Serial-Erfassung komplett. Für serien-getrackte Produkte (Feld `tracking === 'serial'`, vom Backend in der Move-Line-Payload geliefert) geht so die Rückverfolgbarkeit verloren — genau für hochwertige Güter, für die das Feature gedacht ist.
- Erwartetes Verhalten: Beim „Alle bestätigen"-Pfad für jede serien-getrackte Zeile den Serial-Scan/Modal-Flow erzwingen (gleicher Mechanismus wie im Einzel-Confirm), nicht-getrackte Zeilen wie bisher direkt bestätigen.
- Schau dir den Einzel-Confirm-Flow an und wiederverwende dessen Serial-Capture statt zu duplizieren.

**2. (Klein — Issue 5) Modal: Escape-/Backdrop-Handler fehlt.** Das Serial-Modal lässt sich nicht per `Escape` oder Klick auf den Backdrop schließen. Ergänzen, konsistent mit anderen Overlays in der PWA.

## Vorgehen
- XSS-bewusst bleiben (keine ungesäuberten Serials ins DOM).
- E2E testen mit Playwright: `npx playwright test e2e/confirm-flow.spec.js` (ggf. Test für Bulk-Serial-Pfad ergänzen). Falls Docker-Stack nötig: siehe CLAUDE.md / `docs/SETUP.md`.
- Am Ende: Code-Review anfordern (Skill `superpowers:requesting-code-review`), dann committen. **Nicht mergen.**

Hinweis: Ein paralleler Chat baut Cluster-Picking ebenfalls in `app.js` (additiv, neue Funktionen). Halte deine Änderungen lokal auf `handleConfirmAll` + Modal-Handler begrenzt, damit der spätere Merge konfliktarm bleibt.

Berichte am Ende: was geändert, Testergebnis.
