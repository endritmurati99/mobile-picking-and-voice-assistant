# Lauf 28 — Neuer Auftrag, neue Form, frische Bilder: die saubere Zeitreferenz (QA/0390)

**Datum:** 16.09.2026
**Artikel:** Flower hellblau, SKU 6294208, Produkt-ID 103
**Auftrag:** **L1/OUT/00263** (Wal, ACME Demo GmbH), Position 6 von 6, Regal C-01
**Fotos:** 3, frisch erzeugt, freigestellt, aus dem Katalogbild
**Endzustand:** `completed`, **`rework`**, Konfidenz 0,80
**Laufzeit:** 15:44:28 bis 15:46:50 UTC = **2 min 22 s**

## Was der Lauf prüft

Lauf 27 hat gezeigt, dass Wiederholungen mit identischen Bilddateien einen warmen Prompt-Cache in
ollama messen (5 statt 459 Prompt-Token je Aufruf). Alle bisherigen Zeitpaare stehen damit unter
Vorbehalt. Dieser Lauf liefert die Gegenprobe: **neuer Auftrag, neuer Artikel, drei frisch erzeugte
Bilddateien** — keine davon war je in der Kette.

Zweitens ist die Form neu: ein fünfblättriges, dünnwandiges Blütenteil. Bisher liefen alle Läufe
über Quader, Platten, Dachsteine und Rundsteine.

| Foto | Ansicht | MD5 (JPEG) |
|---|---|---|
| 1 | schräg von oben wie die Vorlage | `C03AA591BA4D03B0BB8AF5AEA162BAC7` |
| 2 | strenge Draufsicht | `207DB52A13D2AEF72A6BF8B9895CABDB` |
| 3 | Nahaufnahme der Rissstelle | `91FDC5BEBEAFA016FC11690EA7D37860` |

Beschreibung: „Zwei Bluetenblaetter sind gerissen, an einer Stelle ist der Rand eingerissen mit
rauer Bruchflaeche. Drei Fotos, freigestellt." Schnellauswahl „Artikel beschädigt".

## Befund 1: Die frische Zeitreferenz

**Die Gegenprobe im ollama-Log ist eindeutig:**

| Aufruf | `prompt eval` | Dauer im Backend |
|---|---|---|
| Foto 1 (task 3181) | **459 Token**, 23,3 s | **33,6 s** |
| Foto 2 (task 3237) | **459 Token**, 27,7 s | **36,8 s** |
| Foto 3 (task 3287) | **459 Token**, 31,6 s | **43,3 s** |

459 Token je Aufruf, also volle Auswertung — kein Cache-Treffer. Zum Vergleich Lauf 27 mit
identischen Dateien aus Lauf 25: 5 Token, 12,1 bis 24,5 s.

**Damit steht eine belastbare Zahl:** Ein Meldefoto kostet bei frischem Bildinhalt und warmem
Modell **33,6 bis 43,3 s**. Das liegt im bekannten Band 37–83 s, aber am unteren Rand und ohne die
Ausreißer nach oben, die in den Läufen 11 (82,9 s) und 24 (65,8 s) auftraten.

| | Lauf 24 (frisch) | Lauf 25 (frisch) | Lauf 27 (Cache) | **Lauf 28 (frisch)** |
|---|---|---|---|---|
| Bildaufrufe | 65,8 / 46,2 / 43,5 s | 35,5 / 36,6 / 37,9 s | 24,5 / 12,1 / 14,6 s | **33,6 / 36,8 / 43,3 s** |
| `prompt eval` | 459 | 459 | **5** | **459** |

Die drei frischen Läufe streuen zwischen 33,6 und 65,8 s je Aufruf — der Cache-Lauf liegt
vollständig darunter. **Der Effekt aus Lauf 27 ist damit an einem unabhängigen Fall bestätigt.**

## Befund 2: `rework` — die fünfte Einstufung

