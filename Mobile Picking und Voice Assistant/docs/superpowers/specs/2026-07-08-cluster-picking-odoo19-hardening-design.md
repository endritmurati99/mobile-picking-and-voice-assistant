# Design Spec: Cluster-Picking Odoo-19 Hardening

- **Datum:** 2026-07-08
- **Status:** Vom User zur Planung freigegeben; Implementierung noch nicht gestartet
- **Bezug:** PWA-/Backend-Audit, Odoo-19-Cluster-Argumentation, Subagent-Code-Reviews Backend/PWA/Daten
- **Zielordner:** `Mobile Picking und Voice Assistant`

---

## 1. Ziel

Die bestehende Clusterfunktion soll fachlich belastbar werden: Ein Cluster-Batch darf nicht nur technisch als Odoo-`stock.picking.batch` existieren, sondern muss nach nachvollziehbaren Kriterien gebildet werden. Fuer den PoC soll sichtbar sein, warum genau diese Auftraege zusammengehoeren: gleiches Lieferdatum oder Zeitfenster, nahe Pickpunkte, Produktueberlappung und realistische Wagenkapazitaet.

Zusatz: Die Demo-Daten muessen kunden- und versandnah genug sein, damit spaeter Versandlabel- oder Carrier-Flows glaubwuerdig angebunden werden koennen.

## 2. Aktueller Stand

Bereits vorhanden:

- echter Odoo-`stock.picking.batch`
- PWA-Auswahl und Cluster-Rundgang
- Put-to-Box im Happy Path ueber Odoo-Package und `result_package_id`
- Backend-Cluster-Tests erfolgreich: `54 passed`
- PWA-Cluster-Playwright-Tests erfolgreich: `3 passed`

Noch nicht ausreichend:

- keine harte Kapazitaetsgrenze im Client und Server
- Vorschlaege nur nach Zone, nicht nach Lieferfenster, Produktueberlappung oder belastbarer Naehe
- Picker-Identitaet wird bei Vorschlaegen und Batch-Erstellung nicht ausreichend als Scope verwendet
- ownerless Batches sind zu offen
- Package-Zuordnung ist best-effort
- Seed-Daten enthalten keine realistischen Kunden, Adressen, Carrier- oder Label-Kontexte

## 3. Brainstorming-Ergebnis

Es wurden drei Wege bewertet:

1. **Nur UI nachschaerfen:** schnell, aber fachlich schwach. Das System koennte weiterhin schlechte Cluster erzeugen.
2. **Nur Backend absichern:** fachlich besser, aber fuer Demo und Fischer-Erklaerung unsichtbar. Die PWA wuerde nicht zeigen, warum ein Cluster sinnvoll ist.
3. **End-to-end Hardening:** Backend-Regeln, PWA-Erklaerbarkeit, Seed-Daten und Tests gemeinsam nachziehen. Das ist der empfohlene und gewaehlte Weg.

Entscheidung: Variante 3. Sie passt zur Aussage, dass die Sinnhaftigkeit am Anwendungsfall haengt, nicht nur an der Technik.

## 4. Fachliche Regeln

- Ein Cluster muss mindestens 2 Auftraege enthalten; 1 Auftrag ist kein Cluster.
- Die harte Obergrenze ist 8 Auftraege pro Wagen.
- Die PWA kennzeichnet 4 bis 8 Auftraege als empfohlenen PoC-Bereich.
- Ein Batch darf nur Pickings enthalten, die `assigned` und noch nicht in einem Batch sind.
- Alle Pickings im Batch muessen zur gleichen Company gehoeren.
- Batch-Support muss in Odoo verfuegbar sein. Fehlt `stock.picking.batch` oder `batch_id`, wird Cluster-Picking fail-closed deaktiviert.
- Vorschlaege sollen nach Lieferdatum/Zeitfenster und primaerer Lagerzone gruppieren.
- Produktueberlappung muss positiv sein, sonst spart der gemeinsame Gang fachlich wenig.
- Put-to-Box ist im Cluster normaler Pflichtpfad: jede Cluster-Line braucht einen Zielkarton oder muss fail-closed blockieren.

## 5. Backend-Design

`ClusterService` bekommt eine kleine Eligibility-Schicht:

