# PostgreSQL-App-Rollen für Lager 1, Lager 2 und n8n

Die Zielkonfiguration in Compose verwendet `pwr_db_admin` ausschließlich für PostgreSQL-Bootstrap und
Administration, `odoo_app` für beide Lager und `n8n_app` für n8n einschließlich
Credential-Provisionierung. Die App-Rollen sind weder Superuser noch dürfen sie
Datenbanken oder Rollen anlegen. n8n kann nicht auf die Lagerdatenbanken zugreifen;
Odoo kann nicht auf die n8n-Datenbank zugreifen.

## Neue Installation

In der privaten `.env` drei unterschiedliche Kennwörter konfigurieren:
`POSTGRES_PASSWORD`, `ODOO_DB_PASSWORD`, `N8N_DB_PASSWORD`. Die Vorgaben für die
App-Benutzernamen aus `.env.example` übernehmen. Kennwörter nicht in Git ablegen.

Bei einem **neuen** Volume führt PostgreSQL `10-init-db-roles.sh` aus und erzeugt
`lager1`, `lager2` und `n8n` samt Rollen, Besitzern und Schema-Rechten. Die beiden
Lagerdatenbanken sind zunächst leer; die Odoo-Module und Benutzer müssen wie bei
jeder Neuinstallation initialisiert werden. Die optionale zweite Odoo-Instanz
verwendet das Profil `second-odoo`.

## Bestehende Installation

Ein vorhandenes Volume führt Init-Skripte nicht erneut aus. Die geänderten
Compose-Benutzernamen deshalb erst nach der Migration aktivieren. Ein Neustart
allein migriert weder Rollen noch Eigentümer.

1. Alle schreibenden Dienste in einem Wartungsfenster stoppen und mit
   `infrastructure/scripts/clone-postgres-volume.sh` einen verifizierten
   Offline-Klon und dessen Manifest erstellen. Originalvolume und Sicherung
   erhalten. Den Ablauf zuerst ausschließlich am Klon proben.
2. Für die Migration `ODOO_DB_NAME=lager1` und bei vorhandenem zweitem Lager
   `ODOO_LAGER2_DB_NAME=lager2` setzen. Drei geschützte Kennwortdateien über
   `PWR_DB_ADMIN_PASSWORD_FILE`, `ODOO_DB_PASSWORD_FILE`, `N8N_DB_PASSWORD_FILE`
   bereitstellen (0400 oder 0600). Ihre Werte müssen zu den drei Compose-
   Kennwörtern passen. `PGHOST` und `PGPORT` müssen den zu migrierenden **Klon**
   adressieren; Compose muss dasselbe isolierte Projekt/Volume verwenden.
3. `migrate-n8n-db-role.sh backup <geschütztes-Verzeichnis>` ausführen, dann
   `apply <dasselbe-Verzeichnis>`. Der Apply-Pfad stoppt die App-Schreiber,
   überträgt die Anwendungsobjekte im `public`-Schema beider angegebenen Lager,
   prüft die Zugriffsgrenzen und deaktiviert erst danach den alten gemeinsamen
   Login. Nicht-Zieldatenbanken werden mit OID-basiertem, geschütztem Namenindex
   und Dump gesichert; ihre Daten und Besitzer bleiben unverändert. Der Apply
   bricht vor Änderungen ab, wenn dort aktive Clients laufen, und entfernt dann
   PUBLIC- sowie `odoo_app`/`n8n_app`-CONNECT. `verify` wiederholt die Prüfung.
   Objekte von PostgreSQL-Extensions
   und Systemobjekte behalten ihren Besitzer; weitere Anwendungsschemas sind
   nicht Teil dieses Migrationsskripts und müssen vorab separat geprüft werden.
4. Zusätzlich Anmeldung, beide Lager, Picking und n8n-Credentials am Klon
   prüfen. Erst nach erfolgreicher Probe denselben Ablauf für den geplanten
   Umstieg verwenden.

Der frühere `rollback`-Modus restaurierte nur n8n und ließ die geänderten
Odoo-Eigentümer und Teile der Rechte zurück. Er ist deshalb jetzt gesperrt und
bricht vor jeder Änderung mit einem Hinweis auf die Wiederherstellung ab.
`backup` sichert inzwischen alle angegebenen Anwendungsdatenbanken einschließlich
ihrer Objektdefinitionen und Rechte. Der geplante Rückweg für diesen Umstieg ist
der erhaltene Offline-Stand zusammen mit der vorherigen Compose-/Odoo-Konfiguration. Kein
`docker compose down -v` auf dem Originalprojekt ausführen.

## Nachweis vom 7. September 2026

Der neue Bootstrap wurde in einem isolierten PostgreSQL-16-Container auf tmpfs
ausgeführt. Beide Lager gehören `odoo_app`, n8n gehört `n8n_app`. Beide App-Rollen
konnten in ihrer Datenbank Tabellen erstellen und löschen; Verbindungen zur
jeweils fremden Datenbank wurden verweigert. Vorhandene Betriebsdaten wurden
für diese Prüfung nicht verändert. Die Zweilager-Migration ist zusätzlich mit
den ausführbaren Skripttests abgedeckt; eine Migration des Betriebsvolumes ist
damit nicht behauptet.

## Nachweis und Korrekturen vom 9. September 2026

Der zusätzliche Integrationstest startet für jeden Lauf einen neuen
PostgreSQL-16-Container ohne Netzwerkfreigabe und mit einem Wegwerf-Dateisystem.
Er führt Backup, Apply und die Positiv-/Negativprüfungen mit echtem SQL für
`lager1`, `lager2`, `n8n` und eine erhaltene Archivdatenbank aus. Die Compose-Befehle zum Stoppen/Starten sind
in diesem Test ersetzt: Er beweist die SQL-Migration und den Erhalt von Tabellen,
Views, Sequenzen, Routinen und Typen, nicht den Neustart der Anwendungen.

Ausführung aus `backend/`:

```bash
PWR_TEST_POSTGRES=1 PYTHONPATH=.deps python3 -m pytest -q ../infrastructure/tests/test_db_role_scripts_live.py
```

Die Tests deckten Fehler auf, die die bisherigen Shell-Stubs nicht erkannten:
psql ersetzt Variablen nicht im SQL-Argument von `-c`; Dump-Befehle müssen den
Legacy-Benutzer explizit wählen; ein pauschales `REASSIGN OWNED` funktioniert
nicht für den ursprünglichen Initdb-Benutzer. Das Skript überträgt deshalb nur
die genannten Anwendungsobjekte. Backupverzeichnisse müssen Modus `0700` haben.
Zusätzliche Anwendungsschemas außerhalb von `public` werden vor der
Eigentumsübertragung abgewiesen.

PostgreSQL verlangt außerdem, dass der Initdb-Benutzer (OID 10) Superuser bleibt.
Ist er die alte gemeinsame Rolle, setzt die Migration ihn auf `NOLOGIN`, erhält
aber seine notwendigen Systemrechte und Systemobjekte. Für eine normale alte
Rolle entfernt sie zusätzlich `SUPERUSER`, `CREATEDB` und `CREATEROLE`. Beide
Varianten sind getestet. „Es existiert danach nur ein Superuser“ wäre daher
eine falsche Aussage; die Anwendungen nutzen ausschließlich die begrenzten Rollen.

Der Betriebsstack wurde am 09.09. über seine vorhandenen Container gestartet
und erzeugte ein Demo-Versandlabel. Die neuen DB-Kennwörter fehlen dort noch in
der privaten `.env`; das Betriebsvolume wurde durch diesen Review nicht migriert.