```
ai_disposition:        rework
ai_confidence:         0.80
ai_summary:            Rissige Bluetenblaetter können repariert werden.
ai_photo_analysis:     Schaden: SICHTBAR -- Riss, gebrochene Kante.
ai_recommended_action: Nacharbeit prüfen und Verpackung korrigieren.
```

Zum ersten Mal in der Reihe. Damit sind alle fünf Ausgänge an echten Fällen belegt:

| Einstufung | Erstmals in | Fall |
|---|---|---|
| `scrap` | Lauf 5 | schwerer Bruch |
| `review_required` | Lauf 15 | Widerspruch Text gegen Bild |
| `quarantine` | Lauf 24 | Riss mit Ausbruch |
| `sellable` | Lauf 25 | kein Schaden |
| **`rework`** | **Lauf 28** | **Risse an einem reparablen Teil** |

Die Begründung ist sachlich bemerkenswert: Das Textmodell leitet aus „gerissene Blütenblätter" ab,
dass Nacharbeit möglich ist, während derselbe Befundtyp (`Riss, gebrochene Kante`) in Lauf 24 zu
`quarantine` führte. Die Bildachse lieferte in beiden Fällen dieselben zwei Wörter — **die
Unterscheidung entsteht allein auf der Textachse, aus Artikelname und Meldungstext.** Das ist
dieselbe Arbeitsteilung wie in Lauf 26, dort aber als Schwäche sichtbar (Kratzer als „Riss") und
hier als Stärke.

## Befund 3: Die Artikelachse trägt auch bei filigraner Form

```
"urteil": "match", "erwartet": "6294208",
"rang": [["6294208", 0.9241], ["4100853", 0.7448], ["6214736", 0.7236]]
```

**Spitzenwert 0,9241, Abstand 0,1793** — der drittgrößte Abstand aller Läufe, hinter Lauf 6
(0,2396) und Lauf 24 (0,1585). Die Sorge, ein dünnwandiges, durchbrochenes Teil könnte die
Einbettung überfordern, bestätigt sich nicht: Gerade die ungewöhnliche Silhouette trennt es sauber
vom Rest des Katalogs. Auf Platz 2 und 3 liegen Teile mit rund 0,73 — deutlich abgeschlagen.

Auch dieser Fall liegt weit über der in Lauf 23 vorgeschlagenen unteren Schranke von 0,80.

## Zeitlicher Ablauf

| Zeit (UTC) | Komponente | Ereignis | Dauer |
|---|---|---|---|
| 15:44:28 | PWA | Meldung abgesendet, QA/0390 | — |
| 15:44:31,3 | Backend | Webhook an n8n | 2,9 s |
| 15:44:32–15:44:45 | ollama `qwen2.5:7b` | Textbewertung (task 456, 76 Prompt-Token) | ≈ 13 s |
| 15:44:48,5 | `embed` | Artikelabgleich `match` | < 1 s |
| 15:45:24,9 | ollama | Foto 1 | **33,6 s** |
| 15:46:04,4 | ollama | Foto 2 | **36,8 s** |
| 15:46:50,5 | ollama | Foto 3 | **43,3 s** |
| 15:46:50,5 | Backend | `condition_compare_skipped`, `schaden_bereits_sichtbar` | 0 s |
| 15:46:50 | Odoo | `completed` | — |

**53 % des Knotenlimits**, 113,7 s von 240 s Bildbudget. Reserve 128 s.

## Abweichungen

Keine. Beide Modelle waren warm (`ollama ps` vor dem Lauf: `qwen2.5:7b` und `gemma4:12b`), ollama
lag bei 0,01 % CPU, der Artikelkatalog war eingebettet, der Zustandsvergleich wurde regelkonform
übersprungen.

Bekannte Vorbelastung: Odoo-Websocket-Fehler im Sekundentakt, unabhängig von der Kette.

## Belege

* `fotos/`, `fotos_original/`, `kontaktabzug.jpg`, `pruefsummen.txt`
* `logs/` — Backend- und ollama-Auszüge, darin die drei `prompt eval`-Zeilen mit je 459 Token
* `run28_flower_hellblau.png` — das Katalogbild als Vorlage
