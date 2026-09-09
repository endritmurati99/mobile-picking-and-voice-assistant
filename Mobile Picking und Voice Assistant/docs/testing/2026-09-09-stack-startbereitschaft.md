# Stack-Startbereitschaft und Datenbankrollen – 9. September 2026

Der bestehende lokale Stack wurde gesichert, migriert, vollständig neu erstellt
und anschließend über `docker compose stop` und `make up` kalt gestartet.
Alle elf Dienste laufen; alle definierten Docker-Healthchecks sind grün.
Es gibt einen Backend-Container und je einen Odoo-Container für Lager 1 und Lager 2.

## Änderungen

- `make up` wartet mit `--wait --wait-timeout 300` auf Compose-Bereitschaft.
  Das Backend hat einen Healthcheck auf `/api/health/live`.
- Make interpretiert `.env` nicht mehr als Makefile. Compose und die betroffenen
  Python-Skripte lesen ihre Einstellungen selbst, ohne JSON-Werte zu beschädigen.
- Uvicorn-Reload gehört nur zum Entwicklungs-Overlay. Die ungenutzte
  `odoo19_trial_data`-Deklaration wurde entfernt; bestehende Volumes wurden nicht gelöscht.
- Die lokale, nicht versionierte `.env` enthält nun passende getrennte
  Datenbankzugänge und die ausdrückliche Auswahl von Basisdatei und Dev-Overlay.
  Secrets, Odoo-Anmeldung und n8n-Verschlüsselungsschlüssel bleiben privat.
- Das Migrationsskript sichert auch zusätzliche Datenbanken, prüft deren
  Inventar gegen das Backup und verweigert die Migration bei aktiven Clients dort.
  Beide App-Rollen verlieren CONNECT/TEMPORARY auf diese Archivdatenbanken.
- Der API-Smoke prüft Anmeldung, Lagerzuordnung, CSRF, Auftragsliste und Logout
  in jeder konfigurierten Instanz. Ohne Anmeldedaten schlägt er fehl;
  `--health-only` ist die ausdrücklich eingeschränkte Alternative.
- Odoo-Tests grenzen Aussagen auf ihre eigenen Datensätze ein. Der Paralleltest
  materialisiert IDs vor dem Start seiner Threads und teilt keine ORM-Lesezugriffe.
  Produktlogik wurde dabei nicht geändert.

## Datenübernahme und Sicherungen

Vor der Betriebsumstellung wurden alle Anwendungsschreiber und PostgreSQL
gestoppt. Eine byteidentische PostgreSQL-Volumekopie sowie geprüfte Kopien der
beiden Odoo-Filestores, von n8n-Daten und n8n-Dateien wurden erstellt.
Zusätzlich liegen 15 geprüfte logische Dumps vor: beide Lager, n8n und zwölf
Zusatzdatenbanken. Der Manifestvergleich war erfolgreich.

Die Migration wurde zunächst auf einem vollständigen, netzisolierten Klon mit
echten Compose-Diensten, Anmeldung und Kaltstart ausgeführt. Erst danach folgte
der Betriebsstack. `odoo_app` und `n8n_app` sind keine Superuser und besitzen
ihre jeweiligen Anwendungsdatenbanken. Der alte Initdb-Rolleninhaber ist auf
NOLOGIN gesetzt; seine erforderlichen Systemprivilegien bleiben erhalten.
Die zwölf Zusatzdatenbanken behalten Daten und Eigentümer, sind jedoch für
die neuen App-Zugänge nicht erreichbar.

Rollback-Sicherungen bleiben lokal unter dem Volumenpräfix
`pwr_before_roles_` erhalten. Geschützte Dumps, Manifeste und die vorherige
Konfiguration liegen unter
`/home/endri/audits/picking-start-ready-20260909/` und gehören nicht ins Repository.
Die elf Container des vollständigen Testklons und der ältere SQL-Testcontainer
wurden entfernt, jeweils ohne ihre Volumes zu löschen. Unabhängige ältere
Docker-Projekte wurden nicht verändert.

## Verifikation

| Prüfung | Ergebnis |
| --- | --- |
| Backend und Infrastruktur, vollständige Python-Suite | 1292 bestanden, 2 übersprungen |
| Aktuelle Startup-/Smoke-Regressionen | 19 bestanden |
| Migrationsprüfungen | 25 fokussierte Prüfungen und 2 echte PostgreSQL-Tests bestanden |
| Odoo-Module auf migrierter, befüllter Datenkopie | 313 Tests bestanden, Prozessstatus 0 |
| Vollständiger Image-Build | Prozessstatus 0 |
| Isolierter Compose-Klon, Start und Kaltstart | `--wait` erfolgreich |
| Betriebsstack, vollständiges Recreate | `--wait` erfolgreich |
| Betriebsstack, Stop und `make up` | Prozessstatus 0 |
| HTTPS-Smoke nach Migration und nach Kaltstart | Anmeldung/Zuordnung/CSRF/Aufträge/Logout für beide Lager erfolgreich |
| Fachliche Datenbestände vor/nach Betriebsumstellung | Zeilenzahlen aller 204 geprüften Stock-, Produkt-, Sale-, Partner- und n8n-Workflow/Credential-Tabellen unverändert |
| n8n-Credentials | Alle 4 Einträge erfolgreich entschlüsselt; temporäre Klartextdatei entfernt |
| Datenbank-Isolation nach Kaltstart | Positive und negative Verbindungsprüfungen erfolgreich, einschließlich aller 12 Archive |
| Ausgelieferte PWA | CSS und Service Worker stimmen bytegenau mit dem Checkout überein |

Die Lagerauswahl-Korrektur und ihre Browserprüfungen sind im
[vorherigen Prüfbericht](2026-09-09-docker-und-lagerauswahl.md) dokumentiert.
Diese Runde ändert keine PWA-Layoutdateien.

## Wieder starten

Im Anwendungsverzeichnis `make up`, danach bei Bedarf `make test-api`.
Die lokale Konfiguration startet beide Lager. Neue leere Installationen
brauchen weiterhin ihre Odoo-Modul- und Benutzereinrichtung; die Prüfung oben
belegt den Start der vorhandenen, eingerichteten Installation.
Siehe [README](../../README.md) und
[Migrationsablauf](../runbooks/n8n-db-role-migration.md).
