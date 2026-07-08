---
title: "Cluster-Picking Odoo-19 Audit und Haertungsplan"
tags: [funktionsdoku, cluster, odoo19, audit, pwa]
status: arbeitsstand
stand: 2026-07-08
---

# Cluster-Picking Odoo-19 Audit und Haertungsplan

> [!abstract] Kurzfassung
> Stand 2026-07-08: Die Clusterfunktion ist technisch vorhanden und getestet, aber fachlich noch nicht ausreichend gegen die Odoo-19-Argumentation abgesichert. Der Happy Path mit echtem Odoo-`stock.picking.batch`, PWA-Rundgang und Put-to-Box funktioniert. Nachzuziehen sind vor allem fachliche Batch-Regeln, Picker-Scope, fail-closed Kartonlogik und realistische Kundendaten.

## 1. Was bereits umgesetzt ist

- Backend nutzt Odoo-native `stock.picking.batch`; es gibt keine eigene Schatten-Batch-Datenbank.
- PWA hat einen Cluster-Rundgang mit Linienbestaetigung, Serien-/Lot-Dialog und Batch-Abschluss.
- Put-to-Box ist im Happy Path vorhanden: pro Auftrag wird ein Odoo-Package/Karton genutzt und beim Pick abgefragt.
- Backend-Cluster-Tests liefen erfolgreich: `54 passed`.
- PWA-Cluster-Flow lief erfolgreich ueber Playwright: `3 passed`.
- `agent-browser` war lokal nicht installiert; Playwright wurde als Browser-Fallback genutzt.

## 2. Fachliche Einordnung zu Odoo 19

Odoo beschreibt Cluster-Picking als sinnvoll bei hohem Auftragsvolumen, stabiler Nachfrage und vielen aehnlichen Auftraegen mit wenigen haeufig bestellten Produkten. Der Nutzen gegenueber reinem Batch-Picking ist, dass beim Pick direkt in den auftragsbezogenen Karton sortiert wird. Das Nachsortieren am Packplatz entfaellt.

Fachlich relevante Kriterien fuer einen Cluster-Batch:

- gleicher Ausliefertag oder gleiches Zeitfenster
- raeumliche Naehe der Pickpunkte
- Produktueberlappung
- Wagenkapazitaet als harte Obergrenze; fuer den PoC realistisch 4 bis 8 Auftraege parallel

Bekannte Nachteile aus der Odoo-Argumentation:

- Eilauftraege lassen sich nach gebildetem Batch nicht gut priorisieren.
- Batchbildung muss vorher passieren und kann selbst zum Engpass werden.

## 3. Kartonfrage

Die Auftraege gehoeren nicht alle in denselben Karton. Gemeint ist ein Kommissionierwagen mit mehreren auftragsbezogenen Kartons, Behaeltern oder Totes. Jeder Auftrag bekommt seinen eigenen Zielbehaelter.

Geeignete Begriffe:

- Cluster-Picking
- Put-to-Box
- Pick-to-Carton
- Sort-to-Carton

Im Code laeuft das ueber Odoo-Packages und `result_package_id`.

## 4. Was noch nicht ausreichend umgesetzt ist

### Kritisch

- Keine harte Wagenkapazitaet: aktuell kann ein Batch mit 1 Auftrag oder mit zu vielen Auftraegen gestartet werden.
- Batchbildung prueft nicht sauber gleichen Ausliefertag/Zeitfenster, Produktueberlappung oder echte raeumliche Naehe. Der Vorschlag gruppiert im Wesentlichen nach erster Zone.
- Picker-Scope fehlt bei Vorschlaegen und Batch-Erstellung. Ein aktiver Picker kann zu viel sehen oder claimen.
- Ownerless Batches werden zu offen akzeptiert.

### Wichtig

- Company-Konsistenz wird beim Batch nicht hart geprueft.
- Fehlt `batch_id` in Odoo, faellt der Code zu offen auf `assigned` zurueck. Fuer Cluster muss das fail-closed sein.
- Package-Zuordnung ist teilweise best-effort. Wenn keine Package-Daten vorhanden sind, kann Put-to-Box ausfallen.
- PWA zeigt nicht deutlich genug, warum ein Batch fachlich sinnvoll ist.
- Seed-Daten sind nicht label- oder kundenrealistisch. Es fehlen Firmen, Lieferadressen, Carrier, Kundenreferenzen und Lieferfenster.

## 5. Relevante Code-Stellen

