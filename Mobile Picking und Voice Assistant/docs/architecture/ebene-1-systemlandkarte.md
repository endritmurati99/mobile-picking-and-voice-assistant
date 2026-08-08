# Ebene 1: Die große Systemlandkarte

Diese Ebene erklärt das Projekt so, als würdest du es zum ersten Mal sehen.
Du musst weder programmieren können noch wissen, was eine API oder ein Container
ist.

## Die Erklärung in 30 Sekunden

Ein Mitarbeiter bedient die **PWA** auf einem Handy oder Computer. Die PWA ist
die sichtbare Anwendung mit Auftragsliste, Scanner, Kamera, Mikrofon und
Schaltflächen.

Die PWA spricht mit **FastAPI**. FastAPI ist die zentrale Drehscheibe. Es prüft
die Anfrage und spricht danach mit dem passenden internen Dienst:

- **Odoo** kennt Aufträge, Lagerbestand und Benutzer.
- **n8n** führt längere Quality-Abläufe aus.
- **Whisper** wandelt gesprochene Sprache in Text um.
- **Piper** wandelt Text in gesprochene Sprache um.
- **Ollama** führt die lokale Text- und Bild-KI aus.

> **Wichtigster Merksatz:** Die PWA spricht mit FastAPI. FastAPI spricht mit
> den internen Diensten.

## Das ganze System als Bild

![Systemlandkarte mit PWA, Caddy, FastAPI, Odoo, n8n, Sprachdiensten, lokaler KI und PostgreSQL](./ebene-1-systemlandkarte.svg)

Die [Excalidraw-Quelldatei](./ebene-1-systemlandkarte.excalidraw) ist die
editierbare Fassung der Grafik. Die
[SVG-Datei](./ebene-1-systemlandkarte.svg) eignet sich für Dokumente,
Präsentationen und die Bachelorarbeit.

So liest du das Bild:

- Ein **durchgezogener Pfeil** bedeutet: Ein Dienst ruft einen anderen direkt
  auf und wartet auf seine Antwort.
- Ein **orange gestrichelter Pfeil** bedeutet: Eine gerichtete Quality-
  Nachricht läuft asynchron. Die PWA muss nicht auf die gesamte Verarbeitung
  warten.
- Der große gestrichelte **Docker-Rahmen** zeigt die Serverdienste.
- Mensch, Handy und Browser liegen außerhalb des Docker-Rahmens.

Der Browser erreicht beide Ziele technisch über Caddy: Webseitenaufrufe gehen
zum PWA-Dateiserver, `/api/*` geht zu FastAPI. „Die PWA spricht mit FastAPI“
beschreibt die fachliche Beziehung, nicht eine Umgehung von Caddy.

Der orange Quality-Weg besteht aus zwei getrennten Aufrufen: FastAPI stellt ein
Outbox-Ereignis an n8n zu; n8n sendet den signierten Status an eine interne
FastAPI-Route zurück. n8n schreibt weder direkt nach Odoo noch direkt in dessen
Datenbank.

## Eine Alltagsvorstellung

Stell dir das System wie ein Lagergebäude vor:

- Die **PWA** ist das Arbeitsgerät des Mitarbeiters.
- **Caddy** ist die Eingangstür und der Wegweiser am Empfang.
- **FastAPI** ist die Person am Leitstand. Sie nimmt jede Anfrage entgegen und
  schickt sie an die richtige Stelle.
- **Odoo** ist das offizielle Lagerbuch. Was dort steht, gilt fachlich.
- **n8n** ist ein Ablaufplan für Arbeiten mit mehreren Stationen.
- **Whisper** ist ein Zuhörer und **Piper** ein Sprecher.
- **Ollama** ist ein lokaler Assistent für Text- und Bildbewertung.
- **PostgreSQL** ist der Aktenschrank, in dem Odoo und n8n getrennte Fächer
  besitzen.
- **Docker** ist das Gebäude, in dem diese Serverdienste in getrennten Räumen
  laufen.

Die Vergleiche helfen beim Einstieg. Technisch sind diese Bausteine Programme,
die über Netzwerkaufrufe miteinander sprechen.

## Die Bausteine einzeln erklärt

### Mensch, Gerät und Browser

Der Kommissionierer arbeitet mit Handy, Tablet oder Computer. Scanner, Kamera,
Mikrofon und Touch-Eingabe gehören zum Gerät. Der Browser führt die PWA aus.

Diese Dinge laufen **nicht** in Docker. Docker kann keine echte Handykamera und
keinen Barcode-Scanner ersetzen.

### PWA: die sichtbare Anwendung

**PWA** bedeutet „Progressive Web App“. Vereinfacht ist sie eine Webseite, die
sich wie eine installierte App benutzen lässt.

