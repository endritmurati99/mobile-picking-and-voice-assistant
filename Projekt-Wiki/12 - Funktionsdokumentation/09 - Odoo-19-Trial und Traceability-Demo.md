---
title: "Odoo-19-Trial und Traceability-Demo"
tags: [funktionsdoku, odoo19, traceability, stueckliste, seriennummer, migration]
status: dokumentiert
stand: 2026-07-04
---

# Odoo-19-Trial und Traceability-Demo

> [!abstract] Kurzfassung
> Am 2026-07-04 wurde der aktuelle Odoo-18-Datenstand `masterfischer` in eine getrennte Odoo-19-Trial-Datenbank `masterfischer_o19_trial` migriert und in der PWA als Instanz `Odoo 19 Trial` angebunden. Auf dieser Trial-DB kann die Traceability-Demo zur Laufzeit umgeschaltet werden: alle 3x3-Kombinationen aus Endprodukt-Tracking (`none`, `lot`, `serial`) und Komponenten-Tracking (`none`, `lot`, `serial`). Die Live-/Default-Instanz bleibt bewusst Odoo 18.

## 1. Aktueller technischer Stand

| Bereich | Stand am 2026-07-04 |
| --- | --- |
| Live-Odoo | `local`, Odoo `18.0-20260119`, Host-Port `8069`, DB `masterfischer` |
| Zweite Odoo-18-Instanz | `lager-2`, Odoo 18, Host-Port `8070`, DB `lager2`, Batch-Modul `stock_picking_batch` installiert |
| Trial-Odoo | `o19-trial`, Odoo `19.0-20260630`, Host-Port `8100`, DB `masterfischer_o19_trial` |
| PWA | `https://localhost/`, Instanz-Umschalter rechts oben |
| Login Odoo | lokal fuer Demo: `admin / admin` |
| Sichtbare PWA-Daten in Trial | 21 offene Pickings, 2 Cluster-Vorschlaege |
| Traceability-Status | Demo-Schalter aktiv, aktueller Modus: `Komponenten Lot` |
| Demo-Daten | 11 BOM-Endprodukte, 30 BOM-Komponenten |

Die Trial-DB ist eine Arbeits-/Demo-Kopie. Sie ist nicht der Live-Cutover. Das ist Absicht: Tracking-Aenderungen an Produkten sind echte Odoo-Stammdatenaenderungen und duerfen nicht versehentlich auf der Live-DB getestet werden.

## 2. Warum die Komponenten im Fokus stehen

Fachliche Korrektur vom 2026-07-04: Die rueckverfolgbaren Nummern sollen nicht primaer auf dem fertigen Endprodukt liegen, sondern auf den Bauteilen aus der Stueckliste. Ein fertiges Set entsteht aus mehreren Komponenten; fuer die Rueckverfolgbarkeit ist deshalb wichtig:

1. Welches Endprodukt / Kit wird gepickt?
2. Aus welchen BOM-Komponenten besteht es?
3. Welche konkrete Charge oder Seriennummer einer Komponente wurde verwendet?
4. In welchem Auftrag / Batch wurde diese Komponente ausgeliefert?

Deshalb erzeugt der Demo-Service getrennte Produktmengen:

- **BOM-Endprodukte**: Produkte aus `mrp.bom.product_id` bzw. `mrp.bom.product_tmpl_id`.
- **BOM-Komponenten**: Produkte aus `mrp.bom.line.product_id`.

Die Demo-Modi setzen dann `product.template.tracking` getrennt fuer diese beiden Gruppen.

## 3. Demo-Modi

