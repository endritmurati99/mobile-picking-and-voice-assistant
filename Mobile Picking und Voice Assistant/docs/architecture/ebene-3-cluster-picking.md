# Ebene 3: Cluster-Picking

Ebene 2 zeigte einen einzelnen Auftrag. Beim Cluster-Picking nimmt ein
Mitarbeiter mehrere passende Aufträge gleichzeitig mit und läuft einen
gemeinsamen Weg durch das Lager.

## Die Erklärung in 30 Sekunden

FastAPI schlägt Aufträge vor, die fachlich zusammenpassen. Der Mitarbeiter
wählt zwei bis acht Aufträge aus. FastAPI prüft die Auswahl erneut und erzeugt
in Odoo einen echten Batch sowie einen Zielkarton pro Auftrag.

Die PWA zeigt danach eine gemeinsame Laufreihenfolge. Bei jedem Artikel müssen
sowohl der Artikel als auch der richtige Zielkarton stimmen. Erst wenn alle
Positionen erledigt sind, bittet FastAPI Odoo, den gesamten Batch abzuschließen.

> **Merksatz:** Gemeinsam laufen, aber jeden Kundenauftrag sauber in seinem
> eigenen Karton halten.

## Der Ablauf als Bild

![Cluster-Picking von der Auftragsauswahl bis zum Odoo-Abschluss](./ebene-3-cluster-picking.svg)

Die [Excalidraw-Quelldatei](./ebene-3-cluster-picking.excalidraw) ist
editierbar. Die [SVG-Datei](./ebene-3-cluster-picking.svg) eignet sich für
Dokumente und Präsentationen.

## Ein erfundenes Beispiel

```text
WH/OUT/0101 → Karton A → 1 × Kabel, 1 × Maus
WH/OUT/0102 → Karton B → 2 × Kabel
WH/OUT/0103 → Karton C → 1 × Maus, 1 × Tastatur
WH/OUT/0104 → Karton D → 1 × Kabel, 1 × Tastatur
```

Die vier Aufträge liegen in derselben Zone, haben dasselbe Lieferdatum und
mindestens ein Produkt kommt in allen vier Aufträgen vor. Deshalb ist eine
gemeinsame Runde sinnvoll.

## Schritt 1: Vorschläge laden

Die PWA lädt Cluster-Vorschläge über:

```text
GET /api/cluster/suggestions
```

FastAPI betrachtet nur offene, zugewiesene und noch nicht gebatchte Aufträge.
Es gruppiert sie nach Zone und bewertet unter anderem:

- gleiche Firma,
- gleiches Lieferdatum,
- gemeinsame Produkte.

Ein Vorschlag ist eine Hilfe, keine Buchung. Odoo wird dadurch noch nicht
verändert.

## Schritt 2: Aufträge auswählen und Batch starten

Der Mitarbeiter wählt zwei bis acht Aufträge aus; vier sind die empfohlene
Mindestgröße für eine sinnvolle Runde. Danach sendet die PWA:

```text
POST /api/cluster/batches
```

FastAPI vertraut der alten Bildschirmliste nicht, sondern prüft die Aufträge
erneut. Nur wenn Zustand, Kapazität und Cluster-Regeln noch passen, erzeugt es
in Odoo einen `stock.picking.batch` und setzt den Mitarbeiter als Besitzer.

Jeder Auftrag erhält außerdem ein eigenes Odoo-Paket als Zielkarton. Im
Beispiel sind das Karton A bis D.

## Schritt 3: Gemeinsame Laufreihenfolge anzeigen

Die PWA lädt den aktuellen Batch:

```text
GET /api/cluster/batches/{batch_id}
```

FastAPI liest den Batch aus Odoo und führt passende Positionen nach Lagerplatz
zu einer gemeinsamen Route zusammen. Die PWA zeigt dabei immer:

- Lagerplatz und Produkt,
- offene Gesamtmenge,
- betroffene Aufträge,
- den jeweils erforderlichen Zielkarton,
- den Fortschritt des Batches.

Der Browser hält keine eigene Wahrheit. Nach jeder Bestätigung lädt er den
Batch erneut aus FastAPI und Odoo.

## Schritt 4: Artikel und Zielkarton bestätigen