- Backend-Service: `Mobile Picking und Voice Assistant/backend/app/services/cluster_service.py`
- Backend-Router: `Mobile Picking und Voice Assistant/backend/app/routers/cluster.py`
- PWA-Cluster-Flow: `Mobile Picking und Voice Assistant/pwa/js/app.js`
- PWA-API: `Mobile Picking und Voice Assistant/pwa/js/api.js`
- Seed-Daten: `Mobile Picking und Voice Assistant/infrastructure/scripts/seed-odoo.py`
- Picking-Kontext fuer spaetere Labels: `Mobile Picking und Voice Assistant/backend/app/services/picking_service.py`
- Cluster-Tests: `Mobile Picking und Voice Assistant/backend/tests/test_cluster_service.py`, `Mobile Picking und Voice Assistant/backend/tests/test_cluster_routes.py`, `Mobile Picking und Voice Assistant/e2e/cluster.spec.js`

## 6. Gespeicherte Superpowers-Artefakte

- Design-Spec: `Mobile Picking und Voice Assistant/docs/superpowers/specs/2026-07-08-cluster-picking-odoo19-hardening-design.md`
- Implementierungsplan: `Mobile Picking und Voice Assistant/docs/superpowers/plans/2026-07-08-cluster-picking-odoo19-hardening.md`

## 7. Naechster Umsetzungsschnitt

1. Backend-Regeln: max. 8 Auftraege, sinnvoller Mindestwert, Picker-Scope, Company-Check, ownerless fail-closed, echte Fehlercodes.
2. Cluster-Suggestions: Ausliefertag/Zeitfenster, Zone/Location, Produktueberlappung, Score und Begruendungen.
3. PWA: Kapazitaetsanzeige, Kriterien-Chips, Startbutton sperren, klare Legende "Wagen: separate Kartons je Auftrag", Kartonpruefung fail-closed.
4. Seed-Daten: realistische Demo-Kunden/Firmen, Versandadressen, ausgehende Customer Pickings, Lieferfenster, Carrier-/Label-Kontext.
5. Tests fuer Negativfaelle und Demo-Daten ergaenzen.

## 8. Handoff fuer neue Session

Arbeitsordner:

```bash
cd "/mnt/c/Users/endri/Desktop/Bachelor/Mobile Picking und Voice Assistant"
```

Vor Umsetzung lesen:

```bash
sed -n '1,260p' docs/superpowers/specs/2026-07-08-cluster-picking-odoo19-hardening-design.md
sed -n '1,320p' docs/superpowers/plans/2026-07-08-cluster-picking-odoo19-hardening.md
```

Bekannter Arbeitsbaum-Hinweis: Vor dieser Dokumentation gab es bereits nicht zugeordnete Aenderungen im Repository, vor allem an `.env.example`, Backend-Konfiguration, n8n und LLM-Dateien. Cluster-Implementierungsdateien wurden im Audit nicht geaendert.

## 9. Umsetzung abgeschlossen am 2026-07-08

- Backend-Regeln: Cluster-Picking laeuft fail-closed, wenn `stock.picking.batch`/`batch_id` nicht verfuegbar ist, erzwingt 2 bis 8 Auftraege, prueft Picker-Ownership, Company, Ausliefertag und Produktueberlappung und weist ownerless Batches ab.
- Cluster-Suggestions: Vorschlaege werden nach Ausliefertag und primaerer Lagerzone gruppiert, liefern Score, Gruende, Warnungen und Produktueberlappung an die PWA.
- Put-to-Box: Batch-Erstellung bricht bei fehlender Package-Zuordnung kontrolliert ab; Linienbestaetigung verlangt einen Zielkarton und blockiert ohne `result_package_id`.
- PWA-Regeln: Auswahl zeigt Kapazitaet, Regel-Chips, Score, Lieferdatum und die Legende `Wagen: separate Kartons je Auftrag`; Einzelauftrag und Ueberkapazitaet sind vor API-Aufruf gesperrt.
- Kundendaten: Picking- und Cluster-APIs geben Kundenname, Versandadresse, Kundenreferenz, Lieferdatum und Carrier-Kontext weiter.
- Seed-Daten: Standard-Seed erzeugt Demo-Kunden mit Lieferadressen sowie sechs ausgehende `SO-DEMO-*`-Auftraege mit gemeinsamen Produkten und zwei Lieferterminen fuer realistische Cluster-Vorschlaege.
- Verifikation: Backend-Zieltests `99 passed`; PWA-Cluster-Playwright `6 passed`; Grep-Pruefung fuer die neuen Fehlercodes und UI-Hinweise erfolgreich.
- Bekannte Restgrenze: Versandlabel-Druck ist weiterhin nicht im Scope dieser Umsetzung.
