# Testlauf 13 — fünf Fotos, fünf geprüft

**Datum:** 15.09.2026
**Auftrag:** L1/OUT/00248, Position 5 von 5
**Artikel:** Brick 2x2 hellblau, SKU 6294237, Produkt 77, Regal D-01, 2 Stück,
Alpin Spielwaren GmbH
**Alert:** QA/0378 (Odoo-Datensatz-ID 379)
**Ergebnis:** `completed` / `scrap`, Konfidenz 1,0 — **Antwort nach 248,3 s, alle fünf Fotos
geprüft**

Zeitangaben aus den Container-Logs, UTC.

## 1. Was dieser Lauf prüft

Lauf 12 hat den gleitenden Schätzwert beim **Einschwingen** gezeigt: die ersten drei Aufrufe liefen
noch gegen die Vorgabe von 60 s. Dieser Lauf zeigt ihn im **Dauerbetrieb** — das Backend wurde
nicht neu gestartet, die Messreihe aus Lauf 12 (49,0 / 42,4 / 56,1 / 49,9 s) lag also von Foto 1
an vor.

Die Frage: Was tut der gemessene Wert, wenn die Aufrufe schneller werden als die Messreihe?

## 2. Eingangsdaten

Vorlage: Katalogbild aus Odoo (`default_code = 6294237`, 1 636 Byte PNG). ChatGPT erzeugte daraus
fünf Ansichten desselben beschädigten Steins, alle freigestellt auf weiß: schräg von oben,
Draufsicht auf die vier Noppen, Nahaufnahme der Bruchstelle, Ansicht von hinten, Ansicht von unten.

```
Kategorie:    Artikel beschädigt
Priorität:    Normal
Beschreibung: Testlauf 13: Artikel beschaedigt: Brick 2x2 hellblau (SKU 6294237), Regal D-01.
              Noppe abgebrochen, Riss ueber die Oberseite, Ecke abgeplatzt.
              Nicht versandfaehig. Fuenf Fotos angehaengt.
Fotos:        5  (354 KB gesamt)
```

## 3. Zeitlicher Ablauf

| Zeit (UTC) | Δ zum Start | Ereignis | Dauer (Backend) |
|---|---|---|---|
| 13:32:43,9 | 0 s | Absenden in der PWA, `POST /api/quality-alerts` → 200 OK | — |
| ≈13:32:47 | ≈3 s | Anfrage `assessments/quality`, Anruferfrist bis ≈13:37:02 | — |
| 13:33:15,1 | 31,2 s | Textbewertung `qwen2.5:7b` fertig (238 Token) | 26,31 s |
| 13:33:16,5 | 32,7 s | `embed_abgleich`: **`match`**, 6294237 auf **0,9139**, Abstand 0,0372 | 1,08 s |
| 13:34:03,9 | 80,1 s | `vision_probe` Foto 1 | 45,77 s |
| 13:34:43,1 | 119,2 s | `vision_probe` Foto 2 | **37,48 s** |
| 13:35:26,0 | 162,1 s | `vision_probe` Foto 3 | 39,57 s |
| 13:36:10,0 | 206,1 s | `vision_probe` Foto 4 | 42,33 s |
| 13:36:52,2 | 248,3 s | **`vision_probe` Foto 5**, Antwort → 200 OK, `callbacks/status` → 200 OK | 40,55 s |

**Die Zeile `Fotos: N weitere ungeprüft.` fehlt im Alert zum ersten Mal ganz.** Es blieb nichts
liegen. Nur der Zustandsvergleich fiel aus, und auch das steht im Log:

```json
{"event_type": "vision_budget_stop", "stelle": "zustandsvergleich", "restzeit_s": 21.0, "schaetzung_s": 49.9, "offene_fotos": 0}
```

## 4. Wie der Schätzwert mitwandert

| Nach Foto | Messreihe (sortiert, s) | 80-%-Wert | Wirkung |
|---|---|---|---|
| — (Start) | 42,4 / 49,0 / 49,9 / 56,1 | **56,1 s** | aus Lauf 12 übernommen |
| 1 | 42,4 / 45,8 / 49,0 / 49,9 / 56,1 | 56,1 s | unverändert |
| 2 | 37,5 / 42,4 / 45,8 / 49,0 / 49,9 / 56,1 | **49,9 s** | **sinkt** — Schranke wird durchlässiger |
| 3 | + 39,6 | 49,9 s | unverändert |
| 4 | + 42,3 (8 Werte, ältester fällt raus) | 49,9 s | unverändert |

Der Sprung nach Foto 2 ist der Kern dieses Laufs. Mit 37,48 s lieferte es den **schnellsten
Bildaufruf aller dreizehn Läufe**; der 80-%-Wert fiel dadurch von 56,1 s auf 49,9 s.

Vor Foto 5 blieben 49,0 s Restzeit:

* Mit dem alten festen Wert von 60 s wäre bereits **Foto 4** nicht gestartet (49,0 s Reserve nach
  Foto 3 lagen unter 60 s) — der Lauf hätte bei drei Fotos geendet.
* Mit 49,9 s startete Foto 5 knapp, brauchte 40,55 s und war mit **21 s Reserve** fertig.

Der Grund für die kurzen Aufrufe liegt am Artikel: ein 2x2-Stein ist kleiner und formärmer als
eine 2x4-Platte oder ein Bogenstein. Der gleitende Wert bemerkt das **innerhalb desselben Laufs**;
ein fester Wert kann es grundsätzlich nicht.