Für eine Position bestätigt der Mitarbeiter den vorgegebenen Zielkarton per
Auswahl, Scan oder Eingabe. Bei Los- oder Serienprodukten kommt die
entsprechende Nummer hinzu.

```text
POST /api/cluster/batches/{batch_id}/confirm-line
```

FastAPI prüft serverseitig:

1. Gehört der Batch dem angemeldeten Mitarbeiter?
2. Passt der übermittelte Artikelbarcode zum Produkt?
3. Ist der gescannte Karton genau das Ziel dieses Auftrags?
4. Passt gegebenenfalls Los- oder Seriennummer?
5. Darf die Odoo-Position in diesem Zustand geschrieben werden?

Erst danach wird die Position in Odoo aktualisiert. Ein richtiger Artikel im
falschen Karton wird abgelehnt.

Die aktuelle Cluster-PWA besitzt dabei noch keine unabhängige
Artikel-Scanabfrage: Sie sendet den von FastAPI gelieferten Soll-Barcode zurück.
Die serverseitige Barcodeprüfung schützt deshalb API-Aufrufe, ersetzt im
aktuellen Bildschirm aber keinen physischen Artikelscan.

## Schritt 5: Fortschritt und Wiederholung

Nach jeder erfolgreichen Bestätigung lädt die PWA den Batch neu. Erledigte
Teilmengen verschwinden aus der offenen Route; die nächste sinnvolle Position
rückt nach vorne.

Der Abschlussknopf erscheint erst, wenn keine Position mehr offen ist.

## Schritt 6: Batch in Odoo abschließen

```text
POST /api/cluster/batches/{batch_id}/validate
```

FastAPI prüft erneut den Besitzer und ruft anschließend in Odoo
`stock.picking.batch.action_done` auf. Nur bei `batch_complete: true` zeigt die
PWA den Batch als abgeschlossen.

Fordert Odoo einen manuellen Assistenten oder lehnt den Abschluss ab, bleibt
der Batch offen und die PWA zeigt keinen falschen Erfolg.

## Sicherheitsnetze und bewusste Grenze

- **Besitzprüfung:** Nur der eingetragene Mitarbeiter darf den Batch lesen,
  bestätigen und abschließen.
- **Kartonkontrolle:** Auftrag und Zielpaket bleiben auch auf der gemeinsamen
  Route getrennt.
- **Serverprüfung:** Auswahl, übermittelter Soll-Barcode und Serien-/Losdaten
  werden serverseitig geprüft.
- **Wahrheit in Odoo:** Batch, Positionen, Pakete und Abschluss liegen in Odoo.

Der aktuelle PoC besitzt auf den Cluster-Routen noch keine serverseitige
Idempotenz und keinen eigenen Claim pro enthaltenem Auftrag. Die PWA sperrt
Start- und Bestätigungsknöpfe gegen Doppeltippen; für einen produktiven Rollout
mit instabilem Netz müsste diese Grenze serverseitig geschlossen werden.

## Was hier nicht beteiligt ist

n8n, Whisper, Piper und Ollama sind für Cluster-Picking nicht erforderlich.
Insbesondere löst der aktuelle Batch-Abschluss keinen alten n8n-
`batch-confirmed`-Folgeprozess aus.

## Wo der Ablauf im Projekt steckt

- `pwa/js/app.js`: Auswahl, Cluster-Route, Scans und Abschlussanzeige
- `pwa/js/api.js`: Browser-Aufrufe der Cluster-Endpunkte
- `backend/app/routers/cluster.py`: HTTP-Endpunkte und Besitzgrenzen
- `backend/app/services/cluster_service.py`: Regeln, Batch, Kartons und Odoo-Abschluss
- `backend/app/services/odoo_client.py`: Zugriff auf Odoo

## Kurz zusammengefasst

1. FastAPI schlägt passende Aufträge vor.
2. Odoo erhält einen echten Batch und einen Karton je Auftrag.
3. Die PWA führt gemeinsam durch die Lagerplätze.
4. Zielkarton und gegebenenfalls Los/Serie werden für jede Position geprüft.
5. Odoo entscheidet über den endgültigen Batch-Abschluss.
