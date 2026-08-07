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

## Reviewcheck vom 7. August 2026

Der normale Listen-Schritt wurde gegen Graphify, aktuellen Code, vier gezielte
Service-Tests und einen rein lesenden Abzug der lokalen Odoo-Daten geprüft:

- Graphify zeigt den Pfad `.get_open_pickings() → PickingService → OdooClient`.
- Die vier Tests für `TestGetOpenPickings` sind grün.
- Auftrag `WH/INT/00360` ergibt mit der Produktionslogik „Ente Henri“, sechs
  offene Positionen und als ersten Stopp `Brick 2x2 pink` an `L-E1-P2`.
- Ein kompletter Live-Durchlauf ist derzeit **nicht** grün: Der Odoo-Server
  läuft als Version 19, während die Datenbankmodule noch Version 18 melden.
  Die Anmeldung bricht deshalb an der fehlenden Spalte
  `res_users.totp_last_counter` ab. Beim Review wurden keine Odoo-Daten
  verändert.

Damit sind Codepfad, Projektion und Beispieldaten belegt; Login, Claim und
Buchung dürfen erst nach der Odoo-19-Datenbankmigration als live
end-to-end-verifiziert gelten.
