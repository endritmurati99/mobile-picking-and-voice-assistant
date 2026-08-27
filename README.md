# Mobile Picking und Voice Assistant

Diese Bachelorarbeit untersucht einen lokalen Lagerassistenten für normales
und gebündeltes Kommissionieren. Die Anwendung verbindet Odoo 19 mit einer
mobilen Oberfläche, Scanner, Sprache, Fotos und lokaler KI.

Untersucht wird, wie ein bestehendes ERP für die Arbeit am Smartphone ergänzt
werden kann. Odoo bleibt dabei die führende Datenquelle; die mobile Anwendung
unterstützt Mitarbeitende mit klaren, nachvollziehbaren Arbeitsschritten.

![Systemlandkarte mit PWA, FastAPI, Odoo, Voice, Quality und lokalen KI-Diensten](<Mobile Picking und Voice Assistant/docs/architecture/ebene-1-systemlandkarte.svg>)

## Was dieses Projekt untersucht

Klassische Odoo-Masken sind vor allem für Verwaltung und Planung ausgelegt.
Dieses Projekt betrachtet dagegen die praktische Arbeit im Lager:

- Sie zeigt den nächsten Arbeitsschritt, Lagerort, Artikel und Menge gut lesbar.
- Sie unterstützt Scanner, Kamera, Touch und Sprache als Eingabewege.
- Sie verhindert parallele Bearbeitung und doppelte Buchungen.
- Sie bündelt passende Aufträge zu einem gemeinsamen Rundgang.
- Sie ermöglicht Qualitätsmeldungen mit Beschreibung und Fotos.
- Sie verarbeitet Sprache und Bilder lokal.

Das System ersetzt Odoo nicht. Es ist eine kontrollierte mobile Arbeitsschicht
vor Odoo.

## Der Kern in 30 Sekunden

```text
Mitarbeiter
    ↓
Mobile PWA
    ↓ HTTPS
Caddy
    ↓ /api/*
FastAPI
    ↓ kontrollierte Odoo-Aufrufe
Odoo 19
```

Odoo bleibt das **System of Record**. Die PWA spricht weder direkt mit Odoo
noch mit PostgreSQL oder n8n. FastAPI ist der einzige fachliche Ein- und
Ausgangspunkt der mobilen Anwendung.

| Bereich | Aufgabe |
| --- | --- |
| PWA | mobile Bedienung, Scanner, Kamera, Voice und sichtbarer Workflow |
| FastAPI | Sitzung, Rollen, Claims, Validierung, Idempotenz und Orchestrierung |
| Odoo 19 | Aufträge, Bewegungen, Bestand, Benutzer, Quality und Outbox |
| n8n | asynchrone Quality-Verarbeitung außerhalb des Picking-Hot-Paths |
| Whisper | lokale deutsche Sprache-zu-Text-Erkennung |
| Piper | lokale deutsche Sprachausgabe |
| Ollama | lokale Text- und Bildmodelle |
| Embed-Service | DINOv2- und Farbabgleich gegen den Artikelkatalog |
| Caddy | einzige veröffentlichte HTTPS-Kante |
| PostgreSQL | getrennte dauerhafte Datenbanken für Odoo und n8n |

## So sieht die PWA aus

Die Oberfläche ist auf ein schmales Smartphone-Display ausgelegt. Große
Bedienflächen, klare Zustände und wenige Entscheidungen pro Bildschirm sind
wichtiger als eine möglichst informationsreiche ERP-Ansicht.

### Anmeldung und Benutzerkontext

Die Anmeldung erzeugt eine serverseitig kontrollierte Sitzung. Danach sieht
jeder Mitarbeiter nur die für ihn zulässigen Aufträge und Claims. Die
Benutzeridentität kommt nicht aus frei gesetzten Browser-Headern.

<p align="center">
  <img src="Mobile Picking und Voice Assistant/docs/screenshots/aktuell/pwa-anmeldung-mobil-2026-08-27.png" width="245" alt="PWA-Anmeldung mit Lager 1 und Lager 2 auf dem Smartphone">
</p>

Die aktuelle Anmeldung zeigt die beiden Lagerorte Lager 1 und Lager 2.