Die PWA:

- zeigt Aufträge und Positionen an,
- reagiert auf Touch, Scanner, Kamera und Mikrofon,
- merkt sich vorübergehend den sichtbaren Arbeitszustand,
- sendet fachliche Anfragen an FastAPI.

Die PWA entscheidet nicht selbst, was der echte Lagerbestand ist. Sie schreibt
auch nicht direkt nach Odoo oder PostgreSQL.

Im System gibt es zwei Dinge mit dem Namen PWA:

1. Ein kleiner Docker-Dienst liefert HTML, CSS und JavaScript aus.
2. Nachdem diese Dateien geladen wurden, läuft die eigentliche PWA im Browser.

### Caddy: die Eingangstür

Caddy ist der erste Server, den der Browser erreicht.

- Ein normaler Webseitenaufruf wird zum PWA-Dateiserver geleitet.
- Ein Aufruf unter `/api/*` wird zu FastAPI geleitet.
- Interne Routen werden nach außen blockiert.
- Die verschlüsselte HTTPS-Verbindung endet bei Caddy.

Caddy versteht keine Lageraufträge. Es verteilt nur den Netzwerkverkehr.

### FastAPI: die zentrale Drehscheibe

FastAPI ist das Python-Backend und die einzige fachliche API für die PWA.

**API** bedeutet „Programmierschnittstelle“. Eine API ist eine vereinbarte Tür,
durch die Programme miteinander sprechen. API bedeutet **nicht** KI.

FastAPI:

- prüft Anmeldung, Berechtigung und Eingaben,
- entscheidet, welcher interne Dienst gebraucht wird,
- übersetzt zwischen der PWA und Odoo,
- koordiniert Voice-, Quality- und Cluster-Abläufe,
- gibt der PWA eine verständliche Antwort zurück.

FastAPI speichert die fachlichen Daten nicht selbst in PostgreSQL. Für
Lagerdaten spricht es per JSON-RPC mit Odoo.

### Odoo 19: die fachliche Wahrheit

Odoo ist das ERP-System und das **System of Record**. Das bedeutet: Odoo ist
die offizielle Quelle für den fachlichen Zustand.

Odoo kennt unter anderem:

- Aufträge und Pickings,
- Lagerplätze und Bestände,
- Produkt- und Seriennummern,
- Benutzer und Berechtigungen,
- Quality Alerts,
- Integrationsjobs und Outbox-Ereignisse,
- Cluster-Batches und Zielpakete.

Wenn die PWA einen Auftrag als abgeschlossen zeigt, muss dieser Zustand aus
Odoo kommen. Eine bloße grüne Anzeige im Browser wäre kein fachlicher Beweis.

### n8n: der Workflow-Motor

n8n führt Abläufe aus, die mehrere Schritte und Rückmeldungen besitzen. Im
aktuellen Kernsystem betrifft das vor allem die asynchrone
Quality-Verarbeitung.

n8n ist **nicht** das Backend der PWA und liegt nicht im normalen Picking-Weg.
Auch Cluster-Picking braucht n8n nicht.

n8n spricht für fachliche Prüfungen und Änderungen wieder mit FastAPI. Es
schreibt nicht direkt nach Odoo.

### Whisper und Piper: hören und sprechen

- **Whisper** erhält eine Audiodatei und liefert erkannten Text zurück.
- **Piper** erhält Text und liefert eine gesprochene Audiodatei zurück.

Beide sind lokale Dienste. Der Browser spricht nicht direkt mit ihnen. FastAPI
nimmt die Anfrage entgegen und ruft den passenden Dienst auf.

### Ollama: lokale KI

Ollama führt lokale Sprach- und Bildmodelle aus. Es wird beispielsweise für
unsichere Sprachabsichten sowie Text- und Bildbefunde bei Quality Alerts
verwendet.

Ollama entscheidet nicht über Lagerbestand und schließt keinen Auftrag ab.
Fachliche Ergebnisse werden kontrolliert über FastAPI nach Odoo geschrieben.

### PostgreSQL: getrennte Datenfächer

PostgreSQL ist der Datenbankdienst. Im Projekt läuft ein PostgreSQL-Server mit
getrennten Datenbanken:

- Odoo verwendet seine Odoo-Datenbanken.
- n8n verwendet eine eigene n8n-Datenbank.

„Ein Server“ bedeutet deshalb nicht „alle Daten liegen vermischt in einer
Datenbank“. Odoo und n8n besitzen getrennte logische Fächer.

## Was Docker hier macht

Docker startet die Serverprogramme in getrennten **Containern**. Ein Container
ist ein abgegrenzter Laufraum für einen Dienst. Er ist leichter und gezielter
als ein eigener vollständiger Computer.

