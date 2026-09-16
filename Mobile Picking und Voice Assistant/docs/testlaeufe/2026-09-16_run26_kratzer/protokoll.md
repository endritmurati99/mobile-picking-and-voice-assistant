# Lauf 26 — Leichter Kratzer: ist die Einstufung abgestuft oder binär? (QA/0388)

**Datum:** 16.09.2026
**Artikel:** Brick 2x2 gelb, SKU 343724 — **derselbe wie in Lauf 25**
**Auftrag:** L1/OUT/00300, Position 4 von 7, Regal C-01
**Fotos:** 3, freigestellt, aus dem Katalogbild, **ein feiner Kratzer** auf der Oberseite
**Endzustand:** **`review_required`** über den Widerspruchszweig
**Laufzeit:** 15:16:18 bis 15:18:47 UTC = **2 min 29 s**

## Was der Lauf prüft

Die Reihe kennt bisher drei Schweregrade: kein Schaden → `sellable` (Lauf 25), Riss mit Ausbruch →
`quarantine` (Lauf 24), schwerer Bruch → `scrap` (Läufe 13, 20). Ungemessen war der Fall
dazwischen. Ein **Kratzer** ist der Grenzfall, an dem sich zeigt, ob die Skala trägt oder ob die
Kette nur zwischen „heil" und „kaputt" unterscheidet.

Direkte A/B-Gegenprobe zu Lauf 25 — gleicher Artikel, gleicher Auftrag, gleiche Position, gleiche
drei Ansichten, gleiche Schnellauswahl „Sonstiges". **Einzige Änderung: der Kratzer.**

| Foto | Ansicht | MD5 (JPEG) |
|---|---|---|
| 1 | schräg von oben | `A6EF1865780C5F2223A60BB5A286C4AC` |
| 2 | flachere Seitenansicht | `1EF101245BA12B2C0F8478B2AC240BCF` |
| 3 | Nahaufnahme auf den Kratzer | `0C38901F7F4C5E2941754E1AB5356DEA` |

Beschreibung: „Auf der Oberseite verlaeuft ein feiner Kratzer. Kanten und Noppen sind vollstaendig,
kein Bruch. Drei Fotos zur Beurteilung."

## Zeitlicher Ablauf

| Zeit (UTC) | Komponente | Ereignis | Dauer |
|---|---|---|---|
| 15:16:18 | PWA | Meldung abgesendet, QA/0388 | — |
| 15:16:19,9 | Backend | Webhook an n8n | 1,7 s |
| 15:16:41,6 | `embed` | Artikelabgleich, `match` | < 1 s |
| 15:17:32,3 | ollama | Foto 1 geprüft | **45,3 s** |
| 15:18:06,4 | ollama | Foto 2 geprüft | **31,4 s** |
| 15:18:46,8 | ollama | Foto 3 geprüft | **37,7 s** |
| 15:18:46,8 | Backend | `condition_compare_skipped`, `schaden_bereits_sichtbar` | 0 s |
| 15:18:47 | Odoo | `review_required` | — |

55 % des Knotenlimits, 114,4 s von 240 s Bildbudget. Der schnellste Lauf mit drei Fotos bisher.

## Ergebnis: die beiden Achsen sind unterschiedlich fein

```
ai_evaluation_status: review_required
ai_failure_reason:    Foto widerspricht der Meldung, siehe Fotoanalyse.
ai_photo_analysis:    Schaden: SICHTBAR -- Riss, Bruch.
                      Hinweis: Foto zeigt einen Schaden, die Meldung stuft die Ware als
                      verkaufsfähig ein.
                      Texturteil der Meldung (nicht wirksam): sellable, Konfidenz 1.00.
                      Kratzer ohne Schaden an Form oder Funktionalitaet.
```

**Die Textachse stuft richtig ab.** `qwen2.5:7b` urteilt `sellable` mit der Begründung „Kratzer
ohne Schaden an Form oder Funktionalitaet" — genau die Unterscheidung, um die es geht.

