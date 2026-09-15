# Testlauf 9 — fünf Fotos, und der erste Abbruch seit der Threadkorrektur

**Datum:** 15.09.2026
**Auftrag:** L1/OUT/00303, Position 5 von 6
**Artikel:** Brick Bow 2x3x1 hellblau, SKU 6138111, Produkt 96, Regal C-01, 1 Stück,
Meyer Spielwaren KG
**Alert:** QA/0374 (Odoo-Datensatz-ID 375)
**Ergebnis:** `review_required` / `assessment unavailable` — **Abbruch am n8n-Knotenlimit nach 270 s**

Zeitangaben aus den Container-Logs, UTC.

## 1. Was dieser Lauf prüft

Bis Lauf 8 hatte die Odoo-Konstante `_MAX_ASSESSMENT_PHOTOS = 3` verhindert, dass je mehr als
drei Fotos in die Kette gehen. Damit war unbekannt, was ein viertes und fünftes Foto tatsächlich
kosten. Für diese Messung wurde die Grenze über die neue Umgebungsvariable
`QA_MAX_ASSESSMENT_PHOTOS = 5` angehoben und Odoo neu gestartet.

**Ein Abbruch war das erwartete Ergebnis und ist hier der Befund, nicht der Fehler.**

## 2. Eingangsdaten

Vorlage: Katalogbild aus Odoo (`default_code = 6138111`, 2 100 Byte PNG). ChatGPT erzeugte daraus
fünf Ansichten desselben beschädigten Steins, alle freigestellt auf weiß: schräg von oben,
Draufsicht auf die Noppen, Nahaufnahme der Bruchstelle, Ansicht von hinten, Ansicht von unten.
Schaden: abgebrochene Noppe, Riss über die Wölbung, abgeplatzte Ecke.

```
Kategorie:    Artikel beschädigt
Priorität:    Normal
Beschreibung: Artikel beschaedigt: Brick Bow 2x3x1 hellblau (SKU 6138111), Regal C-01.
              Noppe abgebrochen, Riss ueber die Woelbung, Ecke abgeplatzt.
              Nicht versandfaehig. Fuenf Fotos angehaengt.
Fotos:        5  (fotos/qa_photo_01.jpg bis _05.jpg, je 1 024 px JPEG)
```

## 3. Zeitlicher Ablauf

| Zeit (UTC) | Δ zum Start | Ereignis | Dauer |
|---|---|---|---|
| 09:25:43,6 | 0 s | Absenden in der PWA, `POST /api/quality-alerts` → 200 OK | — |
| ≈09:25:45 | 1,4 s | `POST http://n8n:5678/webhook/quality-assessment-v2` → 200 OK | — |
| ≈09:26:56 | 73 s | Textbewertung `qwen2.5:7b` fertig | **51,14 s** |
| 09:26:57,7 | 74,1 s | `embed_abgleich`: Urteil **`match`**, 6138111 auf **0,9176** | < 1 s |
| 09:27:57,4 | 133,8 s | `vision_probe` Foto 1 (Bilddekodierung 18,34 s), `ok: true` | **59,77 s** |
| 09:28:47,5 | 183,9 s | `vision_probe` Foto 2 (Bilddekodierung 16,81 s), `ok: true` | **50,13 s** |
| 09:29:45,6 | 242,0 s | `vision_probe` Foto 3 (Bilddekodierung 18,55 s), `ok: true` | **58,09 s** |
| **09:30:16** | **273 s** | **n8n bricht ab: `timeout of 270000ms exceeded`**, `callbacks/status` → 200 OK, Odoo bekommt `assessment unavailable` | — |

**Foto 4, Foto 5 und der Katalogbildvergleich kamen nicht mehr an die Reihe.**

### 3.1 Inferenzzeiten

| Aufruf | Modell | Token | Bilddekodierung | Gesamt |
|---|---|---|---|---|
| Textbewertung | `qwen2.5:7b` | 237 | — | 51,14 s |
| Foto 1 | `gemma4:12b` | 519 | 18,34 s | 58,71 s |
| Foto 2 | `gemma4:12b` | 523 | 16,81 s | 49,21 s |
| Foto 3 | `gemma4:12b` | 518 | 18,55 s | 56,95 s |

## 4. Der eigentliche Befund: die Budgetbremse greift nicht

Zum Zeitpunkt des Abbruchs waren **168,0 s** des Bildbudgets von 240 s verbraucht — also 70 %.
`_check_damage` hatte damit keinen Grund, ein Foto zu überspringen, und hätte Foto 4 und 5
weiter geprüft. Der n8n-Knoten hatte zu diesem Zeitpunkt aber längst aufgegeben.

**Das Backend weiß nicht, wann sein Aufrufer aufhört zu warten.** Die Summe der Einzelbudgets
übersteigt das Knotenlimit:

