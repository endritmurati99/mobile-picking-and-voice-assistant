# Technische Evaluation

## Tatsächlich durchgeführte Prüfung

Am 10. September 2026 wurde der Anwendungsstand `3c545b6` als technische
Szenarioevaluation geprüft. Schreibende Tests liefen gegen eine getrennte Kopie
der vorhandenen Odoo-Datenbank in einem internen Docker-Netz. Drei temporäre
Container stellten PostgreSQL, Odoo und FastAPI bereit. Das Testnetz hatte keine
veröffentlichten Ports und keinen externen Netzzugang; Odoo-Cronjobs,
Mailserver und der Backend-Dispatcher waren in der Kopie deaktiviert.

Eine Fixture erzeugte zwei künstliche Artikel, zwei Picker, einen Lagerplatz
und neun Aufträge mit jeweils zwei Positionen. Reguläre Fälle wurden per HTTP
gegen FastAPI ausgeführt und anschließend per Odoo-RPC nachgelesen. Geprüft
wurden ausgewählte Schutzbedingungen, Standard- und Mengenfälle,
Qualitätsmeldungen, Rollback, Idempotenz, konkurrierende Claims, Fehlerpfade,
Outbox-Wiederholung und ein Batch-Ablauf.

Der Lauf belegte die erwarteten Abläufe in diesen künstlichen Szenarien, mit
zwei wesentlichen Einschränkungen: Eine Überentnahme von sechs Stück bei fünf
Stück Soll wurde akzeptiert und bleibt eine offene fachliche Regel. Außerdem
wurde eine ausdrücklich negative Menge damals als gültige Bestätigung
umgedeutet. Dieser zweite Befund wurde anschließend korrigiert.

Die Sprachprüfung bestand aus bestehenden Frontend- und Backend-Regressionen
mit simulierten Browser- und Audio-Schnittstellen sowie einem synthetischen
Piper-zu-Whisper-Versuch. Im dokumentierten Versuch entsprachen 13 von 15
Intent-Zuordnungen der vorab festgelegten Erwartung. Die Mediane der direkt
gemessenen Komponenten betrugen 54,32 ms für Piper, 455,29 ms für Whisper und
0,24 ms für den deterministischen Resolver. Diese Werte sind keine mobile
Ende-zu-Ende-Latenz.

## Vertragsregression vom 12. September 2026

Der aktuelle Anwendungsstand verwendet an beiden Confirm-Line-Requestmodellen
eine Untergrenze von null und lehnt nicht endliche Fließkommawerte ab. Der
zugehörige Regressionstest prüft beide Pydantic-Modelle und beide tatsächlichen
FastAPI-Routen. Er umfasst gültige Null- und Positivwerte sowie negative Werte,
`NaN` und positive beziehungsweise negative Unendlichkeit.

Der bestandene lokale Test belegt die Ablehnung an der HTTP-Vertragsgrenze,
bevor die Handler- und Buchungslogik ausgeführt wird. Die Abhängigkeiten waren
im Test überschrieben; eine Aussage zur Reihenfolge realer Authentifizierung
folgt daraus nicht. Er ist kein neuer
Odoo-Integrationstest und belegt nicht erneut den positiven Buchungspfad. Die
technischen Odoo-Ergebnisse vom 10. September bleiben deshalb als historischer
Lauf abgegrenzt; für den korrigierten Mengenvertrag ist ein neuer isolierter
Odoo-Lauf vorgesehen, sobald Docker verfügbar ist.

Aus dem Anwendungsverzeichnis lässt sich der Vertragscheck so ausführen:

```bash
python infrastructure/scripts/test-confirm-quantity.py
```

Die vollständigen isolierten Szenarioskripte und ihre Sicherheitsgrenzen stehen
unter `infrastructure/evaluation/`. Der Runner zeichnet den geprüften Git-Tree
der Anwendung und alle Test-Exitcodes auf. Jeder fehlgeschlagene Fall führt zu
einem fehlgeschlagenen Gesamtlauf; insbesondere wird der negative Mengentest
nicht mehr als erlaubter Fehler behandelt.

## Aussagegrenzen

Die Evaluation ist eine technische Prüfung ausgewählter Kontroll- und
Integrationsabläufe. Sie ist keine Nutzerstudie, keine Messung einer
Zeitersparnis gegenüber Papier, kein Lasttest und kein Nachweis von
Produktionsreife. Browser, Caddy, TLS, reales Mikrofon, reale Sprecher,
unterschiedliche Mobilgeräte und die vollständige n8n-Callback-Verarbeitung
gehörten nicht durchgehend zum Prüfumfang.

Eine Nutzerstudie mit einem innerhalb der Personen verglichenen Papier- und
PWA-Ablauf kann als zukünftige Evaluation folgen. Teilnehmerzahl,
Counterbalancing, Messgrößen und statistische Verfahren müssen dafür vor der
Datenerhebung festgelegt werden. Für dieses Repository werden keine
Teilnehmerdaten oder Vergleichsergebnisse behauptet.
