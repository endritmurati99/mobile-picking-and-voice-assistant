---
tags:
  - future
  - backlog
---

# Future Functions & Verbesserungen

> Ideen und bekannte Schwächen die nach dem MVP angegangen werden.
> Werden hier gesammelt damit nichts vergessen geht.

---

## Leitlinie

> Auf dem aktuellen PoC aufbauen, keine Parallelwelt erfinden.
> Neue Features müssen auf den bestehenden Invarianten aufsetzen:
> Odoo bleibt System of Record, FastAPI bleibt App-API, n8n bleibt Orchestrator und nicht Voice-Hot-Path.

### Einordnung

- **Jetzt realistisch:** kleine bis mittlere Erweiterungen auf Basis der bestehenden PWA-, Visual- und n8n-Struktur
- **Nach MVP-Test:** Features, die zusätzliche Logs, Metriken oder UX-Schleifen brauchen
- **Später / Forschungsvision:** größere Themen wie AR, echte Spatial Intelligence oder autonome Multi-Agent-Logik

---

## Voice Assistant

### Natürliche Sprachkommandos (KI/NLP statt Keyword-Matching)
- **Problem:** Aktuelle Intent Engine matcht nur exakte Keywords ("bestätigen", "weiter", "zurück")
- **Ziel:** Nutzer soll natürlich sprechen können, z.B.:
  - "Hey, ich hab den Auftrag erledigt. Du kannst ihn jetzt weg schicken und mir den nächsten geben."
  - "Das Produkt ist beschädigt, mach mal ein Quality Alert."
- **Ansatz:** LLM-Layer zwischen Whisper-Transkript und Intent-Engine (kleines lokales Modell oder Structured Prompting)
- **Constraint:** Muss lokal oder datenschutzkonform laufen (Architektur-Invariante 6)
- **Priorität:** Hoch — wichtigstes Feature nach MVP-Stabilisierung

### Voice-Reaktionszeit optimieren
- **Problem:** Round-Trip ~2-4s (700ms Stille + 1-2s Whisper + Netzwerk)
- **Nutzer-Feedback:** "Es funktioniert, aber es könnte noch schneller sein."
- **Optionen:** Kürzere Stille-Schwelle, Whisper `tiny`, Audio-Streaming, VAD im Browser
- **Stand 2026-03-23:** `SILENCE_AFTER_SPEECH` auf 400ms gesenkt (−300ms). Whisper `tiny` und Audio-Streaming noch offen.
- **Priorität:** Mittel (teilweise erledigt)

### ~~M-Taste: Voice-Modus global / Navigation-Problem~~ ✅ Erledigt 2026-03-23
- **Lösung:** `stopVoiceMode()` in `voice.js` exportiert; `updateToolbar()` in `app.js` stoppt Voice automatisch wenn `view !== 'detail'`.

### Barcode-Nummern nicht vorlesen
- **Problem:** TTS liest 9-stellige Barcode-Nummern vor (z.B. "6-1-0-1-1-2-1") — unbrauchbar im Lager
- **Stand:** speak()-Aufrufe in app.js nutzen bereits `product_name` und `location_src` — keine Barcodes direkt. In der Praxis kein akutes Problem, aber noch nicht explizit gefiltert.
- **Lösung:** Barcodes aus dem TTS-Text herausfiltern, stattdessen nur Produktname + Lagerort vorlesen
- **Priorität:** Niedrig (implizit gelöst)

### Intelligenterer Voice Agent (ElevenLabs / KI-Stimme)
- **Idee:** Browser-TTS (SpeechSynthesis) ersetzen durch ElevenLabs oder ähnliches
- **Vorteil:** Natürlichere Stimme, kontextbewusstes Gespräch, bessere Fehlerkorrektur
- **Constraint:** Muss lokal oder datenschutzkonform laufen (kein Cloud-Zwang laut Architektur)
- **Priorität:** Niedrig (erst nach stabilem MVP)

### ~~KI-Voice-Filter für Picking-Liste~~ ✅ Erledigt 2026-03-23
- **Umgesetzt:** Touch-Filter-Buttons + Voice-Intents `filter_high`, `filter_normal`, `status` in `intent_engine.py` und `app.js`.
- **Proaktive Begrüßung** beim App-Start: Assistent spricht Anzahl offener + dringender Aufträge.

