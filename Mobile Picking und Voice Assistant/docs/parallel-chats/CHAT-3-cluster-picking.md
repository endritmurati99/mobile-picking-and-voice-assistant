# START-PROMPT — Chat 3: Cluster-Picking (Feature + Frontend-Design)

> Öffne einen neuen Claude-Code-Chat im Projektordner
> `C:\Users\endri\Desktop\Bachelor\Mobile Picking und Voice Assistant`
> und füge den folgenden Text als erste Nachricht ein.

---

Du arbeitest am Bachelorarbeit-Projekt „LogILab Mobile Picking Assistant" (siehe CLAUDE.md im Projektroot). Lies zuerst CLAUDE.md.

**Dein Branch:** Lege `feat/cluster-picking` an, abzweigend von `feat/seriennummer-bestaetigung`:
```
git checkout feat/seriennummer-bestaetigung && git checkout -b feat/cluster-picking
```

**Ziel:** Cluster-/Batch-Picking umsetzen — mehrere Pickaufträge gebündelt in einem Rundgang abarbeiten, Mengen pro Ziel-Karton/Auftrag aufteilen. Das hat mein Prof als Feature gewünscht. Es soll vollständig integriert sein: Backend + PWA, **und die PWA soll dafür sauber aussehen** (Frontend-Design anpassen).

**Datei-Besitz:** Backend-Logik in **NEUE** Dateien (`backend/app/services/cluster_service.py`, `backend/app/routers/cluster.py`, eigene Tests) — `picking_service.py` möglichst nicht ändern (paralleler Chat). In der PWA arbeitest du in `pwa/js/app.js` / `pwa/css/app.css`, aber **additiv** (neue Views/Funktionen), da ein paralleler Chat dort `handleConfirmAll` fixt.

## Vorgehen (in dieser Reihenfolge)

**1. Spec lesen & schärfen.** Lies `Projekt-Wiki/05 - Future Functions/Cluster- und Batch-Picking.md`. Prüfe, was Odoo 18 nativ kann (Batch Transfers / `stock.picking.batch`, Cluster-Picking), per Context7/Odoo-Doku — wir wollen möglichst auf Odoo-Bordmitteln aufsetzen statt nachzubauen.

**2. Brainstorming + Plan.** Nutze `superpowers:brainstorming`, um Scope für einen PoC festzulegen (nicht überengineeren — Bachelor-Demo-tauglich). Dann `superpowers:writing-plans` → Plan ablegen unter `docs/superpowers/plans/`. Frag mich bei offenen Produktentscheidungen.

**3. Frontend-Design.** Bevor du UI baust, nutze die Designer-Skills:
   - Bestehendes Designsystem ansehen: `pwa/css/app.css` + `.design/picking-pwa/DESIGN_BRIEF.md`.
   - `frontend-design` (und bei Bedarf `design-tokens` / `design-review`), damit die Cluster-Ansicht zum bestehenden PWA-Look passt (mobil-first, dieselben Tokens/Komponenten). Kein generischer KI-Look — konsistent mit der App.
   - Sinnvolle Cluster-UI: Multi-Auftrags-Auswahl/Batch-Start, Sammel-Pickliste nach Lagerort/Route sortiert, pro Position „in welchen Korb/Karton wie viel", Fortschritt über alle Aufträge.

**4. Umsetzen (TDD).** Backend-Endpoint(s) für Batch laden/fortschreiben + PWA-View. Odoo-18-Felder beachten: `quantity` (nicht `qty_done`), `move_ids` (nicht `move_lines`), JSON-RPC. Demo-DB `masterfischer`, Picker „Max Picker" (uid 7).

**5. Testen.** Backend `pytest`, PWA ggf. Playwright (`e2e/`). Visual-Snapshot für die neue View sinnvoll.

**6. Abschluss.** Code-Review anfordern (`superpowers:requesting-code-review`), committen. **Nicht mergen** — dieses Feature landet als letztes nach den Serial-Fixes.

Berichte nach Schritt 2 (Plan) zurück, bevor du groß implementierst, damit ich Scope/Design abnicken kann.
