# Lauf 25 — Unbeschädigtes Teil: erzeugt die Kette einen Befund, wo keiner ist? (QA/0387)

**Datum:** 16.09.2026
**Artikel:** Brick 2x2 gelb, SKU 343724, Produkt-ID 75
**Auftrag:** L1/OUT/00300, Position 4 von 7, Regal C-01
**Fotos:** 3, freigestellt auf weiß, aus dem Katalogbild erzeugt, **ohne jeden Schaden**
**Endzustand:** `completed`, **`sellable`**, Konfidenz **1,0**
**Laufzeit:** 14:19:20 bis 14:22:05 UTC = **2 min 45 s**

## Was der Lauf prüft

Alle 22 bisherigen Kettenläufe enthielten einen echten Schaden. Die Gegenrichtung war ungemessen:
Was tut die Kette, wenn nichts zu finden ist? Für eine Bewertung, die Ware sperren kann, ist das
die wichtigere Hälfte — ein Falschbefund kostet Bestand, eine übersehene Meldung nur Zeit.

Zwei Nebenfragen hängen daran. Der **Zustandsvergleich** läuft seit dem 15.09. nur noch bei
`intact` (Lauf 14) und kam seither in keinem Kettenlauf mehr dran; hier musste er laufen. Und der
**Soll-Befund-Cache** aus Lauf 18 zeigt sich erst im Kettenbetrieb an einem neuen Artikel.

Damit keine Stufe den Befund vorwegnimmt: Schnellauswahl **„Sonstiges"** statt „Artikel
beschädigt", und eine Beschreibung ohne Schadenswort.

## Eingangsdaten

Beschreibung: „Kontrollmeldung ohne erkennbaren Mangel. Teil wirkt unbeschaedigt, Oberflaeche
glatt, Kanten sauber, alle Noppen vollstaendig. Drei Fotos zur Gegenpruefung."

| Foto | Ansicht | MD5 (JPEG) |
|---|---|---|
| 1 | schräg von oben wie die Vorlage | `3A512F3C8966022CCC7067328DD4F48E` |
| 2 | flachere Seitenansicht, gedreht | `34E4ED248932DD2F7FD72FF482C47FDA` |
| 3 | Nahaufnahme der vier Noppen | `C4DB6918B055448A0275B1612855CD25` |

## Zeitlicher Ablauf

| Zeit (UTC) | Komponente | Ereignis | Dauer |
|---|---|---|---|
| 14:19:20 | PWA | Meldung abgesendet, QA/0387 | — |
| 14:19:22,9 | Backend | Webhook an n8n | 2,6 s |
| 14:19:36,3 | `embed` | Artikelabgleich, `match` | **0,62 s** |
| 14:20:11,8 | ollama | Foto 1 geprüft | **35,5 s** |
| 14:20:48,4 | ollama | Foto 2 geprüft | **36,6 s** |
| 14:21:26,3 | ollama | Foto 3 geprüft | **37,9 s** |
| 14:21:26,3 | Backend | `soll_cache_geladen`, 1 Eintrag aus `/var/cache/pwr/soll_befunde.json` | — |
| 14:21:46,6 | ollama | **Katalogbild** für den Zustandsvergleich | **20,3 s** |
| 14:22:05,5 | ollama | Textvergleich Soll gegen Ist | **18,8 s** |
| 14:22:05 | Odoo | `completed` | — |

Auslastung des Knotenlimits: 165 s von 270 s = **61 %**. Vier Bildaufrufe, 130,3 s von 240 s = 54 %.

**Der Katalog wurde nicht neu eingebettet** — anders als in Lauf 24, wo das 12,2 s kostete. Der
Cache des Backends war aus dem Vorlauf warm.

## Ergebnis: kein Falschbefund

```
ai_disposition:        sellable
ai_confidence:         1.0
ai_summary:            Kein Mangel nach Prüfung.
ai_photo_analysis:     Schaden: keine Auffälligkeit sichtbar.
ai_recommended_action: Sichtprüfung durch Qualitätsteam.
```