---

## Quality Alerts

### Bessere Struktur & Workflow
- **Problem:** Aktuell minimales Datenmodell — kein klarer Eskalationspfad
- **Idee:** Mehrstufiger Workflow mit Benachrichtigungen, Verantwortlichkeiten, SLA
- **Priorität:** Mittel

---

## PWA / UI Design

### Visual Sight Loop für Einhand-Bedienung
- **Status:** Technische Basis ist vorhanden (`capture-sight.js`, visuelle Artefakte, Snapshot-Tests)
- **Ziel:** Die PWA soll systematisch auf Lager-Usability geprüft werden: große Touch-Ziele, Daumenreichweite, Kontrast, klare Fokusführung, wenig kognitive Last
- **Review-Notiz:** [[Visual Sight Loop v1 - Einhand-Usability-Report]]
- **Jetzt machbar:**
  - Claude wertet die bestehenden Visual-Artefakte gezielt für Einhand-Bedienung aus
  - UI-Heuristiken je Screen dokumentieren: Picking-Liste, Detailansicht, Quality-Alert
  - konkrete Verbesserungsvorschläge priorisieren statt rein subjektivem UI-Bauchgefühl
- **Nächster Umsetzungsschritt:** "UI-Review-Loop" definieren, der aus `.claude/artifacts/ui_state-index.json` pro Screen 3-5 umsetzbare UX-Verbesserungen ableitet
- **Später:** halbautomatische Layout-Vorschläge, adaptive Bedienmodi je Gerätetyp
- **Bewusst noch nicht:** WebXR, AR-Leitlinien im Raum, kamerabasierte Regalüberlagerungen
- **Priorität:** Hoch

#### Konkreter Arbeitsplan: Visual Sight Loop v1

**Ziel der ersten Iteration:**
- aus dem bestehenden Visual-Loop einen reproduzierbaren UX-Review-Prozess machen
- nicht "schön designen", sondern gezielt Lager-Usability verbessern

**Bestehende Basis im Projekt:**
- `e2e/capture-sight.js`
- `.claude/artifacts/ui_state-index.json`
- visuelle Baselines unter `e2e/visual.spec.js`
- `workflow.ps1 verify-visual`
- `workflow.ps1 verify-visual-diff`

**5 sofort prüfbare UI-Heuristiken:**
1. Primäre Aktion pro Screen liegt in der unteren Daumen-Zone und ist ohne Umgreifen erreichbar.
2. Tappbare Hauptziele sind groß genug für Lagerbetrieb mit Stress oder Handschuhen.
3. Pro Screen ist genau eine Hauptaktion visuell dominant.
4. Der aktuelle Status ist ohne Scrollen sichtbar: Auftrag, nächster Lagerort, Fehlerzustand, Sendezustand.
5. Kritische Rückmeldungen erscheinen direkt am Nutzungspunkt und nicht versteckt am Rand.

**Ablauf pro Review-Zyklus:**
1. `workflow.ps1 verify-visual` ausführen
2. zuerst `.claude/artifacts/ui_state-index.json` lesen, dann nur bei Bedarf die zugehörigen Screenshots öffnen
3. die drei Kernscreens `list`, `detail` und `alert` gegen die 5 Heuristiken bewerten
4. maximal 3 UX-Probleme priorisieren
5. nur 1-2 Änderungen pro Runde umsetzen
6. `workflow.ps1 verify-visual-diff` erneut laufen lassen
7. kurze Vorher/Nachher-Notiz in Obsidian festhalten

**Naheliegende erste Prüfpunkte im aktuellen Stand:**
- Ist der wichtigste Button in der Detailansicht wirklich mit einer Hand gut erreichbar?
- Ist der Quality-Alert-Screen im unteren Bereich klar genug gegliedert?
- Ist auf der Picking-Liste sofort sichtbar, welcher Auftrag als nächstes sinnvoll ist?
- Ist der Lade-/Sendezustand im Moment hoher Latenz eindeutig genug?

**Definition of Done für v1:**
- pro Kernscreen liegt eine kurze UX-Bewertung vor
- pro Kernscreen gibt es 1 priorisierte Verbesserung
- der Review-Prozess ist so klar, dass wir ihn später wiederholen können