| Posten | Grenze |
|---|---|
| Textbewertung | 90 s |
| Bildbudget für alle Bildaufrufe | 240 s |
| zwei Textvergleiche (Artikel, Zustand) | je bis 90 s |
| **Summe möglich** | **bis 510 s** |
| **n8n-Knoten wartet** | **270 s** |

In diesem Lauf kostete allein die Textbewertung 51,1 s, danach blieben dem Bildteil 219 s. Drei
Fotos zu 50–60 s passen hinein, fünf nicht. Die Bremse, die das hätte auffangen können, misst
aber gegen 240 s statt gegen den Rest bis 270 s.

**Das ist kein Grenzfall, sondern ein Rechenfehler in der Budgetierung.** Er fällt nur deshalb
selten auf, weil die Odoo-Konstante die Fotoanzahl bei drei deckelt — sie ist derzeit das
einzige, was die Kette vor ihrem eigenen Budget schützt.

## 5. Die Bildaufrufe waren langsamer als in allen Vorläufen

| Lauf | Fotos | Dauer je Schadensprüfung |
|---|---|---|
| 6 | 2 | 43,3 / 52,7 s |
| 7 | 3 | 46,6 / 49,3 / 48,4 s |
| 8 | 4 (3 geprüft) | 50,0 / 43,3 / 44,3 s |
| **9** | **5 (3 geprüft)** | **59,8 / 50,1 / 58,1 s** |

Schnitt in Lauf 9: 56,0 s gegen 47,9 s in Lauf 8. Die Bilddekodierung lag mit 16,8–18,6 s im
üblichen Rahmen; der Unterschied steckt in der Auswertung. Eine Erklärung liefert dieser Lauf
nicht — die Modelle waren warm, ollama vor dem Start bei 0,01 % CPU.

## 6. Vergleich aller Fotoanzahlen

| | 1 Foto (L5) | 2 Fotos (L6) | 3 Fotos (L7) | 4 Fotos (L8) | **5 Fotos (L9)** |
|---|---|---|---|---|---|
| übergeben / geprüft | 1 / 1 | 2 / 2 | 3 / 3 | 4 / **3** | 5 / **3** |
| Bildaufrufe | 3 | 3 | 4 | 4 | **3** |
| Bildzeit | 121,6 s | 129,3 s | 169,9 s | 156,5 s | **168,0 s** |
| Knotenzeit | 192,6 s | 161,4 s | 254,5 s | 188,1 s | **> 270 s** |
| Endzustand | `completed` | `completed` | `completed` | `completed` | **`review_required`** |

Lauf 8 und Lauf 9 bekamen beide mehr Fotos, als die Kette prüfen kann. Der Unterschied: In Lauf 8
hat **Odoo** bei drei abgeschnitten, bevor die Kette überhaupt anfing — das kostete nichts und
endete sauber. In Lauf 9 hat die Kette alle fünf angenommen und ist über der Zeit gestorben.

**Die Obergrenze in Odoo ist damit nicht bloß eine Sparmaßnahme, sondern der Schutz, der den
Konstruktionsfehler aus Abschnitt 4 verdeckt.**

## 7. Was daraus folgt

1. **`QA_MAX_ASSESSMENT_PHOTOS` zurück auf 3.** Die Messung ist gemacht, der Wert gehört wieder
   auf den sicheren Stand.
2. **Die Budgetrechnung gehört korrigiert**, nicht die Fotoanzahl. Zwei Wege, beide belegbar:
   entweder das Knotenlimit über die Summe der Backend-Budgets heben (mindestens 340 s), oder das
   Bildbudget gegen die **verbleibende** Zeit bis zum Knotenlimit rechnen statt gegen einen
   festen Wert. Der zweite Weg ist der ehrlichere: Er lässt die Kette rechtzeitig aufhören und
   ein Teilergebnis melden, statt in den Abbruch zu laufen.
3. **Ein Abbruch verliert alles.** Drei fertige Bildbefunde über 168 s Rechenzeit gingen
   verloren, weil der vierte Aufruf nicht mehr fertig wurde. Ein Zwischenstand, der bei
   Zeitnot das Bisherige meldet, wäre hier 168 s wert gewesen.

## 8. Belege im Ordner

| Datei | Inhalt |
|---|---|
| `run9_brickbow_hellblau.png` | Katalogbild aus Odoo, Vorlage |
| `fotos_original/run9_damage_01.png` bis `_05.png` | von ChatGPT erzeugte Schadensbilder |
| `fotos/qa_photo_01.jpg` bis `_05.jpg` | auf 1 024 px skaliert, Eingabe der Meldung |
| `kontaktabzug.jpg` | alle fünf Ansichten nebeneinander |
| `pruefsummen.txt` | MD5-Summen |
| `logs/` | backend, ollama, n8n, odoo, Containerstände |
