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

Die weiteren Ebenen vervollständigen den Lernpfad:

- [Ebene 3: Cluster-Picking](./architecture/ebene-3-cluster-picking.md)
- [Ebene 4: Voice mit Whisper und Piper](./architecture/ebene-4-voice.md)
- [Ebene 5: Quality, n8n sowie Text- und Bild-KI](./architecture/ebene-5-quality-n8n-ki.md)
- [Ebene 6: Docker, Netzwerke, Daten und Sicherheit](./architecture/ebene-6-docker-daten-sicherheit.md)
- [Ebene 7: Intent, Problemerkennung und Ollama](./architecture/ebene-7-intent-problemerkennung-ollama.md)
- [Ebene 8: Fehler, Offline und Wiederanlauf](./architecture/ebene-8-fehler-offline-wiederanlauf.md)
- [Ebene 9: Mitarbeiterreise](./architecture/ebene-9-mitarbeiterreise.md)
- [Ebene 10: Status und Lebenszyklen](./architecture/ebene-10-status-und-lebenszyklen.md)
- [Ebene 11: Rollen, Rechte und Datenhoheit](./architecture/ebene-11-rollen-rechte-datenhoheit.md)
- [Ebene 12: Login, Benutzer und Geräte](./architecture/ebene-12-login-benutzer-geraete.md)
- [Ebene 13: Clusterbildung und Lagerorte](./architecture/ebene-13-clusterbildung-und-lagerorte.md)

Die editierbaren und exportierten Grafiken liegen daneben:

- [Excalidraw-Quelle](./architecture/ebene-1-systemlandkarte.excalidraw)
- [SVG-Grafik](./architecture/ebene-1-systemlandkarte.svg)
- [Ebene-2-Excalidraw-Quelle](./architecture/ebene-2-pwa-normaler-auftrag.excalidraw)
- [Ebene-2-SVG-Grafik](./architecture/ebene-2-pwa-normaler-auftrag.svg)
- [Ebene-3-Excalidraw-Quelle](./architecture/ebene-3-cluster-picking.excalidraw)
- [Ebene-3-SVG-Grafik](./architecture/ebene-3-cluster-picking.svg)
- [Ebene-4-Excalidraw-Quelle](./architecture/ebene-4-voice.excalidraw)
- [Ebene-4-SVG-Grafik](./architecture/ebene-4-voice.svg)
- [Ebene-5-Excalidraw-Quelle](./architecture/ebene-5-quality-n8n-ki.excalidraw)
- [Ebene-5-SVG-Grafik](./architecture/ebene-5-quality-n8n-ki.svg)
- [Ebene-6-Excalidraw-Quelle](./architecture/ebene-6-docker-daten-sicherheit.excalidraw)
- [Ebene-6-SVG-Grafik](./architecture/ebene-6-docker-daten-sicherheit.svg)
- [Ebene-12-Excalidraw-Quelle](./architecture/ebene-12-login-benutzer-geraete.excalidraw)
- [Ebene-12-SVG-Grafik](./architecture/ebene-12-login-benutzer-geraete.svg)

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
| 3 | [Cluster-Picking](./architecture/ebene-3-cluster-picking.md) | vorhanden |
| 4 | [Voice mit Whisper und Piper](./architecture/ebene-4-voice.md) | vorhanden |
| 5 | [Quality, n8n sowie Text- und Bild-KI](./architecture/ebene-5-quality-n8n-ki.md) | vorhanden |
| 6 | [Docker, Netzwerke, Daten, Sicherheit und Fehlerfälle](./architecture/ebene-6-docker-daten-sicherheit.md) | vorhanden |
| 7 | [Intent, Problemerkennung und Ollama](./architecture/ebene-7-intent-problemerkennung-ollama.md) | vorhanden |
| 8 | [Fehler, Offline und Wiederanlauf](./architecture/ebene-8-fehler-offline-wiederanlauf.md) | vorhanden |
| 9 | [Mitarbeiterreise](./architecture/ebene-9-mitarbeiterreise.md) | vorhanden |
| 10 | [Status und Lebenszyklen](./architecture/ebene-10-status-und-lebenszyklen.md) | vorhanden |
| 11 | [Rollen, Rechte und Datenhoheit](./architecture/ebene-11-rollen-rechte-datenhoheit.md) | vorhanden |
| 12 | [Login, Benutzer und Geräte](./architecture/ebene-12-login-benutzer-geraete.md) | vorhanden |
| 13 | [Clusterbildung und Lagerorte](./architecture/ebene-13-clusterbildung-und-lagerorte.md) | vorhanden |

## Aktueller Bezug

Die Beschreibungen zeigen, wie das System heute arbeitet. Für Details dient der
jeweilige Ablauf in den Ebenen; Standorte und Daten bleiben dabei getrennt.