## 5. Backend-Zeit gegen Ollama-Zeit

| Aufruf | ollama | Backend | Differenz |
|---|---|---|---|
| Text (`task 236`) | 26,31 s | — | — |
| Foto 1 (`task 251`) | 41,78 s | 45,77 s | 3,99 s |
| Foto 2 (`task 314`) | 34,37 s | 37,48 s | 3,11 s |
| Foto 3 (`task 370`) | 35,75 s | 39,57 s | 3,82 s |
| Foto 4 (`task 431`) | 39,44 s | 42,33 s | 2,89 s |
| Foto 5 (`task 500`) | 37,83 s | 40,55 s | 2,72 s |

Die Differenz liegt hier stabil bei 2,7–4,0 s, in Lauf 12 schwankte sie zwischen 1,0 und 7,1 s.
Kein `cancel task` im Zeitfenster.

## 6. Ergebnis der Systembewertung

```
ai_evaluation_status:  completed
ai_disposition:        scrap
ai_confidence:         1.0
ai_summary:            Abgebrochene Noppe und sichtbare Schäden machen den Artikel unbrauchbar.
ai_photo_analysis:     Schaden: SICHTBAR -- Riss, gebrochene Kante, abgeplatzte Kante, gouged stud.
                       Zustand: nicht verglichen (Zeitbudget erschöpft).
ai_recommended_action: Ware sperren, aussondern und Schichtleitung informieren.
ai_model:              qwen2.5:7b
ai_last_analyzed_at:   2026-09-15 13:36:52
```

**Ein Befund ist englisch geblieben: `gouged stud`.** Das Glossar in `_schadensworte`
(`n8n_v2.py`) übersetzt die bekannten Begriffe, kennt diesen aber nicht. Aus fünf Fotos kamen vier
verschiedene Befunde — mehr Fotos heißt auch mehr Wortvielfalt und damit mehr Lücken im Glossar.

## 7. Der Fortschritt über drei Läufe

| | Lauf 11 | Lauf 12 | Lauf 13 |
|---|---|---|---|
| Artikel | Plate 2x4 grün | Brick 2x4 hellgelb | Brick 2x2 hellblau |
| Schätzwert | fest 60 s | gleitend ab Foto 3 | gleitend von Anfang an |
| **Fotos geprüft** | 2 von 5 | 4 von 5 | **5 von 5** |
| Bildaufrufe | 82,9 / 59,1 s | 49,0 / 42,4 / 56,1 / 49,9 s | 45,8 / 37,5 / 39,6 / 42,3 / 40,6 s |
| Laufzeit | 247,9 s | 252,5 s | 248,3 s |
| Auslastung Knotenlimit | 92 % | 94 % | 92 % |

Bei praktisch gleicher Laufzeit steigt die Zahl der geprüften Fotos von zwei auf fünf. Der Gewinn
kommt nicht aus mehr Rechenleistung, sondern aus einer Schätzung, die dem tatsächlichen Verhalten
folgt statt einem einmal gesetzten Wert.

## 8. Artikelachse

| Rang | Artikel | Wert |
|---|---|---|
| 1 | **6294237 (erwartet)** | **0,9139** |
| 2 | 343701 | 0,8768 |
| 3 | 6294241 — Brick 2x3 W. Inv. Bow hellblau | 0,8022 |

0,9139 ist der zweitbeste Platz-1-Wert aller Läufe (nach 0,9176 in den Läufen 9 und 10). Der
Abstand von 0,0372 liegt sicher über der Knappheitsschwelle, aber deutlich unter dem Wert des
Dachsteins aus Lauf 6 (0,2396) — der 2x2-Würfel ist eine häufige Form im Katalog.

## 9. Abweichungen und bekannte Vorbelastung

* Der Einbettungsabgleich brauchte 1,08 s statt der sonst 194–254 ms. Der Katalog lag im Cache;
  die Ursache ist nicht geklärt und liegt im Bereich üblicher Schwankung des Dienstes.
* Odoo protokolliert weiterhin alle 13–15 s `RuntimeError: Couldn't bind the websocket`.

## 10. Belege

* `fotos/`, `fotos_original/`, `kontaktabzug.jpg`, `pruefsummen.txt`
* `run13_brick2x2_hellblau.png` — Katalogbild aus Odoo
* `logs/backend.log` (mit der `vision_budget_stop`-Zeile), `logs/ollama.log`, `logs/odoo.log`

## 11. Was offen bleibt

1. **Der Zustandsvergleich kommt seit Lauf 9 nie mehr dran.** Er steht am Ende der Kette, und mit
   fünf Fotos bleibt nie ein voller Aufruf übrig. Wenn er fachlich wichtiger ist als das fünfte
   Foto, muss er **vor** die letzten Fotos — das ist eine fachliche Entscheidung, keine technische.
2. **Das Glossar hat Lücken** (`gouged stud`). Mehr geprüfte Fotos heißt mehr Wortvielfalt; die
   Übersetzung muss mitwachsen oder der Prompt die Wortwahl enger führen.
3. **Die Messreihe überlebt keinen Neustart.** Nach jedem Backend-Neustart laufen die ersten drei
   Aufrufe wieder gegen die Vorgabe von 60 s.
