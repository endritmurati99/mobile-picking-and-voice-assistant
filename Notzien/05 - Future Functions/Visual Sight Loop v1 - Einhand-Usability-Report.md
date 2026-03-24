---
title: Visual Sight Loop v1 - Einhand-Usability-Report
tags:
  - future
  - ui
  - review
  - visual-loop
status: draft
---

# Visual Sight Loop v1 - Einhand-Usability-Report

## Ziel

Erster reproduzierbarer UX-Review der drei Kernscreens:
- Picking-Liste
- Picking-Detail
- Quality-Alert-Formular

Der Fokus liegt auf **Einhand-Bedienung im Lager**, nicht auf allgemeiner Design-Kosmetik.

---

## Review-Basis

- Visual-Capture mit `workflow.cmd verify-visual`
- Artefakte unter `.claude/artifacts/ui_state-index.json`
- Mobile-Viewport `390 x 844`
- gemockte Kernzustände aus `e2e/helpers/pwa-api.js`
- UI-Struktur aus `pwa/js/app.js`, `pwa/js/ui.js` und `pwa/css/app.css`

> [!note] Aussagekraft
> Das ist bewusst ein **v1-Expertenreview** auf Basis des reproduzierbaren Mock-Flows.
> Bewertet wird also die Kernstruktur der UI, nicht jede Live-Edge-Case-Situation im Lager.

---

## Bewertungs-Heuristiken

1. Primäre Aktion pro Screen liegt in der unteren Daumen-Zone und ist ohne Umgreifen erreichbar.
2. Tappbare Hauptziele sind groß genug für Lagerbetrieb mit Stress oder Handschuhen.
3. Pro Screen ist genau eine Hauptaktion visuell dominant.
4. Der aktuelle Status ist ohne Scrollen sichtbar.
5. Kritische Rückmeldungen erscheinen direkt am Nutzungspunkt und nicht nur als flüchtiger Toast.

---

## Kurzfazit

Der aktuelle Stand ist für einen PoC bereits solide:
- feste Bottom-Navigation ist für Einhand-Bedienung grundsätzlich gut
- Haupt-Buttons erreichen bereits die 48px-Zielgröße
- der Detailscreen enthält mit `Route Intelligence`, Lagerort und Menge schon die richtige operative Information

Die größten Hebel liegen aktuell nicht in einem kompletten Redesign, sondern in drei konkreten Punkten:
- **Primäre Aktionen noch klarer priorisieren**
- **Form-Aktionen im Alert-Flow stabiler unten verankern**
- **kognitive Last auf dem Detailscreen weiter reduzieren**

---

## Findings

### 1. Picking-Liste: Primäre Aktion ist funktional, aber noch zu implizit

**Screen:** Picking-Liste

**Beobachtung:**
Jede Karte ist vollständig klickbar, aber die Hauptaktion ist nur indirekt erkennbar.
Im aktuellen Zustand muss der Nutzer verstehen, dass die ganze Karte die Aktion "Auftrag öffnen" bedeutet.

**Warum relevant im Lager:**
Unter Zeitdruck sind explizite Handlungsangebote schneller erfassbar als implizite Klick-Flächen.
Gerade bei mehreren Aufträgen wird sonst eher "lesen und interpretieren" nötig als "sehen und tippen".

**Empfohlene Änderung:**
- auf jeder Karte eine klare Primärhandlung sichtbar machen, z. B. `Öffnen`, `Starten` oder Chevron
- den wahrscheinlich nächsten sinnvollen Auftrag visuell stärker hervorheben
- optional die erste relevante Routeninfo direkt in der Liste zeigen

**Priorität:** Hoch

---

### 2. Picking-Detail: Es gibt mehrere Bedienzentren statt einer klaren Einhand-Zone

**Screen:** Picking-Detail

**Beobachtung:**
Der Screen verteilt wichtige Aktionen auf drei Bereiche:
- zurück zur Liste oben rechts im Content
- `Bestätigen` in der Karte
- Voice/Scan/Problem in der Bottom-Navigation

Damit ist die Bedienung zwar vollständig, aber nicht maximal fokussiert.
Der Nutzer muss je nach Aktion zwischen mittlerem und unterem Bildschirmbereich wechseln.

**Warum relevant im Lager:**
Einhand-Bedienung wird dann am stärksten, wenn die häufigste Folgehandlung immer an derselben Stelle liegt.
Im Picking ist das typischerweise die nächste Bestätigung oder der nächste problembezogene Sonderfall.

**Empfohlene Änderung:**
- `Bestätigen` visuell noch stärker als Hauptaktion markieren
- prüfen, ob die Bestätigung näher an die untere Daumen-Zone rücken soll
- die Navigation zurück zur Liste weniger präsent machen als den operativen Hauptfluss

**Priorität:** Hoch

---

### 3. Picking-Detail: Barcode-Zeile erzeugt unnötige kognitive Last

**Screen:** Picking-Detail

