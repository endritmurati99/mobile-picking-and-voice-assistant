# Phase 1: Transaktionshaertung

Dieses Dokument beschreibt genauer, was technisch in Phase 1 umgesetzt wurde.

## Ziel

Der bestehende Picking-Flow sollte nicht umgebaut, sondern gegen reale Stoerungen gehaertet werden:

- kein Doppelbuchen bei Retry oder Doppelklick
- kein paralleles Bearbeiten desselben Pickings ohne sichtbaren Konflikt
- echte Picker-Zuordnung statt technischer Default-Namen

## Technische Umsetzung

### Soft Claiming

- Claim wird beim Oeffnen eines Pickings gesetzt.
- Heartbeat verlaengert den Claim waehrend der Bearbeitung.
- Release erfolgt beim Abschluss oder beim Verlassen der Detailansicht.
- TTL ist standardmaessig `120s`.

### Idempotency

- Idempotency wird in Odoo gespeichert, nicht nur im FastAPI-Prozess.
- Eindeutigkeit basiert auf `endpoint + key`.
- Der Request bekommt zusaetzlich einen Fingerprint des Payloads.

Regeln:

- gleicher Key + gleicher Fingerprint: Replay
- gleicher Key + anderer Fingerprint: `409`
- laufender gleicher Request: `409`

### Picker-Identitaet

- Die PWA verwendet einen ausgewaehlten Odoo-Benutzer.
- Diese Benutzer-ID wird in Write-Headern gesendet.
- Das Geraet erhaelt zusaetzlich eine lokale `device_id`.

## Was sich fachlich nicht geaendert hat

- `confirm-line` bestaetigt weiter die komplette Zielmenge der aktuellen Zeile.
- Es gibt noch keine Partial-Pick-Logik.
- `next` und `skip` sind noch keine fachlich persistierten Skip-Vorgaenge.
- Quality Alerts bleiben additive Erweiterungen und aendern den Picking-Abschluss nicht.

## Warum man davon in der UI nur wenig sieht

Der Nutzen liegt hauptsaechlich in Fehlerfaellen:

- doppelte Requests
- instabiles Netz
- versehentlich doppelt geoeffnete Pickings
- mehrere Geraete im selben Auftrag

Im normalen Happy Path arbeitet die App deshalb fast wie vorher.

## Erfolgskriterien

- bestehender Happy Path bleibt erhalten
- keine Doppelbuchung bei Retry
- Claim-Konflikte werden sichtbar statt verschluckt
- neue Schutzschichten sind durch Backend- und UI-Tests abgesichert
