# n8n-Begründung – Stichpunkte für die Bachelorarbeit

Regel: Text selbst schreiben. Jeder Begriff unten muss in eigenen Worten
erklärbar sein und auf eine Stelle im Repo zeigen.

## Argumentationskette (Kapitel Folgeprozesse)

1. Problem: Pick-Abschluss ist Buchung; Versand ist Folgeprozess mit
   Betriebsentscheidungen (Carrier, Nummer, Aufkleber, Benachrichtigung).
2. Alternative A: alles im Backend. Folge: jede Regeländerung = Code-Deploy
   durch Entwickler.
3. Alternative B: alles in Odoo (QWeb-Report, Automated Action). Folge:
   Logik im ERP, Neustart bei Änderung, keine Ausführungssicht.
4. Entscheidung: n8n als Prozessschicht außerhalb des kritischen Pfads;
   Odoo bleibt System of Record; Backend bleibt Vermittler.
5. Grenze der Entscheidung: n8n trägt nur Entscheidung und Zusammenstellung.
   Rendern und Speichern bleibt in Odoo, weil dort die Daten und ReportLab
   liegen.
6. Beleg: die drei Live-Belege aus `docs/testing/versandlabel-live-beleg.md`.
7. Ehrliche Schwäche: Für vier Regeln ist n8n schwerer als ein `if`. Der
   Nutzen entsteht erst, wenn Regeln sich ändern oder weitere Schritte
   (Mail, Druck) dazukommen. Das ist Ausblick, nicht Beleg.

## Begriffe, je: eigene Erklärung, Frage von Fischer, Stelle im Repo

| Begriff | Mögliche Frage | Wo im Repo |
|---|---|---|
| Transactional Outbox | „Warum nicht direkt einen HTTP-Aufruf nach der Buchung?“ | `odoo/addons/picking_assistant_core/models/shipping_label.py` `api_complete_and_request_label`; `odoo/addons/picking_assistant_integration/models/outbox.py` |
| At-least-once | „Was passiert, wenn n8n das Ereignis zweimal bekommt?“ | `odoo/addons/picking_assistant_integration/models/receipts.py`, Klasse `PickingAssistantEventReceipt`; `callback_id`-Dedup in `PickingAssistantCallbackReceipt` (`_callback_id_unique`) |
| Idempotenz | „Woran erkennt Odoo eine Wiederholung?“ | `event_id` + `payload_fingerprint` in `odoo/addons/picking_assistant_core/models/shipment_event.py`; Sendungsnummer aus `event_id` in `n8n/workflows/shipping-label-v2.json` |
| Fingerprint | „Warum SHA-256 über den Text und nicht über das Objekt?“ | Docstring `odoo/addons/picking_assistant_core/models/shipment_event.py` (Kopfkommentar: „Fingerprint-Regel identisch zu quality.alert.event.builder: SHA-256 ueber genau die Bytes von envelope_text“); `n8n/tests/fingerprint-parity.test.mjs` |
| HMAC-Signatur | „Was schützt die Signatur, was nicht?“ | `n8n/custom-nodes/n8n-nodes-pwr/src/nodes/PwrSignatureGate/PwrSignatureGate.node.ts`; `n8n/custom-nodes/n8n-nodes-pwr/src/nodes/PwrSignedHttpRequest/PwrSignedHttpRequest.node.ts`; `backend/app/services/hmac_keyrings.py` |
| Nonce | „Wozu, wenn schon signiert ist?“ | `odoo/addons/picking_assistant_integration/models/receipts.py`, Modell `picking.assistant.webhook.nonce` (`_reserve`) |
| Lease / Generation | „Was ist, wenn n8n mitten im Lauf abstürzt?“ | `odoo/addons/picking_assistant_integration/models/outbox.py` (`api_lease_due`, `_owned_lease`); Watchdog in `odoo/addons/picking_assistant_integration/models/integration_job.py` |
| Callback | „Warum schreibt n8n nicht direkt nach Odoo?“ | `backend/app/routers/n8n_v2.py`, Funktion `apply_callback`; Allowlist gegen das Instanzregister statt freier Zieladresse (`n8n_v2.py`, Abschnitt zur Pfad- und Instanz-Allowlist) |
| Projektion | „Was ist der Unterschied zwischen Job-Zustand und Feld am Lieferschein?“ | `odoo/addons/picking_assistant_integration/models/receipts.py`, `_PROJECTIONS`; `odoo/addons/picking_assistant_core/models/shipping_label.py`, `_apply_shipping_label` |
| Aggregat / Revision | „Was ist aggregate.revision und warum steht es im Ereignis?“ | `integration_revision` in `odoo/addons/picking_assistant_core/models/shipment_event.py`; `backend/app/models/events.py`, Klasse `EventAggregate` |
| System of Record | „Wer hat Recht, wenn n8n und Odoo sich widersprechen?“ | `docs/ARCHITECTURE.md` (Punkt: „Odoo ist das System of Record für Aufträge, Bestand, Benutzer und Quality …“) |
| Kritischer Pfad | „Was darf ausfallen, ohne dass der Picker steht?“ | Beleg 2 in `docs/testing/versandlabel-live-beleg.md` |
| Webhook | „Was ist der Unterschied zu Polling?“ | `backend/app/services/outbox_dispatcher.py` (lease-getriebene Zustellung statt Abfrage-Schleife; siehe Modul-Docstring „Lease-driven outbox dispatcher“) |
| Verifier | „Wer verhindert, dass jemand in n8n einen Shell-Knoten einbaut?“ | `infrastructure/scripts/workflow_verifier.py`, `POST_ACCEPTANCE_ALLOWED_TYPES`; `NODES_EXCLUDE` in `docker-compose.yml` |