**Wenn wir das als Nächstes wirklich bauen:**
- Claude soll aus den visuellen Artefakten automatisch einen kleinen Einhand-Usability-Report erzeugen
- Format: `Problem`, `Warum relevant im Lager`, `konkrete UI-Änderung`

### Visuales Qualitätsfeedback direkt in der PWA
- **Idee:** Bestehende Kamera- und Thumbnail-Logik nutzen, um Quality Alerts visuell klarer und schneller zu machen
- **Jetzt machbar:**
  - bessere Foto-Hinweise vor dem Upload
  - markierte Pflichtangaben bei schlechter Bildqualität oder leerer Beschreibung
  - kompakter Review-Screen vor dem Absenden
- **Später:** einfache Bilderkennung für unscharfe Fotos oder beschädigte Kartons
- **Priorität:** Mittel

### Route Intelligence weiter ausbauen
- **Status:** MVP seit 2026-03-22 umgesetzt
- **Aktuell:** Offene Pick-Positionen werden im Backend deterministisch nach Lagerzone und Slot sortiert; die PWA zeigt dazu einen kompakten Routenhinweis
- **Nächster Schritt:** Echte Wegezeiten statt Heuristik, z. B. mit Regal-Matrix, Laufweg-Schaetzung und spaeter optional Mitarbeiter-Standort
- **Priorität:** Mittel

### Scanner-UI überarbeiten
- **Problem:** Aktuelles Design ist funktional aber nicht optimal für Lagerumgebung (Handschuhe, Licht)
- **Idee:** Größere Touch-Targets, höherer Kontrast, One-Hand-Bedienung
- **Priorität:** Niedrig (erst nach vollständigem Feature-Set)

---

## Allgemein

### n8n-Orchestrator für proaktive Simulationen
- **Idee:** n8n nicht nur als Event-Empfänger, sondern als leichtgewichtige Simulations- und Reconciliation-Schicht für operative Entscheidungen nutzen
- **Warum das gut passt:** Webhooks, Schedule Trigger und Workflow-Vertragsprüfung sind bereits vorhanden
- **Jetzt machbar:**
  - Pick-Zeiten und Quality-Events in n8n protokollieren
  - einfache "Was kommt als Nächstes?"-Simulation auf Basis von `route-plan`, Lagerort und bisherigen Laufzeiten
  - Polling-Workflow als Safety Net und Datenbasis für spätere Simulationen
  - tägliche oder stündliche Heatmaps: häufige Lagerorte, langsame Picks, Peak-Zeiten
- **Nach MVP-Test:**
  - heuristische Vorhersage der Restdauer eines Pickings
  - Priorisierung offener Pickings nach Aufwand, Stau oder Qualitätsrisiko
  - einfache Vorschläge für die nächste sinnvolle Aufgabe pro Picker
- **Später / Forschungsvision:**
  - echter Standortbezug der Mitarbeiter
  - Multi-Picker-Verteilung ("Swarm Orchestration")
  - "Ghost Picking" oder proaktive Mitnahmeempfehlungen
  - externe Datenquellen wie Lieferverzug, Verkehrs- oder Wetterdaten
- **Constraint:** Keine Entscheidung ohne nachvollziehbare Datenbasis; zuerst messen, dann vorhersagen
- **Priorität:** Hoch

#### Konkreter Arbeitsplan: n8n-Simulationsschicht v1

**Ziel der ersten Iteration:**
- noch keine "KI", sondern eine nachvollziehbare operative Vorschau
- n8n soll aus vorhandenen Daten grob abschätzen, welche Pickings lange dauern und wo Engpässe entstehen

**Bestehende Basis im Projekt:**
- Webhook `pick-confirmed`
- Webhook `quality-alert-created`
- `GET /api/pickings`
- `GET /api/pickings/{id}/route-plan`
- bestehende Routenheuristik im Backend
- geplanter Polling-/Reconciliation-Pfad in Phase 5/6

**Was v1 realistisch leisten kann:**
- offene Pickings periodisch abrufen
- pro Picking Restaufwand aus `remaining_stops`, `estimated_travel_steps` und offenen Positionen schätzen
- langsame oder risikoreiche Pickings markieren
- einfache Prioritätsliste oder täglichen Simulationsreport erzeugen

