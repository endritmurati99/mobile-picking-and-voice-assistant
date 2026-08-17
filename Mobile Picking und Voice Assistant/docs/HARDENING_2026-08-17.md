# Härtungsrunde 2026-08-17

Ausgelöst durch ein vollständiges Review (5 statische Audits + Live-Pentest über
Caddy und Windows-Chrome gegen den laufenden Stack). Jeder Fix ist unten mit
Ursache, Änderung und **Live-Beleg** dokumentiert. Teststand danach:
Backend **1086** grün, PWA **47** node-Tests grün.

Verifiziert am laufenden Stack (11 Container healthy): PWA-Login im Browser als
`lena.lager`, Odoo-Admin-Web-UI, n8n (beide Workflows aktiv, Webhook
`quality-assessment-v2` registriert → unsigniert 403 durch die Signature-Gate),
Backend- und Odoo-Logs fehlerfrei.

---

## Behobene Bugs

### 1. Voice `confirm_all` war tot (KRITISCH)
`pwa/js/app.js` rief `buildReadbackPrompt`, ohne es zu importieren. Jeder Voice-
`confirm_all` und jeder `confirm` mit Confidence in `[0.73, 0.90)` warf eine
`ReferenceError`, die als unhandled promise rejection lautlos verschwand — der
Picker hörte und sah nichts. Das war der Livebug „confirm_all erkannt, aber
nicht ausgeführt".

- **Fix:** `buildReadbackPrompt` in den Import aus `voice-runtime.mjs` aufgenommen.
- **Zusatz-Härtung:** Alle Intent-Dispatches laufen jetzt durch `_dispatchIntent`
  (`voice.js`), das Fehler loggt UND dem Picker als hörbares Signal meldet.
  Bisher machte genau die fehlende `.catch()` diese Bug-Klasse unsichtbar.
- **Regressionstest:** `pwa/js/tests/app-imports.test.mjs` — liest `app.js` als
  Quelltext und schlägt fehl, sobald ein aus `voice-runtime.mjs` benutzter Name
  nicht importiert ist.

### 2. Login-401 war ein getarnter Origin-Reject
`PWA_ORIGINS` stand über `LAN_HOST` auf genau eine LAN-IP. Die Login-Route fasste
`CsrfFailed` (Origin nicht erlaubt) und `AuthenticationFailed` (Passwort falsch)
zu **einem** 401 „Anmeldung fehlgeschlagen" zusammen. Ein Zugriff über
`https://localhost` — dessen Origin nicht auf der Liste stand — sah damit aus wie
ein Passwortfehler.

- **Fix a** (`backend/app/routers/auth.py`): `CsrfFailed` gibt jetzt **403
  „Origin ist nicht erlaubt"** zurück, getrennt von `AuthenticationFailed` (401).
- **Fix b** (`docker-compose.dev.yml`): Das Dev-Overlay erlaubt zusätzlich
  `https://localhost`. Produktion bleibt auf genau der LAN-Origin (Overlay wird
  dort nicht geladen); beide Origins sind HTTPS, die Produktions-Validierung
  bliebe erfüllt.
- **Live-Beleg:** fremder Origin → **403** `Origin ist nicht erlaubt`;
  `https://localhost` → **200** mit Session.

### 3. IDOR — Heartbeat legte Claims an
`api_heartbeat_mobile` (Odoo) war identisch zu `api_claim_mobile` und legte einen
Claim an, wenn keiner aktiv war. Da `confirm-line` den Heartbeat als **einzigen**
Ownership-Check nutzt, konnte ein nie beanspruchter Auftrag — oder nach
Lease-Ablauf der Auftrag eines anderen Pickers — gebucht werden. Live belegt:
Heartbeat von Max auf den unbeanspruchten pick 60 meldete `status:claimed by Max`.

- **Fix** (`odoo/.../picking_assistant.py`): Heartbeat verlängert nur noch einen
  **bereits gehaltenen, aktiven** Claim (`_has_active_owned_claim`). Fehlt der,
  meldet er `status:"missing"` und legt nichts an. Claims entstehen nur über
  `api_claim_mobile`.
