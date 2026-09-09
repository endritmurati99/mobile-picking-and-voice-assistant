# Teststand nach den Review-Korrekturen vom 9. September 2026

Die Schritte „Pagination-Test reparieren“ und „Browser-Tests auf die aktuelle
Oberfläche umstellen“ sind umgesetzt. Getestet wurde der lokale WSL/Linux-Stand.
Die Tests ersetzen noch keinen Durchlauf gegen die laufenden Odoo-/n8n-Dienste.

## Änderungen

- Der Pagination-Mock berücksichtigt den ID-Cursor. Alle 251 Aufträge und die
  tatsächliche Sortierung werden geprüft. Ein nicht fortschreitender Cursor
  erzeugt sofort einen Testfehler statt einer Endlosschleife. Das wurde durch
  eine ausschließlich im Testprozess ausgeführte Mutation zusätzlich geprüft.
- Alle Browser-Specs verwenden das Benutzername-/Passwortformular. Der API-Mock
  lehnt falsche Test-Zugangsdaten oder eine fehlende Gerätekennung ab.
- Auftragskarte, Suchfeld, Aktualisierung und Lagerwechsel entsprechen der
  aktuellen Oberfläche. Der Lagerwechsel prüft den Sitzungswechsel und das
  Ausbleiben des veralteten `X-Odoo-Instance`-Headers.
- Der Cluster-Durchlauf prüft Artikel- und Karton-Scan, den gesperrten regulären
  Bestätigungsknopf sowie die ausdrückliche manuelle Ausnahme. Prüfungen für
  falsche/fehlende Zielkartons und Pflicht-Seriennummern bleiben erhalten.
- Die unveränderte Axe-Prüfung fand zu wenig Kontrast beim Lagerplatztext.
  Der vorhandene Akzent liefert nun 5,9:1 auf der hellen und 6,3:1 auf der
  dunklen Kartenfläche. Service-Worker-Cache: `picking-v38`.
- Playwright-Konfiguration, npm-Skript und festgeschriebene vorhandene
  Testabhängigkeiten sind wieder im Repository enthalten. Der Testserver
  startet automatisch auf `127.0.0.1:4173` und liefert ausschließlich die PWA.
- Drei Linux-Screenshot-Referenzen wurden nach Sichtprüfung aktualisiert.
  Pixel 7 bewahrt die bisherigen 412 × 839 Pixel; ein festes Testdatum hält
  relative Datumsangaben stabil. Win32-Referenzen wurden nicht neu geprüft.

## Ergebnisse

| Prüfung | Ergebnis |
| --- | --- |
| Backend und Infrastruktur | 1.283 bestanden, zwei opt-in PostgreSQL-Livetests übersprungen, Exit 0 |
| PWA und n8n, Node-Modultests | 100 bestanden, Exit 0 |
| Mobiler Chromium-Browser | 31 bestanden einschließlich drei Screenshot-Prüfungen, Exit 0 |
| Desktop-Chromium | 28 bestanden, Exit 0 |
| Abschließender `npm run test:e2e` mit automatisch gestartetem Server | Alle 59 Browser-Tests bestanden, Exit 0; keine Snapshot-Aktualisierung im Prüflauf |
| Workflow-Verträge | Bestanden; bekannte Hinweise auf Outbox statt `n8n.fire` |
| Odoo-Core-Python | Syntaxprüfung aller 17 Python-Dateien bestanden |
| Git-Diff | `git diff --check` ohne Befund |

Die Browser-Prüfungen verwenden echte PWA-Dateien und kontrollierte API-Mocks,
einschließlich der Authentifizierung. Sie buchen keine echten Aufträge.
Browser Harness wurde geprüft; dessen Daemon war nicht erreichbar. Die
bestehende Playwright-Suite lief mit ihrem isolierten Chromium-Testbrowser.

## Wiederholen

Im Anwendungsordner, unter WSL/Linux:

```bash
npm ci
npx playwright install chromium
npm run test:e2e
node --test pwa/js/tests/*.test.mjs n8n/tests/*.test.mjs
python3 infrastructure/scripts/verify-workflows.py
```

Mit den vorhandenen Python-Testabhängigkeiten im Ordner `backend`:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=.deps python3 -m pytest -p no:cacheprovider -q tests ../infrastructure/tests
```

Die Python-Tests wurden direkt ausgeführt, ohne den globalen `.env`-Export des
Makefiles. Direktwerte und Secret-Dateien dürfen nicht gleichzeitig konfiguriert
sein; der Konfigurationsschutz weist diese Kombination ausdrücklich zurück.

## Noch offen vor dem vollständigen Live-Test

Docker/DB-Rollenmigration und fehlende getrennte DB-Kennwörter müssen gemäß
`../runbooks/n8n-db-role-migration.md` zuerst am Klon vereinbart werden. Danach
den geprüften Backend-/Odoo-/PWA-Stand laden und Odoo-Modultests, Handybedienung,
Einzel-/Cluster-Versand sowie n8n-Ausfall/Wiederanlauf an markierten Testaufträgen
nachweisen. Die Abschluss-Wiederaufnahme nach einer bereits gebuchten letzten
Position und die Label-/PDF-Anzeige in der PWA bleiben fachliche Folgearbeit.