Die Hauptkonfiguration definiert neun normale Dienste:

1. `caddy`
2. `db`
3. `odoo`
4. `backend`
5. `whisper`
6. `piper`
7. `ollama`
8. `n8n`
9. `pwa`

Zwei zusätzliche Profildienste werden nur bei Bedarf gestartet:

- `odoo-lager-2` für eine zweite Odoo-Instanz,
- `n8n-credentials` als einmaliger Einrichtungshelfer.

Damit sind **elf Dienste konfiguriert**, aber nicht zwingend alle gleichzeitig
aktiv. Die Anzahl laufender Container hängt von den gewählten Profilen ab.

Docker enthält die serverseitige Laufzeit. Außerhalb bleiben unter anderem:

- Browser und PWA-Ausführung auf dem Endgerät,
- Scanner, Kamera und Mikrofon,
- Docker Engine beziehungsweise Docker Desktop,
- Quellcode, lokale Konfiguration, Zertifikate und Secret-Quelldateien auf dem
  Host.

## Beispiel 1: Ein geprüfter normaler Auftrag

Der rein lesende Review vom 7. August 2026 fand in Odoo den offenen Auftrag
`WH/INT/00360` für das Modell „Ente Henri“ mit sechs Positionen. Ebene 1 nutzt
nur diesen belegten Hauptweg; Artikel, Lagerplätze und Barcodes erklärt
[Ebene 2](./ebene-2-pwa-normaler-auftrag.md) im Detail.

1. Die PWA fragt FastAPI nach offenen Aufträgen.
2. FastAPI fragt Odoo nach den fachlich offenen Pickings.
3. Odoo antwortet. FastAPI bereitet die Daten für die PWA auf.
4. Der Mitarbeiter öffnet `WH/INT/00360`. FastAPI lässt den Auftrag in Odoo für
   diesen Mitarbeiter reservieren.
5. Die PWA zeigt die nächste Position und wartet auf den Scan.
6. Der Barcode wird zunächst im Browser gelesen.
7. Zur Bestätigung sendet die PWA die Position an FastAPI.
8. FastAPI prüft erneut Barcode, Bestand, Reservierung und Eingaben.
9. FastAPI schreibt die bestätigte Menge nach Odoo.
10. Nach der letzten Position lässt FastAPI den Auftrag durch Odoo validieren.

```text
Mensch → PWA → FastAPI → Odoo
```

n8n und Ollama werden für diesen normalen Ablauf nicht benötigt.

## Beispiel 2: Ein Clusterauftrag

„Cluster“ bedeutet hier **Sammelkommissionierung**, nicht Server-Cluster.

Angenommen, vier getrennte Aufträge liegen in ähnlichen Lagerzonen:

- `WH/OUT/0101`
- `WH/OUT/0102`
- `WH/OUT/0103`
- `WH/OUT/0104`

1. Die PWA fragt FastAPI nach geeigneten Aufträgen.
2. FastAPI liest die Kandidaten aus Odoo und bildet einen Vorschlag.
3. Der Mitarbeiter startet den Cluster.
4. FastAPI erstellt in Odoo einen echten `stock.picking.batch`.
5. Jeder Auftrag erhält weiterhin seinen eigenen Zielkarton.
6. Die PWA zeigt eine gemeinsame, sortierte Laufliste.
7. Jede bestätigte Position wird über FastAPI nach Odoo geschrieben.
8. Am Ende lässt FastAPI den gesamten Batch in Odoo abschließen.

```text
Mensch → PWA → FastAPI → Odoo-Batch
```

Die Aufträge werden nicht zu einem einzigen Auftrag verschmolzen. n8n und KI
sind auch für diesen Ablauf nicht notwendig.

## Beispiel 3: Eine Qualitätsmeldung

Eine Qualitätsmeldung darf länger im Hintergrund verarbeitet werden. Deshalb
kommt hier n8n ins Spiel.

1. Die PWA sendet Beschreibung und gegebenenfalls Bilder an FastAPI.
2. FastAPI legt den Quality Alert in Odoo an.
3. Ein Odoo-Outbox-Ereignis wird von FastAPI signiert an n8n übergeben.
4. n8n ruft für die Bewertung wieder interne FastAPI-Routen auf.
5. FastAPI kann Text und Bilder lokal durch Ollama untersuchen lassen.
6. Das Ergebnis läuft über FastAPI zurück nach Odoo.
7. Die PWA kann später den gespeicherten Status aus Odoo anzeigen.

```text
PWA → FastAPI → Odoo-Outbox → FastAPI → n8n
                                      ↔ FastAPI ↔ Ollama
                                      → FastAPI → Odoo
```

Die zusätzlichen Schleifen machen den Ablauf robuster: n8n bekommt keinen
direkten freien Schreibzugriff auf Odoo.