| Modus in der PWA | Technischer Name | Endprodukt | BOM-Komponenten | Zweck |
| --- | --- | --- | --- | --- |
| Aus | `none` | kein Tracking | kein Tracking | Kontrollzustand ohne Pflichtscan |
| Endprodukt Lot | `finished_lot` | Charge | kein Tracking | Endprodukt wird chargengefuehrt |
| Endprodukt Serial | `finished_serial` | Seriennummer | kein Tracking | klassischer Endprodukt-Serial-Fall |
| Komponenten Lot | `component_lot` | kein Tracking | Charge | aktueller Demo-Standard fuer Bauteil-Chargen |
| Komponenten Serial | `component_serial` | kein Tracking | Seriennummer | strenge Exemplarverfolgung pro Bauteil |
| End Lot + Komp. Lot | `finished_lot_component_lot` | Charge | Charge | beide Rollen chargengefuehrt |
| End Lot + Komp. Serial | `finished_lot_component_serial` | Charge | Seriennummer | Endprodukt als Charge, Komponenten als Einzelteile |
| Voll: End Serial + Komp. Lot | `full_lot_traceability` | Seriennummer | Charge | typischer Produktions-/Montagefall |
| Voll: alles Serial | `full_serial_traceability` | Seriennummer | Seriennummer | maximal strenge Demo, hoher Datenaufwand |

Die PWA zeigt den Schalter nur, wenn die aktive Instanz fuer Demo-Traceability freigegeben ist. Lokal ist das aktuell nur `masterfischer_o19_trial`.

## 4. Backend-Ablauf

Die neuen Endpunkte liegen unter `/api/demo/traceability`:

- `GET /api/demo/traceability`: liest den aktuellen Demo-Status, Modus, verfuegbare Modi und Produktzaehler.
- `POST /api/demo/traceability` mit `{ "mode": "component_lot" }`: setzt den gewaehlten Modus.

Schutzmechanismus:

1. `DEMO_TRACEABILITY_ENABLED` muss aktiv sein.
2. Die aktuelle Odoo-DB muss in `DEMO_TRACEABILITY_ALLOWED_DBS` stehen.
3. Unbekannte Modi werden mit HTTP 400 abgelehnt.
4. Odoo-RPC-Fehler werden als HTTP 502 an die PWA zurueckgegeben.

Beim Umschalten passiert real in Odoo:

1. BOM-Endprodukte und BOM-Komponenten werden ueber `mrp.bom` und `mrp.bom.line` ermittelt.
2. Die zugehoerigen `product.template.tracking`-Felder werden auf `none`, `lot` oder `serial` gesetzt.
3. Fuer `lot` werden Demo-Chargen je Produkt/Lagerort erzeugt: `DEMO-LOT-{code}-L{location_id}`.
4. Fuer `serial` werden Demo-Seriennummern erzeugt: `DEMO-SN-{code}-L{location_id}-{index}`.
5. Fuer serialisierte Komponenten werden offene Move-Lines bei Bedarf auf Menge 1 gesplittet, weil Odoo Seriennummern pro einzelner Einheit erwartet.

## 5. PWA-Ablauf

1. Picker oeffnet `https://localhost/`.
2. Rechts oben im Lager-/Instanzschalter `Odoo 19 Trial` waehlen.
3. Profil/Picker waehlen.
4. Der Traceability-Demo-Schalter erscheint rechts oben neben dem Instanzschalter.
5. Modus waehlen.
6. Die PWA sendet `POST /api/demo/traceability`.
7. Nach erfolgreichem Umschalten laedt die PWA die Auftragsliste neu.

Im Picking selbst:

- Bei `tracking = lot` fragt die PWA nach **Charge**.
- Bei `tracking = serial` fragt die PWA nach **Seriennummer**.
- Ohne korrekte Charge/Seriennummer bestaetigt das Backend die Move-Line nicht.
- Einzel-Picking und Cluster-Picking verwenden dieselbe serverseitige Validierung.

## 6. Odoo-Orte in der UI

In Odoo 19 Trial (`http://localhost:8100`, DB `masterfischer_o19_trial`). In Odoo 18 Live und `lager-2` sind die fachlichen Orte gleich, einzelne Menuebezeichnungen koennen leicht abweichen:

