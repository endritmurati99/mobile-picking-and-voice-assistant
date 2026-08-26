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

Die editierbaren Excalidraw-Quellen und die exportierten SVG-Grafiken liegen
jeweils neben dem Markdown-Dokument und tragen denselben Dateistamm. Ebenen 1
bis 10 sowie 12 und 13 besitzen beide Fassungen; Ebene 11 besitzt derzeit nur
die direkt lesbare SVG-Fassung.

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
   lokale Text- und Bildmodelle aus. Der Einbettungsdienst gleicht Artikel mit
   DINOv2 und einem Farbkanal gegen den Katalog ab.
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

## Nächste sinnvolle Vertiefungen

Die Ebenen sollen nicht dieselbe Architektur mehrfach erzählen. Deshalb werden
vorhandene Ebenen zuerst vertieft und nur eine neue Querschnittsebene ergänzt:

| Priorität | Verbesserung | Inhalt |
| ---: | --- | --- |
| 1 | **Ebene 3 und 13: Cluster** | Aktualisiert: Sammelentnahme am Lagerort, getrennte Kartonaufteilungen, PWA-Projektion, Odoo-JSON-RPC und Docker-Laufweg. |
| 2 | **Ebene 2: PWA-Innenansicht ausbauen** | Seitenhülle, ES-Module, Browserzustand, Rendering, Scanner-/Kameraadapter, Service Worker und API-Grenze genauer erklären. |
| 3 | **Ebene 6: Änderungs- und Deployment-Matrix ergänzen** | Zeigen, wann ein Browser-Reload, Uvicorn-Reload, Container-Recreate, Image-Rebuild oder Odoo-Modul-Upgrade nötig ist. |
| 4 | **Neue Ebene 14: Vom Browser durch FastAPI bis Odoo** | Den wiederverwendbaren Anfragepfad `api.js → Caddy → Middleware → Router → Dependency → Service → RuntimeServices → OdooClient → JSON-RPC` an einem GET- und einem POST-Beispiel erklären. |

Eine eigene weitere Ebene nur für „PWA“ oder nur für „Docker“ wäre derzeit
doppelt: Ebene 2 besitzt bereits den Browserablauf und Ebene 6 die vollständige
Container- und Netzwerkgrenze. Ebene 14 ist sinnvoll, weil der generische
technische Anfragepfad bisher nur verteilt über mehrere Fachdokumente vorkommt.

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

Historische Spezifikationen, Scorecards und datierte Reviewabschnitte
beschreiben teilweise frühere Ausbaustufen. Ihre damaligen Tests und Nachweise
liegen im privaten Evidence-Archiv. Bei Widersprüchen haben aktueller Code,
Compose und Workflow-Registry Vorrang.

## Historischer Reviewcheck vom 13. August 2026

Der normale Listen-Schritt wurde gegen Graphify, aktuellen Code, vier gezielte
Service-Tests und einen rein lesenden Abzug der lokalen Odoo-Daten geprüft:

- Graphify zeigt den Pfad `.get_open_pickings() → PickingService → OdooClient`.
- Die vier Tests für `TestGetOpenPickings` sind grün.
- Auftrag `WH/INT/00360` ergibt mit der Produktionslogik „Ente Henri“, sechs
  offene Positionen und als ersten Stopp `Brick 2x2 pink` an `L-E1-P2`.
- Der frühere Odoo-18/19-Migrationsfehler ist behoben. Lena und Max wurden mit
  ihren Odoo-Zugangsdaten erfolgreich über die PWA angemeldet.

Damit sind Codepfad, Projektion, Beispieldaten und der Login gegen die aktuelle
Odoo-19-Datenbank live belegt. Claim und Buchung bleiben eigene Prüfschritte.
