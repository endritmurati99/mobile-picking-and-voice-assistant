# Anwendungscode- und Laufzeitprüfung vom 12.09.2026

## Ergebnis

Die vier Voice-/PWA-Commits zwischen dem veröffentlichten Ausgangsstand und
dem Voice-Stand wurden quellenbasiert geprüft. Im geprüften Diff wurde keine
blockierende funktionale Regression gefunden. Der spätere Mengenfix setzt die
Validierung an beiden HTTP-Requestmodellen konsistent um: negative und nicht
endliche Werte werden vor Ausführung der Handler- und Buchungslogik abgewiesen;
Null als bestehender Scan-Standard sowie positive Teilmengen bleiben zulässig.

Der aktuelle geprüfte Anwendungscode hat den Git-Tree
`92c93dec5df39a8198374e21a142eebb23682e0d`. Dieser Tree entspricht auch dem
separat vorbereiteten öffentlichen Code-Commit; private Manuskript-Commits
werden hier nicht referenziert.

## Review des Anwendungsdiffs

Die Fehlergrenzen des Sprachendpunkts unterscheiden nun leere Uploads,
ungültiges Audio und einen nicht verfügbaren Whisper-Dienst. Das Backend gibt
400, 422 beziehungsweise 503 zurück, statt Konvertierungs- oder Dienstfehler als
leere erfolgreiche Erkennung zu behandeln. Der langsame optionale
LLM-Klassifikator wurde aus dem zeitkritischen Befehlsendpunkt entfernt; die
deterministische Erkennung und ihr Segment-Fallback bleiben erhalten.

Die PWA beendet Hands-free-Aufnahmen nach erkannter Sprache und dem getesteten
Stillefenster, verwirft verspätete Ergebnisse nach Moduswechsel und trennt
Push-to-talk-Sitzungen voneinander. Schreibintents verwenden genau einen
sichtbaren Ja/Nein-Dialog. Die Bestätigung ist an Auftrag, Position und Ansicht
gebunden, läuft ab und serialisiert Einzel- und Mehrfachbuchungen. Die Tests
decken konkurrierende Auslöser, Ablauf, Negation und fehlgeschlagene Buchungen
ab. Die spezifischere Navigationsregel hält aktive und gedrückte
Sprachschaltflächen im responsiven Layout sichtbar; der Service-Worker-Cache
wurde mit jeder PWA-Änderungsstufe angehoben.

Die zusätzliche lokale Origin-Freigabe und der Smoke-Test verwenden die
tatsächliche Browser-Origin `https://localhost`. Die bestehende
Produktionsprüfung verlangt weiterhin HTTPS und lehnt Wildcards bei
credentialed CORS ab.

`git diff --check` meldet in mehreren bereits committed Voice-Dateien
Zeilenende-/Whitespace-Hinweise. `git ls-files --eol` bestätigt CRLF
beziehungsweise gemischte Zeilenenden. Das ist ein nicht blockierender
Formatbefund; die Syntax- und Verhaltenstests waren davon nicht betroffen.

## Tatsächlich ausgeführte Prüfungen

| Prüfung | Ergebnis |
|---|---|
| `python infrastructure/scripts/test-confirm-quantity.py` | Exit 0, 3 Testgruppen bestanden |
| `python infrastructure/scripts/test-voice-backend.py` | Exit 0; 422-/503-Negativpfade und deterministische Erkennung bestanden |
| `node --experimental-vm-modules infrastructure/scripts/test-voice-actions.mjs` | Exit 0 |
| `node --experimental-vm-modules infrastructure/scripts/test-voice-frontend.mjs` | Exit 0 |
| `python infrastructure/scripts/verify-workflows.py` | Exit 0; 3 Workflows geprüft, 2 dokumentierte Warnungen zu nicht direkt verwendeten Webhook-Pfaden |
| Python-Syntaxprüfung der portablen Evaluationsskripte | Exit 0 |
| Node-Syntaxprüfung von `app.js`, `voice.js`, `voice-helpers.mjs`, `sw.js` | Exit 0 |
| YAML-Parsing von `docker-compose.yml` | Exit 0 |
| Runner-Guards: JSON-Fehlermarker und Anwendungstree | Exit 0 |

Der Backend-Sprachtest erzeugt bei seinen absichtlich ungültigen Audiodaten
ffmpeg-Fehlerausgaben. Der abschließende Exitcode und die Assertions waren
erfolgreich; die Fehlermeldungen sind Bestandteil des getesteten Negativpfads.

## Docker- und Odoo-Status

Eine begrenzte Abfrage von Docker Server-Version und Betriebssystem wurde nach
8 Sekunden beendet. Es lagen keine Servermetadaten vor; die Containerliste
wurde deshalb nicht abgefragt. Die isolierte Odoo-Evaluation wurde am
12.09.2026 nicht erneut ausgeführt.

Der historische technische Lauf vom 10.09.2026 gehört zum Anwendungstree
`2216bef9edc6a46be9525e4b99201d98e09319f9`. Er verwendete eine isolierte
Datenbankkopie und künstliche Fixtures. Dieser Lauf fand den Fehler bei
negativen Mengen. Der aktuelle lokale Vertragscheck belegt dessen Korrektur an
beiden FastAPI-Routen, ersetzt aber keinen erneuten Odoo-Integrationslauf.