## Häufige Verwechslungen

### API ist nicht KI

- **API**: eine Schnittstelle, über die Programme sprechen.
- **KI**: ein Modell, das beispielsweise Text oder Bilder bewertet.

FastAPI ist ein API-Framework. Ollama führt die lokalen KI-Modelle aus.

### PWA ist nicht nur der PWA-Container

Der Container liefert die Programmdateien. Die eigentliche Bedienoberfläche
läuft danach im Browser des Endgeräts.

### Cluster-Picking ist kein Server-Cluster

Cluster-Picking bündelt mehrere Lageraufträge zu einer gemeinsamen Laufliste.
Es verteilt keine Rechenlast auf mehrere Server.

### n8n steuert nicht alles

Normales Picking, Cluster-Picking, Anmeldung und direkte Odoo-Abfragen laufen
über FastAPI und Odoo. n8n ist vor allem für den asynchronen Quality-Workflow
da.

### Ein PostgreSQL-Dienst ist nicht nur eine Datenbank

Der Dienst kann mehrere getrennte Datenbanken verwalten. Odoo und n8n verwenden
hier getrennte Datenbanken.

## Wo findet man das im Code?

Für Ebene 1 reichen diese Einstiegspunkte:

| Frage | Einstieg im Projekt |
| --- | --- |
| Welche Docker-Dienste gibt es? | `docker-compose.yml` |
| Wie verteilt die Eingangstür Anfragen? | `infrastructure/caddy/Caddyfile` |
| Wo startet die PWA? | `pwa/index.html` und `pwa/js/app.js` |
| Wo sendet die PWA API-Aufrufe? | `pwa/js/api.js` |
| Wo werden FastAPI-Routen zusammengebaut? | `backend/app/main.py` |
| Wo liegen normale Picking- und Cluster-Abläufe? | `backend/app/services/picking_service.py` und `backend/app/services/cluster_service.py` |
| Wo liegen Voice, Text-KI und Bild-KI? | `backend/app/routers/voice.py`, `backend/app/services/llm_client.py` und `backend/app/services/vision_client.py` |
| Wo liegt der aktive Quality-Workflow? | `n8n/workflows/quality-assessment-v2.json` |
| Wo liegen die Odoo-Erweiterungen? | `odoo/addons/` |

Die Zeilennummern werden bewusst nicht hier festgeschrieben. Sie ändern sich
bei jeder Codeänderung; die Dateigrenzen sind die stabileren Wegweiser.

## Was Ebene 1 bewusst noch nicht erklärt

Ebene 1 zeigt die große Landkarte. Diese Details kommen später:

1. **Ebene 2:** PWA und normaler Auftrag – Bildschirm für Bildschirm und Aufruf
   für Aufruf.
2. **Ebene 3:** Cluster-Picking – Vorschlag, Batch, Kartons, Rundgang und
   Abschluss.
3. **Ebene 4:** Voice – Mikrofon, Whisper, Intent-Erkennung und Piper.
4. **Ebene 5:** Quality – Odoo-Outbox, FastAPI, n8n sowie Text- und Bild-KI.
5. **Ebene 6:** Docker, Netzwerke, Datenhaltung, Sicherheit und Fehlerfälle.

Begriffe wie Session, CSRF, Idempotenz, HMAC, Nonce, Lease und Datenbankrollen
sind wichtig. Sie gehören aber nicht auf die erste Landkarte, weil sie den
Einstieg verdecken würden.

## Review-Scorecard

Stand: 8. August 2026. Bewertet wurde die überarbeitete Darstellung gegen
Compose, Caddy, FastAPI-Runtime, Browserzugriffe und die beteiligten Clients.

| Kriterium | Punkte |
| --- | ---: |
| Komponentenabdeckung | 20/20 |
| Verbindungsgenauigkeit | 20/20 |
| Übereinstimmung mit Code und Compose | 19/20 |
| Verständlichkeit | 19/20 |
| Angemessene Detailtiefe | 19/20 |
| **Gesamt** | **97/100** |

Der deklarierte Aufbau verwendet Odoo 19. Der zuletzt geprüfte Live-Stand ist
noch kein grüner End-to-End-Nachweis: Server und Datenbankschema befinden sich
bis zum abgeschlossenen Modul- und Schema-Upgrade nicht auf demselben Stand.
Die Systemlandkarte bewertet deshalb die belegte Verdrahtung, nicht eine bereits
erfolgreich abgeschlossene Live-Migration.

## Drei Regeln zum Mitnehmen

1. Die PWA spricht nur mit FastAPI.
2. Odoo ist die fachliche Wahrheit.
3. n8n unterstützt längere Quality-Abläufe; normales Picking und Cluster laufen
   ohne n8n.