Korrektur gegenüber der ursprünglichen Stichpunktliste: „System of Record“
steht nicht in `README.md`, sondern in `docs/ARCHITECTURE.md`. „Webhook“
wird hier nicht gegen eine im Repo vorhandene, verworfene Polling-Variante
belegt (die existiert nicht als Code oder Kommentar auf diesem Stand), sondern
gegen die tatsächliche Push-Architektur des Dispatchers.

## Sätze, die Fischer als KI-Text lesen würde (vermeiden)

- „Die nahtlose Integration ermöglicht eine effiziente Orchestrierung.“
- „Dies stellt einen signifikanten Mehrwert dar.“
- Alles mit „ganzheitlich“, „innovativ“, „leistungsfähig“ ohne Zahl oder
  Beleg.

Stattdessen: konkreter Fall, konkrete Zahl, konkrete Datei.

## Messwerte, die in den Text gehören

- Zeit letzte Bestätigung bis Anhang (Beleg 1).
- Wartezeit bis Nachlieferung nach n8n-Neustart (Beleg 2).
- Anzahl Zeilen, die für die Regeländerung geändert wurden: 0 im Repo
  (Beleg 3).

## Grenzen (Ergänzung zu den Live-Belegen)

- Cluster-Picking (`backend/app/services/cluster_service.py`,
  `validate_batch`) schließt über `action_done` auf `stock.picking.batch`
  ab, nicht über `api_complete_and_request_label`. Für Cluster-Abschlüsse
  entsteht kein Versandlabel-Ereignis.
- `shipping_label_status = "failed"` entsteht nur durch einen expliziten
  Terminal-Callback mit Status `failed` oder `review_required`. Bleibt ein
  Job endgültig liegen, bleibt der Status auf `pending` stehen; sichtbar
  wird das nur über den Job-Zustand
  (`picking.assistant.integration.job`) und die INCIDENT-Zeile des
  Watchdogs, nicht am Picking selbst.
- Ein Empfänger ohne `country_code` läuft in der Versandregel
  (`n8n/workflows/shipping-label-v2.json`) in den Drittland-Zweig „UPS
  Standard“ statt in einen expliziten Fehlerzweig.

Ehrliche Schwäche: Der Versand-Tab kann „hängt für immer“ (kein
Terminal-Callback kommt je an) nicht von „endgültig fehlgeschlagen“
unterscheiden — beides sieht auf dem Picking wie `pending` bzw. `failed`
je nach Callback aus, nicht nach eigener Diagnose.