**Beobachtung:**
Die Karte zeigt Produkt, Lagerort, Menge und zusätzlich den vollständigen Barcode.
Für den Normalfall ist das deutlich mehr visuelle Information, als der Touch-Flow zum Bestätigen braucht.

**Warum relevant im Lager:**
Unter Bewegung, Lärm und Zeitdruck hilft eine Oberfläche, wenn sie die Entscheidung vereinfacht:
`Ist das der richtige Ort, der richtige Artikel, die richtige Menge?`
Eine lange Barcode-Zeile konkurriert dabei mit wichtigeren Informationen.

**Empfohlene Änderung:**
- Barcode standardmäßig visuell abschwächen oder einklappen
- alternativ nur die letzten Ziffern oder ein kurzes Identifikationsmerkmal anzeigen
- Produktname, Lagerort und Menge als operatives Trio noch konsequenter hervorheben

**Priorität:** Mittel

---

### 4. Quality-Alert-Formular: Submit-Aktion ist noch nicht robust genug am unteren Rand verankert

**Screen:** Quality Alert

**Beobachtung:**
`Absenden` und `Abbrechen` liegen im Formularfluss und nicht in einer stabilen, festen Aktionszone.
Sobald Textarea, Fotos und Mobile-Keyboard zusammenspielen, steigt das Risiko, dass die wichtigste Aktion nicht mehr ideal erreichbar ist.

**Warum relevant im Lager:**
Der Alert-Flow ist ein Ausnahmefall, oft unter Stress.
In solchen Situationen muss die primäre Abschlussaktion sofort auffindbar und wiederholbar erreichbar bleiben.

**Empfohlene Änderung:**
- `Absenden` als feste untere Primäraktion prüfen
- `Abbrechen` optisch klar sekundär halten
- obere Formularfläche auf das Wesentliche reduzieren: Beschreibung, Priorität, Foto-Hinweis

**Priorität:** Hoch

---

### 5. Quality-Alert-Formular: Feedback ist gut vorhanden, aber noch zu toast-lastig

**Screen:** Quality Alert

**Beobachtung:**
Die UI nutzt Toasters bereits sinnvoll, etwa für fehlende Beschreibung oder erfolgreiche Uploads.
Für kritische Fehler oder blockierende Eingaben ist das allein aber relativ flüchtig.

**Warum relevant im Lager:**
Wenn ein Nutzer gerade Fotos aufgenommen oder Text eingegeben hat, darf ein Fehler nicht nur kurz auftauchen und wieder verschwinden.
Sonst muss er rekonstruieren, was genau schiefgelaufen ist.

**Empfohlene Änderung:**
- Feldfehler direkt am `qa-description` anzeigen
- Upload- oder Serverfehler zusätzlich inline oberhalb der Aktionsbuttons festhalten
- Toaster eher als Bestätigung nutzen, nicht als einziges Fehler-Medium

**Priorität:** Mittel

---

### 6. Bottom-Navigation: Gute Basis, aber Rollen der drei Aktionen noch schärfen

**Screen:** Picking-Detail

**Beobachtung:**
Die Bottom-Navigation ist für Einhand-Bedienung grundsätzlich der stärkste Teil des Layouts.
Aktuell stehen dort `Voice`, `Scan` und `Problem` gleichrangig nebeneinander.

**Warum relevant im Lager:**
Wenn drei Sonderaktionen dieselbe visuelle Gewichtung haben, fehlt eine klare Rangordnung zwischen Standardfluss und Ausnahmehandlung.

**Empfohlene Änderung:**
- Scan als wahrscheinlich häufigste Sekundäraktion stärker priorisieren
- Problem-Meldung visuell als Ausnahme markieren
- Voice-Zustand noch eindeutiger persistent visualisieren

**Priorität:** Mittel

---

## Empfohlene Reihenfolge für echte Umsetzung

1. Quality-Alert-Aktionen unten stabilisieren
2. Picking-Liste mit expliziter Primärhandlung schärfen
3. Picking-Detail visuell entschlacken

Diese Reihenfolge verspricht den höchsten Nutzen bei kleinem Eingriff.

---

## Kleine, realistische v1-Änderungen

- Picking-Liste: CTA oder Chevron auf jeder Karte
- Picking-Detail: Barcode visuell abschwächen
- Picking-Detail: `Bestätigen` noch klarer als Primäraktion hervorheben
- Quality Alert: stabilere untere Aktionszone für `Absenden`
- Quality Alert: Inline-Fehler zusätzlich zu Toastern

---

## Definition of Done für diesen Review

- drei Kernscreens wurden gegen dieselben Heuristiken bewertet
- maximal sechs konkrete Findings wurden priorisiert
- die nächsten 1-3 UI-Schritte sind klein genug für den bestehenden PoC

---

## Nächster sinnvoller Schritt

Aus diesem Review **nur eine** kleine UI-Runde ableiten:
- entweder `Quality Alert` robuster machen
- oder `Picking-Detail` für Einhand-Bedienung weiter schärfen

Nicht beides gleichzeitig, damit der Effekt später klar beurteilbar bleibt.