**Alle drei Fotos ergaben `intact`.** Keine erfundene Anomalie, kein Begriff im Formular, der nicht
im Bild steht. Damit ist die vierte Einstufung belegt, und die Wahrheitstabelle hat erstmals einen
Eintrag auf der negativen Seite:

| Fall | Läufe | Ergebnis |
|---|---|---|
| Oberflächenschaden vorhanden, erkannt | 5–14, 20, 24 | `scrap` / `quarantine` |
| Schaden vorhanden, **nicht** erkannt (fehlende Geometrie) | 15–18 | `review_required` über den Widerspruchszweig |
| **Kein Schaden, kein Befund** | **25** | **`sellable`, Konfidenz 1,0** |

### Der Zustandsvergleich lief zum ersten Mal seit Lauf 15 vollständig durch

```json
{"event_type": "condition_compare", "new_damage": false, "damage": "intact",
 "reason": "Die Beschreibungen stimmen überein und deuten auf den gleichen Zustand hin."}
```

Er kostete **39,1 s** — 20,3 s für das Katalogbild plus 18,8 s Textvergleich. Der Soll-Befund-Cache
war geladen, enthielt aber nur den einen Eintrag aus Lauf 18 (Artikel 4183780), nicht diesen
Artikel. Der Katalogbildaufruf fiel deshalb an. **Genau so ist der Cache gemeint:** er spart ab der
zweiten Meldung je Artikel, nicht bei der ersten.

Die Abfolge bestätigt außerdem die Reihenfolge-Entscheidung aus Lauf 14 an ihrem Gegenstück: Bei
`damaged` wird der Vergleich übersprungen (Lauf 24), bei `intact` läuft er — und hier hatte die
Kette mit 105 s Restzeit auch Platz dafür.

### Artikelachse

```
"urteil": "match", "erwartet": "343724",
"rang": [["343724", 0.9534], ["4648231", 0.8962], ["4159527", 0.8908]], "abstand": 0.0571
```

**0,9534 ist der höchste Spitzenwert aller Läufe** (bisher 0,9318 in Lauf 5). Plausibel: Das Foto
zeigt ein makelloses Teil, das Katalogbild ebenfalls — ohne Schaden gibt es keinen Unterschied, den
die Einbettung bestrafen könnte. Der Abstand ist mit 0,0571 dennoch mäßig, weil auf Platz 2 und 3
zwei weitere gelbe 2x2-Steine liegen: Die Farbe zieht die Kandidaten zusammen, wie schon in Lauf 11.

Für die untere Schranke aus Lauf 23 ist das ein weiterer richtiger Fall weit über 0,80.

## Beobachtung ohne Messwert

`ai_recommended_action` lautet auch im sauberen Fall „Sichtprüfung durch Qualitätsteam". Bei
`sellable` mit Konfidenz 1,0 ist das kein hilfreicher Satz — die Handlungsempfehlung folgt der
Einstufung offenbar nicht. Kein Fehler der Bewertung, aber eine Stelle im Formular, die einem
Lagerarbeiter das Gegenteil dessen nahelegt, was die Kette entschieden hat.

## Vergleich mit dem Vorlauf

| | Lauf 24 (beschädigt) | **Lauf 25 (unbeschädigt)** |
|---|---|---|
| Fotos | 3 | 3 |
| Bildaufrufe | 3 | **4** (mit Katalogbild) |
| Bildzeit | 155,5 s | **130,3 s** |
| Zustandsvergleich | übersprungen | **gelaufen, 39,1 s** |
| Artikelachse | 0,9146 | **0,9534** |
| Einstufung | `quarantine` 0,8 | **`sellable` 1,0** |
| Laufzeit | 3 min 19 s | **2 min 45 s** |

Die Bildaufrufe waren mit 35,5–37,9 s am **unteren** Rand des Bandes 37–83 s — ein makelloses Teil
liefert kürzere Befundlisten als ein beschädigtes und kostet deshalb weniger Ausgabetoken.

## Belege

* `fotos/`, `fotos_original/`, `kontaktabzug.jpg`, `pruefsummen.txt`
* `logs/` — Backend-, ollama-, n8n- und Odoo-Auszüge
* `run25_brick2x2_gelb.png` — das Katalogbild als Vorlage