### Cluster-Vorschläge und Auswahl

FastAPI liest geeignete Odoo-Aufträge und erzeugt daraus nachvollziehbare
Cluster-Vorschläge. Der Mitarbeiter kann einen Vorschlag übernehmen oder
mehrere passende Vorschläge auswählen.

<p align="center">
  <img src="Mobile Picking und Voice Assistant/docs/screenshots/cluster-verbessert/01-vorschlaege.png" width="245" alt="Automatisch berechnete Cluster-Vorschläge">
  &nbsp;
  <img src="Mobile Picking und Voice Assistant/docs/screenshots/cluster-verbessert/02-mehrere-ausgewaehlt.png" width="245" alt="Mehrere ausgewählte Cluster-Vorschläge">
  &nbsp;
</p>

Der Rundgang fasst gleiche Lagerstopps zusammen. Die Aufträge werden dabei
nicht vermischt: jede Menge bleibt einem konkreten Odoo-Auftrag und einem
konkreten Zielkarton zugeordnet.

### Wirkung in Odoo

Die PWA zeigt eine vereinfachte Arbeitsansicht, schreibt aber keine
Parallelbestände. Nach einer bestätigten Bewegung ist Odoo weiterhin die
fachliche Wahrheit.

<p align="center">
  <img src="Mobile Picking und Voice Assistant/docs/screenshots/cluster-verbessert/03-odoo-bestandsansicht.png" width="760" alt="Odoo-19-Bestandsansicht nach dem Picking">
</p>

## Die komplette Mitarbeiterreise

### 1. Anmelden

Der Mitarbeiter meldet sich in der PWA an. FastAPI prüft den Benutzer gegen
Odoo, erstellt die Sitzung und bindet sie an den zulässigen Ursprung. Im
Produktionsprofil werden unsichere Browser-Origins und der alte
Header-Grace-Modus abgewiesen.

### 2. Auftrag oder Cluster wählen

Für einen normalen Auftrag lädt die PWA die offenen, zulässigen Pickings. Für
Cluster-Picking berechnet FastAPI Vorschläge aus mehreren Aufträgen. Ein
Vorschlag berücksichtigt unter anderem:

- Odoo-Instanz und Lager,
- Auslieferungstag beziehungsweise Zeitfenster,
- Lagerzonen und Laufweg,
- Wagen- oder Clusterkapazität,
- gemeinsam vorkommende Produkte,
- Auftrags- und Mitarbeiter-Scope.

### 3. Auftrag beanspruchen

Beim Öffnen reserviert FastAPI den Auftrag zeitlich begrenzt für Mitarbeiter
und Gerät. Ein Heartbeat verlängert den Claim. Verlässt der Mitarbeiter den
Auftrag, wird er freigegeben; fällt das Gerät aus, läuft der Claim kontrolliert
ab.

Ein zweites Gerät erhält bei einer Kollision keinen scheinbaren Erfolg,
sondern einen sichtbaren Konflikt. So entstehen nicht zwei parallele
Bearbeitungen desselben Pickings.

### 4. Zum Lagerort gehen

Die PWA zeigt den nächsten Lagerort, den erwarteten Artikel, die offene Menge,
den Fortschritt und beim Cluster-Picking zusätzlich den Zielkarton. Die Route
ist für die Arbeit am Regal optimiert, nicht für die Darstellung der
Odoo-Verwaltungsstruktur.

### 5. Artikel und Karton bestätigen

Der robuste Primärpfad ist ein HID-Barcodescanner, der sich wie eine Tastatur
verhält. Zusätzlich sind Kamera, Touch und Voice möglich.

Beim Cluster-Picking prüft das Backend den tatsächlich übermittelten
Karton-Token gegen das erwartete Odoo-Zielpaket. Ein falscher Karton blockiert
die Buchung. Die Prüfung findet nicht nur visuell im Browser statt, sondern
erneut serverseitig vor dem Odoo-Write.

### 6. Kontrolliert nach Odoo schreiben

FastAPI validiert Sitzung, Claim, Picking, Position, Artikel, Menge und
gegebenenfalls Karton. Erst danach wird Odoo aktualisiert.