**Die Bildachse tut es nicht.** `gemma4:12b` meldet **`Riss, Bruch`** für einen feinen Kratzer. Das
ist die Umkehrung des Befunds aus Lauf 15: Dort übersah das Bildmodell einen echten Schaden, hier
übertreibt es einen geringfügigen. Beide Male ist die Ursache dieselbe Prompt-Stelle — der
`DAMAGE_PROMPT` kennt nur `damaged: true/false` und eine Wortliste aus Riss, Bruch und gebrochener
Kante. **Eine Schwereskala existiert auf der Bildachse gar nicht**, also kann sie auch nichts
abstufen; ein Kratzer wird auf das nächstliegende Wort abgebildet, und das heißt „Riss".

**Die Kette selbst hat richtig entschieden.** Text `sellable` gegen Bild „Schaden sichtbar" — der
Widerspruchszweig machte daraus `review_required` mit beiden Seiten im Klartext, statt eine der
Halbwahrheiten wirksam zu machen. `ai_disposition` bleibt leer, `ai_confidence` 0,0: **nichts wird
automatisch verfügt.**

Damit greift der Zweig zum zweiten Mal an einem echten Fall, und diesmal in der anderen Richtung:

| | Lauf 15 | **Lauf 26** |
|---|---|---|
| Realer Zustand | Ecke sauber abgebrochen | feiner Kratzer |
| Textachse | `scrap` | **`sellable`** |
| Bildachse | `intact` (übersehen) | **`Riss, Bruch` (übertrieben)** |
| Ergebnis | `review_required` | **`review_required`** |

**Der Widerspruchszweig fängt beide Fehlerrichtungen des Bildmodells ab.** Das ist das belastbarste
Ergebnis dieses Laufs: Nicht dass eine Achse irrt — sondern dass die Konstruktion aus zwei
unabhängigen Achsen plus Widerspruchsregel den Irrtum nicht wirksam werden lässt.

## Gegenprobe zu Lauf 25

| | Lauf 25 (kein Schaden) | **Lauf 26 (Kratzer)** |
|---|---|---|
| Artikel, Auftrag, Ansichten, Auswahl | identisch | identisch |
| Bildbefund | `intact`, dreimal | **`Riss, Bruch`** |
| Textbefund | `sellable` 1,0 | `sellable` 1,0 |
| Zustandsvergleich | gelaufen, 39,1 s | **übersprungen** |
| Artikelachse | 0,9534 | **0,9708** |
| Ergebnis | `sellable` 1,0 | **`review_required`** |
| Laufzeit | 2 min 45 s | **2 min 29 s** |

**Ein einziger feiner Kratzer kippt das Ergebnis von „verkaufsfähig" auf „Handprüfung".** Bei sonst
identischer Eingabe. Für den Betrieb heißt das: Die Kette ist auf der Bildachse empfindlich
eingestellt — sie lässt eher prüfen als durchgehen. Für eine Qualitätsmeldung ist das die richtige
Richtung, kostet aber Handarbeit bei Bagatellschäden.

Nebenbefund: **0,9708 ist der neue Höchstwert der Artikelachse** (vorher 0,9534 in Lauf 25,
ebenfalls dieser Artikel). Ein Kratzer stört die Einbettung praktisch nicht.

Der Soll-Befund-Cache kam nicht zum Zug: Der Zustandsvergleich wurde übersprungen, weil das Bild
bereits Schaden meldete. Die für diesen Artikel in Lauf 25 erzeugte Soll-Beschreibung blieb
ungenutzt — richtig so, aber die erhoffte zweite Cache-Messung fiel damit aus.

## Abweichungen

Im Kontaktabzug ist der Kratzer nach der Skalierung auf 1 024 px (`DAMAGE_MAX_EDGE`) kaum noch zu
erkennen. Dass das Bildmodell ihn trotzdem — und zu deutlich — gemeldet hat, heißt: Er hat die
Verkleinerung überstanden. Eine Aussage über noch feinere Schäden lässt der Lauf nicht zu.

Bekannte Vorbelastung: Odoo-Websocket-Fehler im Sekundentakt, unabhängig von der Kette.

## Belege

* `fotos/`, `fotos_original/`, `kontaktabzug.jpg`, `pruefsummen.txt`
* `logs/` — Backend-, ollama-, n8n- und Odoo-Auszüge
* Vorlage: `../2026-09-16_run25_unbeschaedigt/run25_brick2x2_gelb.png` (dasselbe Katalogbild)
