# Architektur

Diese Seite ist der Einstieg in die Architekturdokumentation des **Mobile
Picking und Voice Assistant**.

## Für Einsteiger

Beginne mit [Ebene 1: Die große Systemlandkarte](./architecture/ebene-1-systemlandkarte.md).
Sie erklärt PWA, Caddy, FastAPI, Odoo, n8n, Voice, lokale KI, PostgreSQL und
Docker ohne technisches Vorwissen.

Danach folgt [Ebene 2: Die PWA und ein normaler Auftrag](./architecture/ebene-2-pwa-normaler-auftrag.md).
Sie verfolgt Anmeldung, Auftragsliste, Claim, Scan, Positionsbestätigung und
Odoo-Abschluss Schritt für Schritt.

Die editierbaren und exportierten Grafiken liegen daneben:

- [Excalidraw-Quelle](./architecture/ebene-1-systemlandkarte.excalidraw)
- [SVG-Grafik](./architecture/ebene-1-systemlandkarte.svg)
- [Ebene-2-Excalidraw-Quelle](./architecture/ebene-2-pwa-normaler-auftrag.excalidraw)
- [Ebene-2-SVG-Grafik](./architecture/ebene-2-pwa-normaler-auftrag.svg)

## Stabile Architekturregeln

1. Die PWA spricht fachlich nur mit FastAPI, nie direkt mit Odoo, n8n oder
   PostgreSQL.
2. FastAPI ist die einzige App-API und vermittelt zwischen Browser und internen
   Diensten.
3. Odoo ist das System of Record für Aufträge, Bestand, Benutzer und Quality
   Alerts.
4. Normales Picking und Cluster-Picking werden durch FastAPI und Odoo
   abgewickelt; n8n ist dafür nicht erforderlich.
5. n8n orchestriert vor allem die asynchrone Quality-Verarbeitung. Fachliche
   Änderungen laufen kontrolliert über FastAPI zurück nach Odoo.
6. Whisper wandelt Sprache in Text, Piper Text in Sprache und Ollama führt
   lokale Text- und Bildmodelle aus.
7. Odoo und n8n nutzen getrennte Datenbanken im gemeinsamen
   PostgreSQL-Dienst. FastAPI greift nicht direkt auf diese Datenbanken zu.
8. Touch und Scanner bleiben die verlässlichen Bedienwege; Voice ist eine
   zusätzliche Eingabemöglichkeit.
9. Bei mehreren Odoo-Instanzen bleibt jede Instanz ihr eigenes System of
   Record. Daten werden nicht still zwischen Profilen vermischt.

## Lernpfad

| Ebene | Inhalt | Status |
| --- | --- | --- |
| 1 | Gesamtlandkarte und Docker-Grenze | vorhanden |
| 2 | [PWA und normaler Auftrag](./architecture/ebene-2-pwa-normaler-auftrag.md) | vorhanden |
| 3 | Cluster-Picking | geplant |
| 4 | Voice mit Whisper und Piper | geplant |
| 5 | Quality, n8n sowie Text- und Bild-KI | geplant |
| 6 | Docker, Netzwerke, Daten, Sicherheit und Fehlerfälle | geplant |

## Technische Quellen

Die Dokumentation erklärt das System. Für die verbindliche technische
Verdrahtung gelten weiterhin Code und Konfiguration:

- `docker-compose.yml` für Dienste, Profile, Netze und Volumes,
- `infrastructure/caddy/Caddyfile` für die öffentliche Eingangsschicht,
- `pwa/js/api.js` für Browser-API-Aufrufe,
- `backend/app/main.py` für die FastAPI-Router,
- `backend/app/services/` für die Abläufe,
- `odoo/addons/` für die Odoo-Fachmodelle,
- `n8n/workflow-registry.json` und `n8n/workflows/` für n8n.

Historische Spezifikationen und alte Vertragsdokumente beschreiben teilweise
frühere Ausbaustufen. Bei Widersprüchen hat der aktuelle Code Vorrang.