Jede Schreibaktion erhält einen Idempotenzschlüssel. Geht die HTTP-Antwort
verloren, darf der Client dieselbe Aktion wiederholen: statt einer zweiten
Buchung liefert das System die bereits gespeicherte Antwort.

### 7. Auftrag abschließen

Einzelaufträge werden nach vollständiger Bearbeitung abgeschlossen.
Cluster-Aufträge bleiben fachlich getrennt, werden aber über den gemeinsamen
Batch kontrolliert beendet. Die PWA zeigt nur Erfolg, wenn der zugrunde
liegende Vorgang wirklich erfolgreich war.

## Normales Picking

Der normale Ablauf ist der kürzeste und robusteste Pfad:

```text
Auftragsliste
  → Picking öffnen und claimen
  → nächste Position anzeigen
  → Artikel bestätigen
  → Menge nach Odoo schreiben
  → nächste Position
  → Picking abschließen
```

Scanner und Touch funktionieren unabhängig von Voice, n8n und den
KI-Modellen. Diese Trennung ist absichtlich: Ein ausgefallenes Modell darf
keinen normalen Lagerauftrag blockieren.

## Cluster-Picking

Cluster-Picking reduziert Laufwege, indem mehrere Aufträge auf einem
gemeinsamen Rundgang bearbeitet werden.

```text
offene Odoo-Pickings
  → geeignete Kandidaten filtern
  → Cluster-Vorschläge berechnen
  → Aufträge und Zielkartons zuordnen
  → gleiche Lagerstopps bündeln
  → jede Teilmenge einzeln dem richtigen Auftrag bestätigen
  → Batch und Pickings kontrolliert abschließen
```

Die entscheidende Regel lautet: **gemeinsamer Laufweg, getrennte fachliche
Buchung**. Vier Stück am selben Regal werden nicht anonym als Viererblock
verbucht. Das System weiß, welche Teilmenge in welchen Karton und zu welchem
Auftrag gehört.

Die verwendeten Odoo-Modelle bleiben die nativen Lagerobjekte, darunter
`stock.picking.batch`, `stock.picking`, Move-Lines und
`stock.quant.package`. Eigene Logik ergänzt Claims, sichere API-Verträge und
die mobile Führung, statt eine zweite Lagerverwaltung nachzubauen.

![Cluster-Picking von Vorschlag bis Odoo-Buchung](<Mobile Picking und Voice Assistant/docs/architecture/ebene-3-cluster-picking.svg>)

## Voice Assistant

Voice ist ein zusätzlicher Bedienweg, kein Zwang und kein Ersatz für Scanner
und Touch.

```text
Mikrofon
  → PWA erkennt Sprache und Stille
  → FastAPI sendet Audio an Whisper
  → deterministische Intent-Regeln
  → sichere Aktion
  └─ nur bei Unsicherheit: Ollama-Klassifikation

Antwort
  → Piper erzeugt lokale Sprache
  └─ bei Piper-Ausfall: Browser SpeechSynthesis
```

### Warum Voice nicht über n8n läuft

Kommandos wie „nächster Artikel“, „noch zwei Stück“ oder „Problem melden“
gehören zum interaktiven Hot-Path. Ein zusätzlicher Workflow-Hop würde
Latenz und Ausfallmöglichkeiten erhöhen. Deshalb bleibt der normale
Voice-Loop direkt zwischen PWA, FastAPI, Whisper, Intent-Logik und Piper.

### Aufnahme und Rückmeldung

Die PWA arbeitet mit klaren Grenzen:

- Sprachschwelle: RMS größer als 18,
- Stille nach Sprache: ungefähr 550 Millisekunden,
- Neustart bei ausbleibender Sprache: 6 Sekunden,
- minimale Sprechdauer: 100 Millisekunden,
- maximale Aufnahme: 10 Sekunden.

Während die Sprachausgabe läuft, bleibt das Mikrofon stumm. Dadurch hört der
Assistent nicht seine eigene Antwort und erzeugt keine Feedback-Schleife.
Riskante oder unsichere Schreibaktionen benötigen eine ausdrückliche
Bestätigung.

