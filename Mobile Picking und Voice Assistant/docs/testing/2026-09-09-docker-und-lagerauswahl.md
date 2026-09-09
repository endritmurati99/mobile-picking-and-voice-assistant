# Docker-Bereinigung und mobile Lagerauswahl

## Laufender Stack

Es gibt einen aktuellen Backend-Container. Zwei aktuelle Odoo-Container sind
beabsichtigt: `mobilepickingundvoiceassistant-odoo-1` bedient Lager 1 (8069),
`mobilepickingundvoiceassistant-odoo-lager-2-1` Lager 2 (8070). Sie nutzen eigene
Konfigurationen und Odoo-Datenvolumes. PostgreSQL, n8n, Caddy/PWA und die
Sprach-/Embeddingdienste ergänzen diesen Stack.

Beim vorherigen Docker-Desktop-Start liefen nur die automatisch wieder
gestarteten Container. Backend, n8n, Lager 2, Caddy/PWA und Embed waren noch
gestoppt. Ihre Restart-Policy `unless-stopped` startet zuvor bewusst gestoppte
Container nicht automatisch. Das war kein vollständiger Anwendungsstart.
Der Owner hat diese Dienste anschließend gestartet; beim Abschluss waren sie
weiter aktiv, und `https://localhost/api/health/live` lieferte HTTP 200/status ok.
PostgreSQL, beide Odoo, n8n und Embed meldeten healthy.

Ein vollständiges Compose-Recreate wurde nicht ausgeführt: Die getrennten
Betriebs-DB-Kennwörter und der Umstieg gemäß DB-Klonbericht sind noch offen.
Ältere Compose-Labels sind kein Beweis für veraltete Mounts: Die PWA bindet
tatsächlich den aktuellen Checkout ein.

## Entfernte Container

Alle folgenden Container waren gestoppte, nach Image/Labels/Mounts bzw.
Testzweck eindeutig zugeordnete alte App-Versuche:

- `pwr-review-db-20260907`
- `pwr-review-odoo-20260907`
- `pwr-review-odoo-scoped-20260907`
- `embed-test`
- `affectionate_bhaskara` (alter Piper)
- `magical_herschel` (Odoo-19-Trial)
- `bold_murdock` (altes zweites Backend)
- `odoo19-smoke`

Die Entfernung erfolgte mit expliziten Namen, ohne `-v` und ohne Prune.
Alle fünf angehängten Docker-Volumes wurden danach als weiterhin vorhanden
verifiziert. Der Review-DB-Container verwendete bereits verlorenes tmpfs;
der neue gesicherte DB-Klon blieb unberührt. Private Container-Metadaten liegen
geschützt unter `/home/endri/audits/docker-cleanup-20260909-1540/`, nicht in Git.

Nicht zugeordnete historische n8n/Fischer-Projekte und der alte Ollama-Container
bleiben erhalten. Letzterer enthält Modelle und Identitätsdaten im beschreibbaren
Container-Dateisystem; seine Entfernung wäre keine reine Containerbereinigung.

## PWA-Fix

Der native Lagerumschalter war mobil auf 88 Pixel begrenzt. Text, Innenabstände
und der native Pfeil passten nicht hinein; im echten Browser wurde bereits
„Lager 1“ abgeschnitten. Die Breite richtet sich nun nach dem Inhalt, mit
`max-width: 100%`. Die widersprechenden mobilen Breitenlimits wurden entfernt.
Umbruch der Kopfaktionen und 44-Pixel-Bedienflächen bleiben erhalten.

Service-Worker-Cache: `picking-v39`. Der laufende PWA-Container liefert bereits
bytegenau die neuen CSS-/SW-Dateien. Kein Container-Neubau war dafür erforderlich.

## Prüfung

- Neuer Regressionstest schlug vor dem Fix fehl und bestand danach bei
  320, 390 und 412 Pixeln, einschließlich Kontrollflächen im sichtbaren Bereich.
- Abschließender Browserlauf: 21 Tests bestanden, Exit 0; Lagerumschaltung,
  Accessibility, Desktoplayout und unveränderte visuelle Referenzen.
- Fünf Asset-/Service-Worker-Tests bestanden.
- Ein bestehender Screenshot-Test erfasste zunächst den temporären Sprachstatus
  „Spricht“. Der Screenshot-Helfer beendet jetzt ausstehende Sprachausgabe und
  wartet auf idle, damit das Ruhelayout unabhängig vom Audio-System geprüft wird.
- Browser Harness prüfte die echte ausgelieferte PWA; keine Anmeldung oder
  Auftragsbuchung durchgeführt. Unabhängiger Diff-Review ohne wichtigen Befund.