| Frage | Odoo-Menue |
| --- | --- |
| Wo sehe ich Produkte? | Inventory -> Products -> Products |
| Wo sehe ich Tracking am Produkt? | Produkt oeffnen -> Inventory/Traceability -> Tracking |
| Wo sehe ich Chargen/Seriennummern? | Inventory -> Products -> Lots / Serial Numbers |
| Wo sehe ich Stuecklisten? | Manufacturing -> Products -> Bills of Materials |
| Wo sehe ich offene Auftraege? | Inventory -> Operations -> Transfers |
| Wo sehe ich Cluster/Batches? | Inventory -> Operations -> Batch Transfers |
| Wo sehe ich Lagerbestand je Lot/Serial? | Inventory -> Reporting oder Produkt/Lot-Ansicht, je nach Odoo-19-Menue |

Wenn im Produkt kein Tracking-Feld sichtbar ist, liegt das meist an einem dieser Punkte:

- Die Lots-/Serials-Funktion ist in Inventory Settings nicht aktiv.
- Man schaut auf eine andere Datenbank/Instanz als `masterfischer_o19_trial`.
- Das Produkt ist nicht Teil der BOM-Komponentenmenge, die der Demo-Service umschaltet.
- Die Ansicht ist nicht im Inventory-/Traceability-Bereich des Produktformulars.

## 7. Cluster-Regel im aktuellen System

Cluster-Vorschlaege sind keine KI-Entscheidung. Sie entstehen deterministisch:

1. Backend liest `stock.picking` mit `state = assigned` und `batch_id = False`.
2. Backend liest die Move-Lines dieser Pickings.
3. Aus der Quell-Location wird die Zone abgeleitet: vorletztes Segment im Location-Pfad.
4. Pickings werden nach Zone gruppiert.
5. Die groessten Gruppen erscheinen zuerst.
6. Beim Start legt das Backend einen echten `stock.picking.batch` in Odoo an.
7. Jede Order bekommt eine Box/Farbe und ein echtes Ziel-Package.

Die PWA zeigt deshalb aktuell zwei Cluster-Vorschlaege auf der Trial-DB. Die Zahl aendert sich, wenn Pickings validiert, gebatcht oder aus `assigned` herausbewegt werden.

Kompatibilitaet: Falls eine Odoo-18-Datenbank das Feld `stock.picking.batch_id` noch nicht hat, faellt `/api/cluster/suggestions` auf `state = assigned` ohne Batch-Filter zurueck, statt mit HTTP 500 abzubrechen. Am 2026-07-04 wurde `stock_picking_batch` in `lager-2` installiert; damit hat auch diese Instanz das echte Feld `batch_id`.

## 8. Sicherheitskorrektur Docker/Odoo

Beim Backend-Recreate wurde sichtbar, dass der Compose-Service `odoo` zu leicht mit einem Odoo-19-Image gegen die Live-DB haette starten koennen. Der Stand wurde deshalb abgesichert:

- `odoo/Dockerfile` hat wieder Odoo 18 als Default (`ODOO_BASE_IMAGE=odoo:18.0`).
- Der Compose-Service `odoo` ist als Live/Default-Odoo-18 markiert und hart auf `odoo:18.0` gepinnt.
- Live-Odoo und `lager-2` mounten `odoo/addons18`.
- Odoo 19 Trial mountet `odoo/addons`.
- `odoo19-trial` ist ein eigener Compose-Service mit Profil `odoo19-trial`.
- `odoo19-trial` nutzt `odoo/odoo19-trial.conf`.
- `odoo/odoo19-trial.conf` erlaubt nur `dbfilter = ^masterfischer_o19_trial$`.
- Backend-Profile mit Odoo-19-Namen wie `o19-trial` duerfen nur auf `masterfischer_o19_trial` zeigen.

Damit ist der Sollzustand:

- normales `docker compose up` startet die Live-/Default-Welt auf Odoo 18,
- Odoo 19 ist nur explizit fuer Trial/Demo aktiv,
- Live-Cutover auf Odoo 19 bleibt eine separate, kontrollierte Entscheidung.

## 9. Verifikation vom 2026-07-04

Ausgefuehrte Checks:

