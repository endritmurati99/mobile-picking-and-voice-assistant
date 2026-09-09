# PostgreSQL-App-Rollen für Lager 1, Lager 2 und n8n

Compose verwendet `pwr_db_admin` nur für PostgreSQL-Bootstrap und Administration, `odoo_app` für beide Lager und `n8n_app` für n8n einschließlich Credential-Provisionierung. Die App-Rollen sind keine Superuser und können weder Datenbanken noch Rollen anlegen. n8n kann nicht auf die Lagerdatenbanken zugreifen; Odoo kann nicht auf die n8n-Datenbank zugreifen.

## Neue Installation

In der privaten `.env` drei unterschiedliche Kennwörter setzen: `POSTGRES_PASSWORD`, `ODOO_DB_PASSWORD` und `N8N_DB_PASSWORD`. Kennwörter gehören nie in Git.

Bei einem neuen Volume legt PostgreSQL `lager1`, `lager2` und `n8n` samt Rollen, Besitzern und Schema-Rechten an. Die Lagerdatenbanken sind zunächst leer; Odoo-Module und Benutzer werden anschließend wie bei jeder Neuinstallation eingerichtet.

## Bestehende Installation

Ein bestehendes Volume führt Init-Skripte nicht erneut aus. Ein Neustart allein migriert weder Rollen noch Eigentümer. Den Ablauf ausschließlich in einem Wartungsfenster ausführen:

1. Schreibende Dienste anhalten und mit `infrastructure/scripts/clone-postgres-volume.sh` einen Offline-Klon samt Manifest erstellen. Originalvolume und Sicherung erhalten.
2. Den gesamten Ablauf zuerst am isolierten Klon durchführen. `ODOO_DB_NAME=lager1` und, falls vorhanden, `ODOO_LAGER2_DB_NAME=lager2` setzen.
3. Drei geschützte Kennwortdateien (0400 oder 0600) für `PWR_DB_ADMIN_PASSWORD_FILE`, `ODOO_DB_PASSWORD_FILE` und `N8N_DB_PASSWORD_FILE` bereitstellen. Die Werte müssen zu den drei Compose-Kennwörtern passen.
4. `migrate-n8n-db-role.sh backup <geschütztes-Verzeichnis>` und danach `apply <dasselbe-Verzeichnis>` ausführen. `PGHOST` und `PGPORT` müssen dabei auf den Klon zeigen; Compose muss dasselbe isolierte Projekt und Volume verwenden.
5. Anmeldung, beide Lager, Picking und n8n-Credentials am Klon prüfen. Erst nach erfolgreicher Probe denselben Ablauf im Wartungsfenster am Betriebsvolume ausführen.

Der Backup-Pfad sichert die angegebenen Anwendungsdatenbanken einschließlich Objektdefinitionen und Rechten. Der Apply-Pfad prüft das Backup-Manifest, überträgt die Anwendungsobjekte im `public`-Schema und prüft anschließend die Zugriffsgrenzen, bevor er den alten gemeinsamen Login deaktiviert. Nicht-Zieldatenbanken werden mit OID-basiertem Namenindex und Dump gesichert; Daten und Besitzer bleiben erhalten. Bei aktiven Clients auf diesen Datenbanken bricht der Ablauf vor Änderungen ab. Danach wird `CONNECT` für `PUBLIC`, `odoo_app` und `n8n_app` auf diesen Archivdatenbanken entzogen.

Zusätzliche Anwendungsschemas außerhalb von `public` sind nicht Teil dieses Skripts und müssen vorher separat geprüft werden. PostgreSQL-Systemobjekte und Objekte von Extensions behalten ihren Besitzer. Kein `docker compose down -v` auf dem Originalprojekt ausführen.

Der frühere `rollback`-Modus ist gesperrt, weil er nur n8n vollständig zurücksetzte. Der Rückweg ist der erhaltene Offline-Stand zusammen mit der vorherigen Compose- und Odoo-Konfiguration.

## Prüfen

Nach `apply` wiederholt `verify` die Zugriffsprüfung. Zusätzlich müssen sich Benutzer an beiden Lagern anmelden können, Pickings laden und n8n seine vorhandenen Credentials entschlüsseln können.