**Was v1 bewusst noch nicht kann:**
- exakten Mitarbeiter-Standort berücksichtigen
- echte Multi-Picker-Verteilung berechnen
- zukünftige Bestellungen probabilistisch vorhersagen
- externe Datenquellen wie Wetter oder Verkehr sinnvoll integrieren

**Ablauf für einen schlanken Workflow:**
1. `Schedule Trigger` in n8n, z. B. alle 15 Minuten
2. offene Pickings über das Backend abrufen
3. für jedes Picking den `route-plan` anfragen
4. einfache Restdauer heuristisch berechnen, z. B. `Basiszeit pro Stopp + Laufwegfaktor`
5. Liste nach geschätzter Restdauer oder Risiko sortieren
6. Ergebnis als Log, Report oder Odoo-Notiz ablegen
7. später mit realen Abschlusszeiten aus `pick-confirmed` vergleichen

**Einfache Heuristiken für den Start:**
- viele Reststopps = höherer Aufwand
- hohe geschätzte Laufwege = ineffizienter Auftrag
- offener Quality Alert am Picking = erhöhtes Risiko
- lange offene Dauer = Kandidat für Priorisierung

**Messgrößen für v1:**
- Anzahl offener Pickings pro Lauf
- geschätzte Restdauer je Picking
- Differenz zwischen Schätzung und realem Abschluss
- Anzahl Pickings mit Quality-Risiko

**Definition of Done für v1:**
- ein n8n-Workflow erzeugt periodisch eine nachvollziehbare Prioritäts- oder Prognoseliste
- die Schätzformel ist dokumentiert und nicht "magisch"
- die Ergebnisse lassen sich mit echten Ereignissen aus dem PoC vergleichen

**Wenn wir das als Nächstes wirklich bauen:**
- zuerst nur einen read-only Report erzeugen
- keine automatische Umplanung
- erst nach einigen Messläufen entscheiden, ob sich eine echte Priorisierungslogik lohnt

### Hyper-Personalisierte Arbeitsoberfläche
- **Idee:** Die PWA reagiert auf Erfahrungsniveau und Nutzungsmuster des Mitarbeiters
- **Jetzt machbar:**
  - einfacher Modus "Anfänger" vs. "Profi"
  - mehr oder weniger sprachliche Führung
  - variierende Detailtiefe in der Picking-Ansicht
- **Später:** automatische Anpassung anhand echter Nutzungsdaten
- **Priorität:** Mittel

### MQTT-Barcode-Scanner Integration
- **Hintergrund:** `MQTT_Barcode` + `mqtt_listener` + `logilab` in masterfischer installiert
- **Idee:** Physische Scanner im Lager über MQTT anbinden
- **Offen:** Quellcode beim Professor anfragen (E-Mail Todo)
- **Priorität:** Optional

---

## Große Vision, bewusst geerdet

Die langfristige Richtung kann man als proaktives Lager-Assistenzsystem beschreiben:
- Das System beobachtet Ereignisse nicht nur, sondern lernt aus ihnen
- Die PWA führt nicht nur aus, sondern unterstützt Entscheidungen
- n8n koordiniert nicht nur Webhooks, sondern hilft bei Recovery, Simulation und Priorisierung

Nicht für den aktuellen Stand eingeplant:
- echte AR-/WebXR-Regalprojektionen
- Stimm-Biometrie oder Emotionserkennung
- selbstverändernde Claude-Regeln oder autonome Code-Evolution

Diese Ideen bleiben interessant, sind für den jetzigen Bachelor-PoC aber bewusst nach hinten priorisiert.

---

### Audio-Feedback (Beep + Vibration) ✅ Erledigt 2026-03-23
- **Umgesetzt:** `pwa/js/feedback.js` — Web Audio API, kein externes Asset.
  - Scan-Erfolg → heller Doppel-Piep + kurze Vibration
  - Scan-Fehler → tiefer Brummton + lange Vibration
  - `feedbackAlert()` bereit für Eilauftrag-Alarm via n8n-Webhook (noch nicht verdrahtet)

### Bestandsabfrage per Sprache ✅ Erledigt 2026-03-23
- **Umgesetzt:** `GET /api/pickings/{id}/stock` — fragt `stock.quant` in Odoo ab.
- **Intent:** `stock_query` ("noch da", "lagerbestand") → spricht verfügbare Menge an.

---

*Zuletzt aktualisiert: 2026-03-23*
