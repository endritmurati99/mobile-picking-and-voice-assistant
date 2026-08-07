# Ebene 1 Systemlandkarte – Review-Design

## Ziel

Die Systemlandkarte soll den aktuellen, im Repository belegten Aufbau korrekt
wiedergeben, ohne die Detaildiagramme der Ebenen 2 bis 6 vorwegzunehmen.

## Gewählter Ansatz

Die bestehende Übersicht bleibt erhalten. Ergänzt oder präzisiert werden nur
fünf belegte Punkte:

1. Der Browser erreicht PWA-Dateien und die FastAPI-Schnittstelle technisch
   ausschließlich über Caddy.
2. Caddy ist der einzige veröffentlichte Eingang und blockiert interne Routen.
3. Odoo verwaltet neben Aufträgen und Bestand auch Quality Alerts, Outbox und
   Cluster-Batches.
4. Der Quality-Weg wird in Zustellung und signierten Callback getrennt; n8n
   schreibt weder direkt nach Odoo noch direkt in dessen Datenbank.
5. Die zweite Odoo-Instanz bleibt ein kurzer Profilhinweis statt eines weiteren
   Hauptkastens.

Die drei Docker-Netze, konkrete Endpunkte und vollständige Sicherheitsmechanik
bleiben Ebene 6 beziehungsweise den Ablaufebenen vorbehalten.

## Darstellung

- SVG und Excalidraw erhalten dieselben Aussagen.
- Direkte Request/Response-Verbindungen bleiben dunkel und durchgezogen.
- Der asynchrone Quality-Hinweg und der signierte Rückweg werden als zwei
  orange gestrichelte Pfeile beschriftet.
- Ein kurzer Hinweis trennt den deklarierten Odoo-19-Aufbau vom derzeit
  blockierten Live-Migrationsstand.
- Die Beschriftungen bleiben auch in der eingebetteten Dokumentansicht lesbar.

## Begleittext und Scorecard

Die Markdown-Seite erklärt die neuen Bilddetails und enthält eine kompakte
Scorecard mit fünf gleich gewichteten Kriterien:

- Komponentenabdeckung,
- Verbindungsgenauigkeit,
- Übereinstimmung mit Code und Compose,
- Verständlichkeit,
- angemessene Detailtiefe.

Jedes Kriterium erhält bis zu 20 Punkte. Abweichungen zwischen deklarierter
Architektur und Live-Laufzeit werden ausdrücklich benannt und nicht als
erfolgreicher End-to-End-Stand dargestellt.

## Prüfung

- Excalidraw muss gültiges JSON sein.
- SVG muss gültiges XML sein und ohne abgeschnittene Texte rendern.
- Alle sichtbaren Kanten werden gegen Compose, Caddy und die beteiligten
  Backend-Clients geprüft.
- Veraltete Aussagen sowie widersprüchliche Quality-Verbindungen dürfen in den
  drei Ebene-1-Dateien nicht verbleiben.