## Portable Evaluation und korrigierte Erfolgssemantik

Die vorhandenen Evaluationsskripte wurden nach
`infrastructure/evaluation/` der Anwendung übernommen. Der Runner leitet seinen
Standard-Anwendungspfad aus dem eigenen Speicherort ab, unterstützt Windows,
WSL und native Linux-Bind-Mounts, erlaubt explizite Quellcontainernamen und
zeichnet den Git-Tree der Anwendung auf. Er verweigert abweichende gemountete
Laufzeitquellen.

Im historischen Runner konnte `test_negative_quantity.py` den JSON-Status
`fail` ausgeben und trotzdem mit Exitcode 0 enden; zusätzlich war genau dieser
Test als erlaubter Prozessfehler markiert. Dadurch konnte der Gesamtlauf
`completed` melden, obwohl die fachliche Erwartung nicht erfüllt war. Die
portable Fassung behebt beide Ebenen: Der Test endet bei einem negativen
Ergebnis mit Fehler, und der Runner wertet zusätzlich sanitierte JSON-
Fehlermarker als Suitefehler. Ein erfolgreicher Gesamtlauf schreibt nun
`status: passed`; jeder fehlgeschlagene Fall schreibt `status: failed`.

## Datenschutz- und Veröffentlichungsprüfung

Veröffentlichungskandidaten sind ausschließlich Quellskripte, README,
`.gitignore` und die aktualisierte Evaluationsdokumentation. Eine gezielte Suche
fand darin keine persönlichen Namen, E-Mail-Adressen oder benutzerspezifischen
Windows-/WSL-Pfade. Es sind keine realen Passwörter, Tokens, Cookies,
Datenbankdumps oder Ergebnisprotokolle enthalten. Die Fixture erzeugt
Zugangsdaten zur Laufzeit; sie werden nur in eine private Datei innerhalb der
temporären Testcontainer übertragen. Der konstante Wert
`evaluation-test-only` ist ein lokaler Mock-Schlüssel und kein Projektzugang.

Der Runner kopiert zur Laufzeit eine vorhandene Quelldatenbank in einen
temporären internen PostgreSQL-Container. Diese Kopie kann reale Daten enthalten
und darf nicht veröffentlicht werden. Ergebnisunterverzeichnisse `private/`,
lokale Laufprotokolle, Dumps und Umgebungsdateien bleiben ausgeschlossen. Die
Anwendungs-`.gitignore`-Regeln geben nur die versionierten Skripte unter
`infrastructure/evaluation/` frei; Cache-, private und Ergebnisdateien bleiben
ignoriert.

Die Quellcontainer werden ausschließlich mit `docker inspect`, `pg_dump` und
Readiness-Probes angesprochen. Datenbankanlage, Job-/Mail-Deaktivierung,
Fixtures, API-Szenarien und Zustandsabfragen mit Testschreibvorgängen zielen nur
auf `bachelor-eval-db`, `bachelor-eval-odoo` und `bachelor-eval-backend` im
internen Netz. Der Runner enthält keinen schreibenden Befehl gegen die
Quellcontainer. `--replace` ist auf diese drei temporären Namen und das
Testnetz begrenzt.

## Verbleibende Grenze

Für eine vollständige Bestätigung des aktuellen Mengenfixes fehlt ausschließlich
der erneute isolierte Odoo-Lauf bei erreichbarer Docker Engine. Außerdem sind
die Voice-Frontend-Checks Node-basierte Harnesses; reales Mikrofon, Browser,
Mobilgerät, Caddy/TLS und reale Sprecher sind damit nicht abgedeckt.

## Korrekturen aus der unabhängigen Abschlussprüfung

Die Abschlussprüfung fand zusätzlich vier Fehler im Evaluationswerkzeug, die vor Veröffentlichung behoben wurden:

- Start mit den inspizierten unveränderlichen Image-IDs statt beweglichen Tags; Protokoll und gestartete Images stimmen damit überein.
- Quellcontainer werden vor jeder Bereinigung inspiziert und anhand ihres kanonischen Namens gegen die temporären Ziele geprüft. Dies schützt auch bei Eingabe einer Container-ID.
- Eingerückte JSON-Arrays und JSONL werden auf fehlgeschlagene oder blockierte Fälle geprüft. Das Follow-up-Skript gibt einzelne JSONL-Ergebnisse aus und endet für solche Fälle mit Fehler.
- Nichtleere Ergebnisverzeichnisse werden abgewiesen, damit kein neuer Fehlerlauf mit älteren Erfolgsdateien vermischt wird.

Das neue Offline-Regressionstestskript `infrastructure/evaluation/test_runner_guards.py` führte vor den Korrekturen zu sieben Fehlern in vier Testgruppen; danach bestanden alle vier. Die unabhängige Gegenprüfung wiederholte diese Tests erfolgreich. Docker wird hierbei vollständig ersetzt; dies bleibt ein Test des Runners und kein Odoo-Integrationslauf. Unvorhergesehene Exceptions geben nur den Fehlertyp statt möglicherweise sensitiver Fehlermeldungen aus.