- **Fix** (`backend/.../mobile_workflow.py`): `heartbeat_picking` wirft bei
  `missing` einen `ClaimConflictError` → confirm-line weist ab (409), der Client
  zeigt den Neu-Beanspruchen-Dialog. `claim`/`release` bleiben conflict-only
  (Release ohne Claim ist ein No-op).
- **Tests:** zwei neue in `test_mobile_workflow_service.py`.
- **Live-Beleg:** Heartbeat auf unbeanspruchten pick 48 → **409** „Kein aktiver
  Claim"; Happy-Path claim→heartbeat(200 claimed)→release weiterhin grün.

### 4. Idempotency-Replay/Fehl-ID → 500
Ein Claim auf eine nicht (mehr) existente Kommissionierungs-ID mit
Idempotency-Key schrieb eine baumelnde Fremdschlüssel-Referenz in die
Idempotency-Tabelle; PostgreSQL brach den INSERT ab, und die Odoo-Meldung
(„Another model is using the record you are trying to delete") kam als roher 500
beim Client an.

- **Fix** (`odoo/.../idempotency.py`): `picking_id` ist reine Metadaten
  (`ondelete="set null"`). `api_reserve_request` prüft die Existenz einmal und
  speichert sonst `False`. Die Reservierung gelingt, der nachgelagerte
  claim/heartbeat meldet sauber `missing`.
- **Live-Beleg:** Claim auf pick 99999 → vorher 500/500, jetzt **200/200** mit
  `{"status":"missing"}`, Replay liefert die gecachte Antwort.

---

## Zusätzliche Härtung

### 5. `.env.example`: Grace-Mode-Falle entschärft
`MOBILE_HEADER_GRACE_MODE=true` wurde in `.env.example` ausgeliefert. Wer die
Datei nach `.env` kopiert (der dokumentierte Setup-Schritt), hätte die
Session-Auth komplett abgeschaltet. Zeile auskommentiert + Warnkommentar. In
Produktion ist der Wert ohnehin fail-closed verboten.

### 6. Globaler `OdooAPIError`-Handler → sauberer 502
Die Browser-Router `pickings.py`/`voice.py` fingen `OdooAPIError` nicht ab — ein
Odoo-Timeout/5xx/eine baumelnde Referenz kam als 500 mitsamt Stacktrace an. Neuer
`exception_handler` in `main.py` übersetzt jeden ungefangenen `OdooAPIError` in
einen 502 mit umlautfester Meldung, ohne Interna zu leaken. Handler statt
try/except pro Route: keine Route kann ihn vergessen. Test in
`test_mobile_routes.py`.

---

## Offen (bewusst nicht in dieser Runde — brauchen Produktentscheidung/Test)

- **`require_roles()` verdrahten.** Die Primitive existiert, wird aber nirgends
  benutzt → keine echte Rollentrennung (picker vs supervisor). Sinnvolle Gates
  (Cluster-Validate, Quality-Alert-Abschluss, Demo-Toggles) setzen voraus, dass
  festgelegt wird, **wer** supervisor ist — die Demo-Picker haben aktuell nur
  `picker`. Ein Gate ohne diese Zuordnung würde den Demo-Fluss sperren.
- **`n8n/workflows/error-trigger.json`** ist tot: nutzt `$env.N8N_CALLBACK_SECRET`,
  während `N8N_BLOCK_ENV_ACCESS_IN_NODE=true` gesetzt ist; zielt auf gelöschte
  v1-Routen. Fehler-Benachrichtigungen laufen ins Leere. Reparatur braucht einen
  n8n-Testlauf (Credential-Binding statt `$env`, v2-Callback-Route).
- **PWA-Feinschliff:** Touchziele < 48px (`.qa-photo-remove` 28px), Fehler-/
  Erfolgstext auf die `-ink`-Kontrastvarianten, Offline-Write-Queue (aktuell
  Stub). Kosmetik/UX, kein Sicherheitsrisiko.
- **Zwei konkurrierende Voice-Confirm-State-Machines** (`voice.js` vs `app.js`)
  und drei Ja/Nein-Wortlisten auf eine Definition vereinheitlichen.
