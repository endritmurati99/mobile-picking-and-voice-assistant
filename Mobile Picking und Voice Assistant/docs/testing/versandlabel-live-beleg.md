# Versandlabel über n8n – Live-Belege vom 03.09.2026

## Testlauf

Alle Läufe fanden am 03.09.2026 im Worktree `feature/versandlabel-n8n` statt.
Docker Desktop lief, Compose-Projekt `versandlabel`. Vor dem Odoo-Lauf wurde
die Wegwerf-Datenbank `picking_test` explizit gedroppt (siehe Task-1-Bericht),
weil `make test-odoo` sie bei einem bereits installierten Stand sonst nicht
neu aufsetzt und ein Lauf ohne Drop irreführend grün wäre.

| Suite | Befehl | Ergebnis |
|---|---|---|
| Backend | `make test` | 1079 bestanden, 27 fehlgeschlagen (siehe Anmerkung unten) |
| Odoo | `make test-odoo` | 301 bestanden in den drei Projektmodulen (`picking_assistant_core` 59, `picking_assistant_integration` 180, `quality_alert_custom` 62); 4 vorbestehende Odoo-Kern-Fehlschläge und 2 vorbestehende Idempotenz-Race-Fehlschläge, beide unabhängig von diesem Task |
| n8n | `make test-n8n` | 20 bestanden, 0 fehlgeschlagen |
| Infrastruktur | `make test-infra` | 156 bestanden, 1 vorbestehender Fehlschlag (`test_no_app_uses_cluster_bootstrap_role_in_compose`, siehe Anmerkung unten) |
| Workflow-Verträge | `make verify-workflows` | „Workflow validation passed.“ – 3 Workflow-Dateien gegen 7 n8n-Callback-Endpunkte geprüft, kein Befund im v2-Vertrag; 2 vorbestehende Warnungen (Webhook-Pfade `quality-assessment-v2` und `shipping-label-v2` werden aktuell nicht über `n8n.fire(...)` ausgelöst) |

**Anmerkung zu `make test`:** Das Makefile lädt `.env` global mit
`-include .env` und `export` in jede Recipe. Dadurch stehen beim Aufruf über
`make` Secrets sowohl als direkter Wert (aus `.env`) als auch als Datei
(unter `infrastructure/secrets/`) im Prozess bereit; der fail-closed-Guard
`read_secret()` (`backend/app/config.py`) weist das als Konfigurationsfehler
zurück – korrektes Verhalten des Guards, aber ein Artefakt des
`make`-Aufrufs, nicht des in diesem Task geänderten Codes. Derselbe
Testlauf direkt im Backend-Ordner, ohne den `.env`-Export von `make`
(`cd backend && PYTHONPATH=.deps python -m pytest -p pytest_asyncio tests/ -v`),
läuft vollständig grün: 1106 von 1106 bestanden. Dieser Task ändert nur
Dokumentation und berührt `backend/app/config.py` nicht.

**Anmerkung zu `make test-infra`:** Der eine Fehlschlag
(`test_db_role_scripts.py::test_no_app_uses_cluster_bootstrap_role_in_compose`)
ist laut Auftrag bekannt und vorbestehend; er wird hier nur ehrlich
protokolliert, nicht behoben.

## Beleg 1: Label erscheint nach Pick-Abschluss

Durchführung: Stack läuft (`make up`), Seed gefahren. In der PWA einen
offenen Auftrag mit einem österreichischen Kunden vollständig picken.

Schritte für den Beleg:

1. Auftrag mit österreichischem Kunden in der PWA öffnen und vollständig
   picken.
2. Sofort danach:
   ```bash
   docker compose logs --since 2m backend | grep -i "shipment\|outbox\|dispatch"
   docker compose logs --since 2m n8n | grep -i "shipping-label-v2"
   ```
3. In Odoo den zugehörigen Lieferschein öffnen, Reiter „Versand“ und Chatter
   prüfen.
4. n8n-Ausführung des Workflows „Shipping Label v2“ öffnen.

Auftrag: [ ] ____________________
Kunde: [ ] ____________________
Land: [ ] ____________________
Gewicht: [ ] ____________________ kg
Gewählter Carrier: [ ] ____________________
Sendungsnummer (`PWR-DPD-...`): [ ] ____________________
Zeit von letzter Bestätigung (Pick-Abschluss in der PWA) bis Anhang im
Chatter: [ ] ____________________ s

Logzeilen (Backend, `shipment`/`outbox`/`dispatch`):
```
[ ] ____________________
```

Logzeilen (n8n, `shipping-label-v2`):
```
[ ] ____________________
```

Screenshots (unter `docs/testing/screenshots/versandlabel/` ablegen und hier
verlinken):
- [ ] Reiter „Versand“ (Status „Label erzeugt“, Carrier „DPD Classic“,
  Sendungsnummer): `docs/testing/screenshots/versandlabel/beleg1-reiter-versand.png`
- [ ] Chatter mit Anhang `Versandlabel WH/OUT/000xx.pdf`:
  `docs/testing/screenshots/versandlabel/beleg1-chatter.png`