![Voice-Pfad mit Whisper, Intent-Regeln, Ollama-Fallback und Piper](<Mobile Picking und Voice Assistant/docs/architecture/ebene-4-voice.svg>)

## Qualitätsmeldungen, Fotos und lokale KI

Ein Mitarbeiter kann direkt aus dem Picking eine Qualitätsmeldung erstellen.
Sie enthält Beschreibung, fachlichen Kontext und optional Fotos.

### Dauerhaft speichern, bevor KI beginnt

FastAPI berechnet Fingerprints und übergibt die Meldung an Odoo. Odoo speichert
in einer gemeinsamen Transaktion:

- Quality Alert,
- Fotoanhänge,
- Integrationsjob,
- Outbox-Ereignis.

Erst wenn diese Daten dauerhaft gespeichert sind, beginnt die asynchrone
Verarbeitung.

```text
PWA
  → FastAPI
  → Odoo: Alert + Fotos + Job + Outbox
  → signierter Dispatcher
  → n8n Quality Assessment v2
  → signierte FastAPI-Bewertungsroute
  → lokale Text-, Embedding- und Bildanalyse
  → signierter Callback
  → Odoo: Ergebnis oder review_required
```

### Aufgabenteilung der Modelle

| Stufe | Technik | Aufgabe |
| --- | --- | --- |
| Textbewertung | `qwen2.5:7b` | Meldung in `sellable`, `rework`, `quarantine` oder `scrap` einordnen |
| Artikelabgleich | DINOv2 + Farbhistogramm | Foto gegen den bekannten Artikelkatalog rangieren |
| Bildbeschreibung | `gemma4:12b` | Artikelmerkmale beschreiben, wenn der Embedding-Pfad nicht sicher entscheidet |
| Schadensprüfung | `gemma4:12b` | sichtbare Beschädigungen pro Bild untersuchen |
| Zusammenführung | deterministisches Python | Text- und Bildbefund nach festen Regeln abgleichen |

Die Modelle treffen nicht frei die endgültige Betriebsentscheidung. Ein Bild
darf einen Fall verschärfen, aber eine menschliche Schadensmeldung nicht
unbemerkt abschwächen. Ein falscher Artikel, ein Bildwiderspruch oder ein nicht
belegtes `scrap` endet daher bei `review_required`.

Die konkrete Handlungsempfehlung kommt aus einer festen Zuordnungstabelle und
nicht aus einer frei formulierten Modellantwort.

![Quality-Flow mit Odoo-Outbox, n8n und lokaler KI](<Mobile Picking und Voice Assistant/docs/architecture/ebene-5-quality-n8n-ki.svg>)

## Architektur im Detail

### PWA

Die PWA besteht aus HTML, CSS und JavaScript und kann ohne App-Store auf dem
Smartphone installiert werden. Der Service Worker cached die Anwendungshülle
unter `picking-v29`. Fachdaten und Schreibaktionen werden bewusst nicht
offline erfunden oder auf Vorrat synchronisiert.

### Caddy

Caddy terminiert HTTPS und ist im Basis-Stack die einzige ins LAN
veröffentlichte Komponente. Normale Seitenpfade gehen an die PWA, `/api/*`
geht an FastAPI. Odoo, PostgreSQL, n8n und die Modelldienste bleiben intern.

### FastAPI

FastAPI ist API, Sicherheitsgrenze und Command Gatekeeper. Hier liegen:

- Login und serverseitige Sitzung,
- Rollen- und Instanzkontext,
- Origin- und CSRF-Prüfung,
- Claims und Heartbeats,
- Idempotenz,
- normaler und gebündelter Picking-Ablauf,
- Voice-Intent-Verarbeitung,
- Quality-Orchestrierung,
- signierte Service-zu-Service-Routen.

FastAPI besitzt keine eigene fachliche Geschäftsdatenbank.

### Odoo 19

Odoo führt die fachlichen Objekte. Eigene Odoo-Addons ergänzen Funktionen, die
nahe an derselben Transaktion liegen müssen:

