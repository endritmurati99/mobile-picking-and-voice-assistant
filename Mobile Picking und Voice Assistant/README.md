# Mobile Picking und Voice Assistant

Eine mobile Unterstützung für die Kommissionierung an zwei getrennten Standorten: **Lager 1** und **Lager 2**.

Die App wird am Handy genutzt. Mitarbeitende melden sich an, wählen ihren Standort und bearbeiten Aufträge mit Scanner, Kamera oder Touch. Sprachbefehle unterstützen dabei, ersetzen aber keine sichere Bestätigung.

## Was dazugehört

| Bereich | Wofür er da ist |
| --- | --- |
| PWA | Die App auf Handy und PC für Anmeldung, Aufträge, Scan und Bestätigung. |
| Odoo 19 | Hält Aufträge, Bestände, Personen und Buchungen je Standort. |
| Voice | Versteht kurze Sprachbefehle und gibt Rückmeldungen. |
| Quality | Nimmt Auffälligkeiten mit Beschreibung und optionalen Fotos auf. |
| n8n | Bearbeitet Quality-Fälle im Hintergrund und erzeugt nach Pick-Abschluss das Versandlabel. |

## Zwei Standorte

Lager 1 und Lager 2 bleiben getrennt. Der gewählte Standort bestimmt, welche Aufträge und Bestände in der App angezeigt werden.

## Starten

Die Zugangsdaten und Secrets sind absichtlich nicht als Vorlage im Repository enthalten. Eine private `.env` mit restriktiven Rechten anlegen, die benötigten Werte für Compose eintragen und dann starten:

```bash
install -m 600 /dev/null .env
# Werte in .env eintragen
make up
```

`make up` wartet auf die Compose-Healthchecks und meldet einen nicht bereiten Dienst als Fehler. Die Basis-Compose-Datei startet ohne Uvicorn-Reload. Für lokale Entwicklung kann die private `.env` das Overlay aktivieren:

```dotenv
COMPOSE_PATH_SEPARATOR=;
COMPOSE_FILE=docker-compose.yml;docker-compose.dev.yml
COMPOSE_PROFILES=second-odoo
```

Ein neues PostgreSQL-Volume legt `lager1`, `lager2` und `n8n` samt getrennten App-Rollen an. Odoo-Module und Benutzer werden anschließend wie bei jeder neuen Odoo-Installation eingerichtet.

Ein vorhandenes PostgreSQL-Volume darf nicht allein mit neuen `ODOO_DB_PASSWORD`- und `N8N_DB_PASSWORD`-Werten neu gestartet werden. Rollen und Eigentümer müssen zuvor nach dem [DB-Rollen-Migrationsablauf](docs/runbooks/n8n-db-role-migration.md) auf einem Offline-Klon geprüft und im Wartungsfenster migriert werden.

## Screenshots vom 27. August 2026

- [PWA-Anmeldung auf dem Handy](docs/screenshots/aktuell/pwa-anmeldung-mobil-2026-08-27.png)
- [Odoo – Lager 1](docs/screenshots/aktuell/odoo-lager-1-anmeldung-2026-08-27.png)
- [Odoo – Lager 2](docs/screenshots/aktuell/odoo-lager-2-anmeldung-2026-08-27.png)
- [n8n-Anmeldung](docs/screenshots/aktuell/n8n-anmeldung-2026-08-27.png)

Weitere Erklärungen stehen in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).
