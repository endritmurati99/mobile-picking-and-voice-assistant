# Mobile Picking und Voice Assistant

Eine mobile Unterstützung für die Kommissionierung an zwei getrennten
Standorten: **Lager 1** und **Lager 2**.

Die App wird am Handy genutzt. Mitarbeitende melden sich an, wählen ihren
Standort und bearbeiten Aufträge mit Scanner, Kamera oder Touch. Sprachbefehle
unterstützen dabei, ersetzen aber keine sichere Bestätigung.

## Was dazugehört

| Bereich | Wofür er da ist |
| --- | --- |
| PWA | Die App auf Handy und PC für Anmeldung, Aufträge, Scan und Bestätigung. |
| Odoo 19 | Hält Aufträge, Bestände, Personen und Buchungen je Standort. |
| Voice | Versteht kurze Sprachbefehle und gibt Rückmeldungen. |
| Quality | Nimmt Auffälligkeiten mit Beschreibung und optionalen Fotos auf. |
| n8n | Bearbeitet Quality-Fälle im Hintergrund. |

## Zwei Standorte

Lager 1 und Lager 2 bleiben getrennt. Der gewählte Standort bestimmt, welche
Aufträge und Bestände in der App angezeigt werden.

## Screenshots vom 27. August 2026

- [PWA-Anmeldung auf dem Handy](docs/screenshots/aktuell/pwa-anmeldung-mobil-2026-08-27.png)
- [Odoo – Lager 1](docs/screenshots/aktuell/odoo-lager-1-anmeldung-2026-08-27.png)
- [Odoo – Lager 2](docs/screenshots/aktuell/odoo-lager-2-anmeldung-2026-08-27.png)
- [n8n-Anmeldung](docs/screenshots/aktuell/n8n-anmeldung-2026-08-27.png)

Weitere Erklärungen stehen in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).