- Kapazitaet pruefen: `2 <= len(unique_picking_ids) <= 8`
- Kandidaten aus Odoo lesen: Picking-Kontext, Company, Picker/Owner, Lieferdatum, Partner, Carrier falls vorhanden, Move-Line-Location und Product IDs
- Regelreport bilden: `eligible`, `errors`, `warnings`, `reasons`, `score`
- dieselbe Eligibility fuer `suggest_batches` und manuelles `create_batch` verwenden

Picker-Scope:

- Router uebergibt `PickerIdentity` an `suggest_batches` und `create_batch`.
- Batch-Zugriff ist nur erlaubt, wenn `batch.user_id == picker_identity.user_id`.
- Ownerless Batches werden verweigert, bis es einen expliziten Supervisor-/Claim-Flow gibt.

Fehlercodes:

- Validierungsfehler: 400 oder 422
- fremder/gesperrter Zugriff: 403
- Batch- oder Odoo-Feature nicht verfuegbar: 503
- fachlicher Konflikt wie gemischte Company oder schon gebatchte Auftraege: 409

## 6. PWA-Design

Die PWA muss vor dem Start erklaeren und erzwingen:

- Zaehler: `n/8`
- Startbutton nur aktiv bei gueltiger Kapazitaet
- Hinweis: "Wagen: separate Kartons je Auftrag"
- Vorschlagskarten mit Begruendungschips: Lieferdatum, Zone, Produktueberlappung, Score
- manuelle Auswahl mit kompaktem Kunden-/Lieferdatum-/Zonen-Kontext
- API-Ablehnungen bleiben sichtbar und recoverable

Put-to-Box:

- Fehlt in einer Cluster-Line der Zielkarton, wird nicht bestaetigt.
- Die PWA versucht den Zielkarton aus `line.package_*` oder `batch.boxes` zu ermitteln.
- Wenn kein Zielkarton ermittelt werden kann, zeigt sie einen Fehler und sendet keinen Confirm.

## 7. Seed- und Label-Daten

Der Seeder soll realistische Demo-Kunden und ausgehende Pickings erzeugen:

- `res.partner` Firmen und Lieferkontakte mit Strasse, PLZ, Stadt, Land, E-Mail, Telefon
- ausgehende Customer Pickings mit `partner_id`, `origin`, `scheduled_date`, optional `date_deadline`
- wiederkehrende Produkte mit absichtlicher Ueberlappung
- mehrere Lieferfenster und Lagerzonen, damit gute und schlechte Cluster sichtbar sind
- Carrier-Kontext, wenn das Odoo-Modul Feldzugriff bietet; sonst als Demo-Metadaten im API-Payload, ohne Schatten-System of Record

## 8. Akzeptanzkriterien

- Backend lehnt 1 Auftrag und mehr als 8 Auftraege ab.
- Backend lehnt gemischte Company, fehlendes Batch-Modul, ownerless Batch-Zugriff und fehlenden Picker-Scope ab.
- Vorschlaege enthalten Score und Begruendungen.
- PWA zeigt Kapazitaet, Kriterien und "separate Kartons je Auftrag".
- PWA startet keinen ungueltigen Batch.
- Cluster-Line ohne Zielkarton ist nicht bestaetigbar.
- Seed-Daten erzeugen mehrere realistische Kundenauftraege mit Adressen und Produktueberlappung.
- Tests decken die Negativfaelle ab.

## 9. Nicht im Scope

- Versandlabel-Druck selbst.
- Automatische Odoo-Route-/Carrier-Optimierung.
- Eilauftrag-Umbau in laufenden Clustern.
- Supervisor-Claim-Flow fuer ownerless Batches.
- Neue lokale Schatten-Datenbank fuer Kunden- oder Versanddaten.

## 10. Verifikation

Pflicht vor Abschluss:

```bash
cd "/mnt/c/Users/endri/Desktop/Bachelor/Mobile Picking und Voice Assistant/backend"
PYTHONPATH=.deps python3 -m pytest -p pytest_asyncio tests/test_cluster_service.py tests/test_cluster_routes.py tests/test_picking_service.py tests/test_seed_odoo_script.py -q

cd "/mnt/c/Users/endri/Desktop/Bachelor/Mobile Picking und Voice Assistant"
npx playwright test e2e/cluster.spec.js
```

Wenn die PWA visuell geaendert wird, muss zusaetzlich ein Browser-Screenshot oder Playwright-Lauf gegen den lokalen Server erfolgen.
