# Seriennummern- und Retouren-Haertung

Stand: 2026-07-03

## Ziel

Seriennummern sind konkrete physische Exemplare eines Produkts, nicht Artikelnummern. Beim Picking muss fuer `tracking=serial` die ausgelieferte Instanz erfasst werden, damit Retouren spaeter gegen genau diese ausgelieferte Instanz verglichen werden koennen.

Beispiel: Ausgeliefert wird ein Brick 2x2 mit Seriennummer `123`. In der Retoure kommt ein Brick 2x2 mit Seriennummer `245` zurueck. Der Abgleich muss melden: `245` ist unbekannt/falsches Exemplar, `123` fehlt.

## Umgesetzte Haertung

- [x] PWA erzwingt den Seriennummern-Dialog fuer `tracking=serial`.
- [x] Escape/Backdrop/leerer Wert bestaetigen serialisierte Produkte nicht mehr.
- [x] HID-Scanner ignoriert Eingabefelder, damit ein Serial-Scan im Modal nicht parallel als Produktbarcode laeuft.
- [x] Einzel-Picking nimmt `serial_number` in den serverseitigen Idempotenz-Fingerprint auf.
- [x] Einzel-Picking und Cluster-Picking nutzen dieselbe Backend-Serial-Validierung.
- [x] Backend akzeptiert bei `tracking=serial` nur Menge `1`.
- [x] Backend validiert, dass die Seriennummer als `stock.lot` zum Produkt existiert.
- [x] Backend prueft, dass fuer `product_id + lot_id + source location` Bestand in `stock.quant` vorhanden ist.
- [x] Backend schreibt bei `tracking=serial` `lot_id`, nicht freie Phantom-Seriennummern per `lot_name`.
- [x] Backend stellt `POST /api/pickings/{picking_id}/returns/reconcile` bereit.
- [x] Versand-Serials werden read-only aus `stock.move.line.lot_id`/`lot_name` gelesen und mit gescannten Retouren-Serials ueber `reconcile_serials()` verglichen.
- [x] Projekt-Wiki beschreibt Seriennummern als Produkt-Instanzen und dokumentiert das Retouren-Beispiel.

## Offene Folgearbeiten

- [ ] Persistenz/Workflow fuer Abweichungen festlegen: Quality Alert, Chatter-Note, n8n-Event oder Supervisor-Queue.
- [ ] Wiederverwendungs-/Duplikatpruefung gegen bereits ausgelieferte Seriennummern ergaenzen.
- [ ] Live-Odoo-Test mit Produkt `tracking=serial`, vorab angelegtem `stock.lot`, Quellbestand und PWA-Scanner durchfuehren.
- [ ] Optionales GS1-/AI-Parsing fuer Serial-Barcodes ergaenzen (z. B. AI `21` Serial, AI `10` Lot).

## Prueffokus

- Serial-Produkt ohne Seriennummer: kein Odoo-Write.
- Serial-Produkt mit Menge > 1: kein Odoo-Write.
- Unbekannte Seriennummer: kein Odoo-Write.
- Seriennummer anderes Produkt oder anderer Lagerort: kein Odoo-Write.
- Richtige Seriennummer: ein Write auf `stock.move.line` mit `quantity` und `lot_id`.
- Cluster-Picking: falscher Karton blockiert vor Serial-Write; richtiger Karton plus Serial schreibt.
- Idempotenz: gleicher `Idempotency-Key` mit anderer Seriennummer wird als anderer Request erkannt.