- Picking-Claims,
- Idempotenz-Receipts,
- Quality Alerts,
- Integrationsjobs,
- Outbox-Ereignisse,
- Nonces und Callback-Receipts.

### n8n

n8n verbindet asynchrone Quality-Schritte. Es ist absichtlich weder
allgemeines Backend noch Bestandteil jedes Scanner- oder Voice-Kommandos.
Workflow-Dateien und Registry definieren, welcher Workflow produktiv importiert
und aktiviert werden muss.

### Lokale Modelldienste

Whisper, Piper, Ollama und der Embedding-Dienst laufen im lokalen
Docker-Netz. Betriebs-, Sprach- und Bilddaten müssen für die normale
Verarbeitung den Host nicht verlassen.

## Docker-Dienste und Netze

Der Basis-Stack enthält:

| Dienst | Zweck | Netz |
| --- | --- | --- |
| `pwa` | statische mobile Anwendung | Edge |
| `caddy` | HTTPS und Reverse Proxy | Edge |
| `backend` | FastAPI und kontrollierte Abläufe | Edge, Core, Automation |
| `db` | PostgreSQL für Odoo und n8n | Core |
| `odoo` | Odoo 19 Community mit Custom Addons | Core |
| `n8n` | asynchrone Workflows | Automation |
| `whisper` | lokale Spracherkennung | Automation |
| `piper` | lokale Sprachausgabe | Automation |
| `ollama` | lokale Text- und Bildmodelle | Automation |
| `embed` | DINOv2- und Farbabgleich | Automation |

Die drei Netze `edge-net`, `core-net` und `automation-net` begrenzen,
welche Dienste miteinander sprechen können. Das Development-Overlay
veröffentlicht ausgewählte Diagnoseports ausschließlich auf `127.0.0.1`.

## Sicherheit und Datenhoheit

Die Sicherheitsregeln greifen an mehreren Grenzen:

- Nur Caddy veröffentlicht im Basis-Stack Ports ins LAN.
- Die PWA spricht fachlich ausschließlich mit FastAPI.
- Browserzugriffe verwenden Sitzung, Origin-Prüfung, CSRF und Odoo-Rollen.
- Produktionskonfiguration verlangt HTTPS-Origins und verbietet den
  unsicheren Header-Grace-Modus.
- Service-zu-Service-Aufrufe im Quality-v2-Pfad verwenden HMAC-SHA256.
- Signiert werden Methode, Ziel, Generation, Zeitstempel, Nonce und Body-Hash.
- Nonces begrenzen Replay-Angriffe.
- Odoo hält Jobs, Receipts und Outbox-Zustand dauerhaft.
- Event-ID und Payload-Fingerprint deduplizieren Wiederholungen.
- Secrets liegen ausschließlich in der lokalen, ignorierten `.env` oder in
  restriktiv gemounteten Secret-Dateien.

![Rollen, Rechte und Datenhoheit](<Mobile Picking und Voice Assistant/docs/architecture/ebene-11-rollen-rechte-datenhoheit.svg>)

## Fehler und Wiederanlauf

Das System bevorzugt sichtbare Unsicherheit vor falschem Erfolg:

| Situation | Verhalten |
| --- | --- |
| Browsernetz fehlt | App-Shell kann öffnen; keine Fachdaten oder Writes werden erfunden |
| Sitzung läuft ab | lokaler Sitzungskontext wird verworfen und Login erscheint |
| Claim gehört anderem Gerät | `409` und sichtbarer Konflikt |
| HTTP-Antwort geht verloren | gleicher Idempotenzschlüssel liefert das gespeicherte Ergebnis |
| Whisper fällt aus | Scanner und Touch bleiben verfügbar |
| Piper fällt aus | Browser-Sprachausgabe übernimmt |
| Ollama fällt aus | deterministische sichere Pfade bleiben nutzbar |
| Embed fällt aus | Artikelabgleich fällt auf Vision-/Textvergleich zurück |
| n8n ist nicht erreichbar | Odoo-Outbox versucht später mit Backoff erneut |
| Ack geht verloren | Event darf erneut zugestellt und wird dedupliziert |
| Modellbefund ist unsicher | `review_required` statt erfundenem Urteil |
| Verarbeitung hängt | Lease läuft ab; Watchdog gibt eine neue Generation frei |

