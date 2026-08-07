# Handoff — Architekturvisualisierungen 2026-08-07

## Aktuelles Ziel

Alle sechs Visualisierungen unter `docs/architecture/` sollen nacheinander
gegen den aktuellen Repository-Stand geprüft, bei Bedarf präzisiert und mit
einer Scorecard bewertet werden. Der Nutzer hat festgelegt: zuerst Ebene 1
vollständig abschließen, danach gemeinsam weitergehen.

## Stand von Ebene 1

Die aktuelle SVG wurde gerendert und zusammen mit Markdown und Excalidraw gegen
`docker-compose.yml`, `infrastructure/caddy/Caddyfile`, FastAPI-Runtime und
die beteiligten Clients geprüft.

Vorläufiges Ergebnis vor Überarbeitung: **84/100**.

Bestätigter Änderungsumfang:

1. Browserzugriff technisch über Caddy klarstellen.
2. Caddy als einzigen öffentlichen Eingang und Blocker interner Routen zeigen.
3. Odoo um Quality Alerts, Outbox und Cluster-Batches ergänzen.
4. Quality-Hinweg und signierten Callback als zwei gerichtete Pfeile zeigen.
5. Die optionale zweite Odoo-Instanz nur als Profilhinweis aufnehmen.
6. Deklarierten Odoo-19-Aufbau vom blockierten Live-Migrationsstand trennen.
7. Das erfundene Normalauftrag-Beispiel durch den geprüften Auftrag
   `WH/INT/00360` „Ente Henri“ ersetzen.

Der Nutzer hat diesen ausgewogenen Ansatz und anschließend die schriftliche
Spezifikation ausdrücklich bestätigt.

## Relevante Commits und Dokumente

- `993a0fc` — Architektur mit echten Odoo-Daten verifiziert.
- `3dd5865` — bestätigtes Ebene-1-Review-Design:
  `docs/superpowers/specs/2026-08-07-ebene-1-systemlandkarte-review-design.md`
- `2ce89d6` — ausführbarer Ebene-1-Plan:
  `docs/superpowers/plans/2026-08-07-ebene-1-systemlandkarte-review.md`

Die drei eigentlichen Ebene-1-Dateien wurden in dieser Sitzung noch nicht
verändert:

- `docs/architecture/ebene-1-systemlandkarte.md`
- `docs/architecture/ebene-1-systemlandkarte.svg`
- `docs/architecture/ebene-1-systemlandkarte.excalidraw`

## Prüfevidenz

- SVG-Render über `google-chrome --headless` war erfolgreich.
- Compose bestätigt neun Standarddienste sowie `edge-net`, `core-net` und
  `automation-net`.
- Nur Caddy veröffentlicht Ports 80 und 443.
- Caddy routet `/api/*` zu FastAPI, Webzugriffe zur PWA und blockiert interne
  Routen.
- FastAPI spricht direkt mit Odoo, n8n, Whisper, Piper und Ollama.
- n8n schreibt nicht direkt nach Odoo.
- Odoo und n8n nutzen getrennte Datenbanken im PostgreSQL-Dienst.
- Graphify-Audit:
  `/home/endri/audits/mobile-picking-full-2026-08-06/graphify-out/graph.json`
- Breite Graphify-Architekturabfragen sind als Dead End markiert, weil sie bei
  `odoo()`-Test-Fixtures starten. Der gezielte Pfad
  `OdooClient -> VerifiedInternalRequest -> OutboxDispatcher` wurde gefunden,
  aber wegen seiner nur inferierten Kanten direkt im Code gegengeprüft.

## Echte Beispieldaten

- Auftrag `WH/INT/00360`, Ursprung `[619287] Ente Henri (BOM 619287)`,
  sechs offene Positionen.
- Erste Route: `L-E1-P2`, Artikel `Brick 2x2 pink`, Barcode `4648234`,
  SML `1015`.
- Quality-Datensatz `QA/0149` zu `WH/INT/00336`, Artikel
  `Plate 2x4 weiß`, disposition `quarantine`, zwei Bildanhänge.

## Bekannter Live-Blocker

Der deklarierte Serverstand ist Odoo 19. Der zuletzt geprüfte Datenbank-/
Modulstand ist noch nicht vollständig migriert; beim Login fehlt insbesondere
`res_users.totp_last_counter`. Deshalb ist kein grüner Login-Claim-Confirm-
End-to-End-Nachweis erlaubt, bis das Schema-Upgrade abgeschlossen ist.

## Nächster Schritt

Den Plan `docs/superpowers/plans/2026-08-07-ebene-1-systemlandkarte-review.md`
ausführen. Noch offen ist nur die Wahl der Ausführung:

1. Inline in derselben Sitzung — empfohlen.
2. Subagent-gesteuert mit getrennten Review-Gates.

Danach JSON, XML, sichtbaren SVG-Render, Aussagegleichheit und
`git diff --check` frisch verifizieren. Erst dann die endgültige Scorecard
für Ebene 1 melden und Ebene 2 beginnen.

## Arbeitsbaum

Branch: `integration/foundation-remediation`

Der Arbeitsbaum enthält zahlreiche bereits vorhandene, nicht zu diesem
Architekturauftrag gehörende Änderungen in Backend, Odoo, PWA, Compose und
Whisper. Sie gehören dem Nutzer und dürfen weder überschrieben noch zusammen
mit den Architekturdateien committed werden. Vor jedem Commit nur exakte
Dateipfade stagen.