- [ ] Heruntergeladenes PDF (Ablage, kein Screenshot nötig, Pfad notieren):
  [ ] ____________________
- [ ] n8n-Ausführung, grüner Pfad:
  `docs/testing/screenshots/versandlabel/beleg1-n8n-execution.png`

## Beleg 2: n8n ausgefallen, Picker arbeitet weiter

Durchführung:

1. n8n stoppen:
   ```bash
   docker compose stop n8n
   ```
2. Weiteren Auftrag in der PWA komplett picken. Erwartung: PWA meldet
   „Auftrag abgeschlossen.“, Lieferschein in Odoo `done`, Reiter „Versand“
   zeigt „Label angefordert“.
3. Zeitpunkt des Pick-Abschlusses notieren.
4. n8n wieder starten:
   ```bash
   docker compose start n8n
   ```
5. Innerhalb der Dispatcher-Wiederholung (Backoff-Tabelle aus der Outbox)
   beobachten, bis das Label nachkommt:
   ```bash
   docker compose logs -f backend | grep -i outbox
   ```
6. Zeitpunkt notieren, zu dem der Reiter „Versand“ auf „Label erzeugt“
   wechselt.

Auftrag: [ ] ____________________
Zeit Pick-Abschluss (n8n aus): [ ] ____________________
Status unmittelbar danach in Odoo: „Label angefordert“ [ ]
Zeit n8n-Neustart: [ ] ____________________
Zeit, zu der das Label nachkommt: [ ] ____________________
Wartezeit bis Nachlieferung nach n8n-Neustart: [ ] ____________________ s

Logzeilen des Dispatchers mit Zeitstempel (Backoff-Wiederholung, Erfolg):
```
[ ] ____________________
```

Screenshots:
- [ ] Odoo-Reiter „Versand“ vorher (Status „Label angefordert“):
  `docs/testing/screenshots/versandlabel/beleg2-vorher.png`
- [ ] Odoo-Reiter „Versand“ nachher (Status „Label erzeugt“):
  `docs/testing/screenshots/versandlabel/beleg2-nachher.png`

## Beleg 3: Carrier-Regel ohne Code-Deploy geändert

Durchführung:

1. In der n8n-Oberfläche den Workflow „Shipping Label v2“ öffnen, Knoten
   „If Weight Under 2kg“ öffnen, Grenze von `2` auf `0.01` setzen, speichern.
2. Einen leichten deutschen Auftrag picken. Erwartung: Carrier
   „DHL Paket 5 kg“ statt „DHL Paket“.
3. Grenze danach zurücksetzen und den Workflow erneut aus
   `n8n/workflows/shipping-label-v2.json` importieren, damit Repo und
   Instanz wieder übereinstimmen.

Hinweis: Diese Änderung passiert in der n8n-Instanz, nicht im Repo. Genau
das ist der Beleg. Der Verifier (`infrastructure/scripts/verify-workflows.py`,
aufgerufen über `make verify-workflows`) prüft beim nächsten Import die
Datei aus dem Repo, nicht den Live-Zustand der n8n-Instanz. Eine Live-Änderung
kommt also nicht dauerhaft am Verifier vorbei: Sobald der Workflow erneut aus
dem Repo importiert wird – etwa bei einem Deployment oder einer erneuten
Provisionierung –, gilt wieder der Stand aus `shipping-label-v2.json`, und der
nächste `make verify-workflows`-Lauf prüft diesen Stand, nicht die
zwischenzeitliche Live-Änderung.

Geänderter Knoten: „If Weight Under 2kg“
Grenze vorher: `2`
Grenze während des Tests: `0.01`
Auftrag: [ ] ____________________
Gewicht: [ ] ____________________ kg
Carrier vorher (bei Grenze `2`): „DHL Paket“
Carrier während des Tests (bei Grenze `0.01`): [ ] ____________________
Rücksetzung durchgeführt (Grenze zurück auf `2`, Workflow neu importiert):
[ ] ja, um [ ] ____________________ Uhr

Anzahl Zeilen, die im Repo für die Regeländerung geändert wurden: 0
(die Änderung fand ausschließlich in der laufenden n8n-Instanz statt).

Screenshots:
- [ ] Geänderter Knoten „If Weight Under 2kg“ mit Grenze `0.01`:
  `docs/testing/screenshots/versandlabel/beleg3-knoten.png`
- [ ] Lieferschein mit Carrier „DHL Paket 5 kg“:
  `docs/testing/screenshots/versandlabel/beleg3-lieferschein.png`

## Grenzen

- Cluster-Picking (`backend/app/services/cluster_service.py`,
  `validate_batch`) schließt den Batch über `action_done` auf
  `stock.picking.batch` ab, nicht über `api_complete_and_request_label` auf
  `stock.picking`. Für Cluster-Abschlüsse entsteht dadurch kein
  `shipment.parcel.ready.v1`-Ereignis und kein Versandlabel.
- Kein Drucker, keine Mail, kein Gefahrgut, keine echte Sendungsnummer.