![Fehler, Offline-Verhalten und Wiederanlauf](<Mobile Picking und Voice Assistant/docs/architecture/ebene-8-fehler-offline-wiederanlauf.svg>)

## Lokal starten

### Voraussetzungen

- Docker mit Compose v2,
- `mkcert` für lokale HTTPS-Zertifikate,
- Python 3.10+ für Betriebshelfer,
- feste LAN-IP des Docker-Hosts,
- lokale, nicht getrackte `.env`.

Es wird absichtlich keine Environment-Datei mit Platzhaltern eingecheckt.
Erstelle die Datei lokal mit restriktiven Rechten:

```bash
cd "Mobile Picking und Voice Assistant"
install -m 600 /dev/null .env
```

Mindestens diese Konfigurationsgruppen müssen passend zur Zielumgebung gesetzt
werden:

| Gruppe | Beispiele für Variablennamen |
| --- | --- |
| PostgreSQL | `POSTGRES_USER`, `POSTGRES_PASSWORD` |
| Odoo | `ODOO_DB`, `ODOO_USER`, `ODOO_API_KEY` |
| Netzwerk | `LAN_HOST`, `PWA_ORIGINS`, `RUNTIME_PROFILE` |
| n8n | `N8N_ENCRYPTION_KEY`, Webhook-Pfade und Callback-Konfiguration |
| Quality-Signaturen | aktive Key-IDs und getrennte Base64-HMAC-Secrets |
| lokale Modelle | `LLM_PROVIDER`, `LLM_MODEL`, `VISION_MODEL`, `EMBED_MODE` |

Welche Variablen zwingend sind, definiert die aktuelle
`docker-compose.yml` fail-closed. Secretwerte dürfen nicht in Issues,
Screenshots, Dokumentation oder Git landen.

Danach:

```bash
bash infrastructure/scripts/setup-certs.sh <LAN-IP>
docker compose config --quiet
docker compose build
docker compose up -d
```

Für lokale Diagnoseports:

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d
```

Für einen einmaligen Modelldownload erhalten nur Whisper und Ollama über das
Egress-Overlay einen zeitlich begrenzten Außenweg.

## Repository-Struktur

```text
.
├── README.md
└── Mobile Picking und Voice Assistant/
    ├── backend/app/       FastAPI-Router, Services und Sicherheitslogik
    ├── pwa/               mobile Oberfläche, Scanner, Kamera und Voice
    ├── odoo/addons/       Picking-, Integrations- und Quality-Addons
    ├── n8n/               Workflow-Registry, Workflows und Custom Nodes
    ├── embed/             lokaler DINOv2-/Farb-Abgleich
    ├── whisper/           lokaler Speech-to-Text-Dienst
    ├── piper/             lokaler Text-to-Speech-Dienst
    ├── infrastructure/    Caddy, Zertifikate und Betriebshelfer
    ├── docs/              Architektur, Entscheidungen und Runbooks
    ├── docker-compose.yml
    └── Makefile
```


## Ehrlicher aktueller Stand

- Die Compose-Grunddatei veröffentlicht nur Caddy, startet FastAPI derzeit
  aber noch mit Uvicorn `--reload`.
- Die Workflow-Registry verlangt die Produktionsaktivierung von „Quality
  Assessment v2“, während die eingecheckte Workflow-Datei `active: false`
  trägt. Import und Aktivierung sind ein kontrollierter Deployment-Schritt.
- Quality-Bewertungen laufen auf dem aktuellen CPU-Host absichtlich seriell.
- Die PWA cached ihre Anwendungshülle, aber keine API-Daten oder
  Schreibaktionen.
- Test-Suiten und Belegkorpus sind erhalten, aber nicht Teil des öffentlichen
  Runtime-Branches.

Das Ergebnis ist kein isolierter UI-Demonstrator. Es ist ein kompakter
End-to-End-Laufzeitstand vom Smartphone über API und ERP bis zu lokaler
Sprach-, Workflow- und Bildverarbeitung.

Stand: 26. August 2026.