- `docker compose config --quiet`
- Python-Syntaxcheck fuer Backend-/Odoo-Dateien
- JS-Syntaxcheck fuer PWA-Dateien
- Backend-Fokustests: 109 bestanden
- PWA-JS-Tests: 21 bestanden
- API-Smoke im Backend-Container:
  - `local` meldet Odoo `18.0-20260119`
  - `o19-trial` meldet Odoo `19.0-20260630`
  - `/api/instances` liefert `local`, `lager-2`, `o19-trial`
  - `/api/demo/traceability` liefert `component_lot`
  - `/api/pickings` liefert `local`: 21, `lager-2`: 9, `o19-trial`: 21 offene Auftraege
  - `/api/cluster/suggestions` liefert `local`: 2, `lager-2`: 1, `o19-trial`: 2 Vorschlagsgruppen
- Browser-Smoke mit Playwright:
  - PWA laedt auf `https://localhost/`
  - 3 Picker sichtbar
  - Demo-Schalter sichtbar
  - 9 Demo-Modi sichtbar
  - Demo-Modus steht auf `component_lot`
  - 21 Auftraege sichtbar
  - Cluster-Screen zeigt 2 Vorschlaege und 21 Pickings

## 10. Naechste Schritte

Prioritaet 1: Demo stabil halten

- Odoo-19 Trial nicht als Live-System behandeln.
- Demo-Modus vor Praesentation auf `Komponenten Lot` oder `Voll: End Serial + Komp. Lot` setzen.
- Ein bis zwei Beispielauftraege in Odoo und PWA durchgehen und Screenshots fuer die Arbeit sichern.

Prioritaet 2: Odoo-19-Cutover vorbereiten

- Backup der Live-DB `masterfischer` ziehen.
- Trial-Migration reproduzierbar dokumentieren.
- Custom-Addons fuer Odoo 18/19 final pruefen.
- n8n-Callbacks mit Instanzbewusstsein klaeren; aktuell bleiben sie bewusst auf `local`.
- Vor Cutover alle offenen Pickings/Quality Alerts in Trial mit realen Benutzerrollen testen.

Prioritaet 3: Bachelorarbeits-Abschluss

- Funktionsdokumentation gegen Screenshots/Codebelege finalisieren.
- Evaluationstabellen fuer Picking, Cluster, Serial/Lot und Voice befuellen.
- Risiken/Limitierungen offen dokumentieren: Odoo19 ist Trial, keine produktive Endabnahme.

Realistische Zeitschaetzung:

- Demo-fertiger Stand: jetzt nutzbar.
- Saubere Dokumentation + Git-Sicherung: heute.
- Stabiler Odoo-19-Live-Cutover: 1 bis 2 weitere Arbeitstage mit Backup, Modulupdate-Test und Abnahme.
- Thesis-fertige Einbettung mit Screenshots/Evaluation: 2 bis 4 weitere Arbeitstage, je nach Umfang der finalen Screenshots und Bewertungstabellen.

## 11. Codequellen

- `backend/app/routers/demo.py` - API-Endpunkte und Trial-DB-Guard
- `backend/app/services/demo_traceability.py` - BOM-Erkennung, Modi, Lot-/Serial-Erzeugung
- `backend/app/services/serial_validation.py` - Charge-/Seriennummernvalidierung
- `backend/app/services/picking_service.py` - Einzel-Picking mit Tracking
- `backend/app/services/cluster_service.py` - Cluster-Picking mit Tracking und Packages
- `pwa/js/api.js` - API-Client fuer Demo-Endpunkte und Instanzheader
- `pwa/js/app.js` - Instanzschalter, Demo-Schalter, Charge-/Serial-Prompt
- `docker-compose.yml` - Odoo18 Default, Odoo19 Trial-Profil
- `odoo/odoo19-trial.conf` - DB-Filter fuer Trial
- `odoo/addons18` - Odoo-18-kompatible Addons fuer Live/Default
- `odoo/addons` - Odoo-19-Port fuer Trial

## Verwandt

- [[03 - Cluster- & Batch-Picking]]
- [[05 - Seriennummer-Bestätigung]]
- [[08 - Odoo-Instanz-Switching (Multi-Mandant)]]
- [[06 - Odoo]]
