# DB-Rollenmigration am Betriebsdaten-Klon

Stand: 9. September 2026. Die SQL-Probe am verifizierten Offline-Klon ist
erfolgreich. Eine Umstellung des Betriebsvolumes oder ein Start der Anwendungen
mit den neuen Rollen ist damit nicht freigegeben oder nachgewiesen.

## Nachweise

- Docker Desktop gestartet; vorhandenes PostgreSQL und Odoo sind gesund.
- Odoo und PostgreSQL für die Offline-Kopie gestoppt und danach im bisherigen
  Stand wieder gestartet. Das Originalvolume wurde nicht migriert.
- `clone-postgres-volume.sh create` hat den etwa 851 MiB großen Datenbestand
  kopiert und identische SHA-256-Dateimanifeste sowie PG_VERSION bestätigt.
- `assert-target` hat den Klon anhand von Volumename und Identitätsmarker
  bestätigt. Der Probecontainer hat `--network none` und keine Portfreigaben.
- Backup und Apply der vorhandenen Migrationsskripte auf dem Klon: Exit 0.
  Die Compose-Befehle wurden durch einen auf die erwarteten Aufrufe begrenzten
  Stub ersetzt. Dies ist ausschließlich ein SQL-Nachweis.
- Die separate Verifikation über TCP (`PGHOST=127.0.0.1`) und die geschützten
  Kennwortdateien bestand: Zugriff auf eigene Datenbanken möglich, n8n-Zugriff
  auf beide Lager und Odoo-Zugriff auf n8n verweigert.
- Alle öffentlichen Tabellen sind unter den neuen App-Rollen lesbar und haben
  exakt dieselben Zeilenzahlen wie vor Apply: 353 in lager1, 353 in lager2,
  62 in n8n, insgesamt 768 Tabellen.
- Beide App-Rollen sind weder Superuser noch CREATEDB/CREATEROLE. Der alte
  Initdb-Benutzer bleibt technisch Superuser, ist aber NOLOGIN.
- Beide vorhandenen PostgreSQL-Livetestvarianten bestanden, Exit 0.

## Gefundener Testfehler

Der erste Livetest erkannte den temporären Init-Server über den Unix-Socket
als bereit und verlor anschließend beim Init-Neustart die Verbindung.
Der Entry-Point des PostgreSQL-Images bestätigt `listen_addresses=''` für
diesen temporären Server. `pg_isready -h 127.0.0.1` wartet auf den endgültigen
Server. Nur diese Bereitschaftsprüfung und ihr erklärender Kommentar wurden
im Test geändert; der folgende vollständige Lauf beider Varianten bestand.

Der erste Apply-Aufruf der Klonprobe endete nach erfolgreicher SQL-Migration,
weil der lokale Probe-Stub den abschließenden Backend-Start noch nicht kannte.
Nach Ergänzung dieses erwarteten Aufrufs und vorübergehender Wiederfreigabe
des Legacy-Logins ausschließlich am Klon bestand der wiederholte Apply-Aufruf.

## Blocker für die Betriebsumstellung

Außer postgres und den drei Ziel-Datenbanken existieren zwölf weitere
Datenbanken. Nach der Migration haben beide App-Rollen auf alle zwölf
weiterhin CONNECT. Die aktuellen Skripte isolieren und prüfen nur die drei
genannten Ziele. CONNECT allein beweist keinen lesbaren Tabelleninhalt;
die vollständige Zugriffsabgrenzung des Clusters ist aber nicht erreicht.

Die zusätzlichen Datenbanken sind:

- `l1fixr1_final_masterfischer_o19_20260904t134644z`
- `lager1_odoo18_alt`, `lager2_odoo18_alt`
- `masterfischer_o19_foundation_test`, `masterfischer_o19_trial`
- `odoo19_smoke_codex`
- `picking`, `picking_test`, `pwr_test`
- `task5_lager2_o19_20260904t084644z`
- `task5_masterfischer_o19_20260904t084644z`
- `task5_n8n_20260904t084644z`

Vor der Umstellung ist zu klären, welche davon noch aktiv verwendet werden
und welche Eigentümer und Zugriffsrechte sie benötigen. Keine wurde gelöscht
oder auf dem Original verändert. Zudem fehlen im Betriebs-.env weiterhin
ODOO_DB_PASSWORD und N8N_DB_PASSWORD. Die zufälligen Probe-Kennwörter wurden
ausschließlich im isolierten Klon hinterlegt und sind keine Betriebsentscheidung.

## Fortsetzung

Der Kloncontainer `pwr-dbrole-clone-20260909-1517` ist gestoppt und erhalten,
das Klonvolume heißt `pwr_dbrole_clone_20260909_1517`. Geschützte lokale
Manifeste, ein zusätzlich exportiertes Backup und Protokolle liegen unter
`/home/endri/audits/picking-db-clone-20260909-1517/`; keine dieser Rohdateien
gehört in Git. Das ursprüngliche Dateimanifest belegt den Stand vor Apply;
nach der Migration ist keine Bytegleichheit mit dem Original zu erwarten.

Als Nächstes die Alt-Datenbanken klassifizieren und die gewünschte Rechtepolitik
am Klon prüfen. Danach einen isolierten Anwendungsstart einschließlich Odoo,
n8n-Credentials und Backend nachweisen. Erst anschließend den Betriebsumstieg
planen. Handy-, Versand- und Ausfalltests bleiben offen.
