# Testlauf 5 — neues Objekt, freigestelltes Schadensfoto

**Datum:** 15.09.2026
**Auftrag:** L1/OUT/00251, Position 1 von 4
**Artikel:** Brick 2x4 W. Inv. Bows gelb, SKU 6171865, Regal A-01, 2 Stück, ACME Demo GmbH
**Alert:** QA/0369 (Odoo-Datensatz-ID 370)
**Ergebnis:** Kette **vollständig durchlaufen und bewertet** — `ai_evaluation_status = completed`

Erster Lauf, der nicht in `review_required` endet. Zeitangaben aus den Container-Logs, UTC.

## 1. Was dieser Lauf prüft

Lauf 3 hat die Zeitfrage beantwortet (Threadzahl). Offen blieb die Artikelachse: Der
Einbettungsabgleich hatte dreimal in Folge denselben falschen Artikel auf Platz 1 gesetzt. Der
Gegentest in `../2026-09-15_run4_weisser_hintergrund/protokoll.md` zeigte, dass die Ursache der
Hintergrund des generierten Fotos ist und nicht das Verfahren.

Dieser Lauf zieht die Folgerung durch: **neues Objekt, Schadensfoto freigestellt auf weiß**, sonst
unverändert.

## 2. Eingangsdaten

Vorlage: Katalogbild aus Odoo (`product.product`, `default_code = 6171865`, `image_1920`,
2 314 Byte PNG), abgelegt als `run5_brick2x4_bows_gelb_p92.png`. ChatGPT erzeugte daraus ein
Katalogbild desselben Steins mit abgebrochener Noppe und Riss durch die gewölbte Seitenwand —
weißer Grund, diffuses Licht, gleiche Perspektive.

```
Kategorie:    Artikel beschädigt
Priorität:    Normal
Beschreibung: Artikel beschaedigt: Brick 2x4 W. Inv. Bows gelb (SKU 6171865), Regal A-01.
              Noppe abgebrochen, Riss durch die gewoelbte Seitenwand.
              Nicht versandfaehig. Foto angehaengt.
Fotos:        1  (fotos/qa_photo_01.jpg, 1 024 px JPEG)
```

## 3. Vorabmessung am Einbettungsdienst

Vor dem Lauf direkt gegen `POST /abgleich` gemessen, ohne die übrige Kette:

| Eingabe | Urteil | Rangfolge |
|---|---|---|
| Katalogbild 6171865 | `match` | 6171865 **1,0**, 6167549 0,9764, 6380873 0,8642 |
| Schadensfoto weiß | `unsicher` | 6171865 **0,9301**, 6167549 0,9274, 6380873 0,8498 |

Der richtige Artikel steht auf Platz 1. Das Urteil lautet trotzdem `unsicher`, weil der Abstand
zum Zweiten 0,0027 beträgt und damit unter `EINBETT_KNAPP_SCHWELLE = 0.02` liegt.

## 4. Zeitlicher Ablauf

| Zeit (UTC) | Δ zum Start | Ereignis | Quelle |
|---|---|---|---|
| 07:17:58,5 | 0 s | Absenden in der PWA, `POST /api/quality-alerts` → 200 OK | Browser / backend.log |
| 07:18:00,7 | 2,2 s | `POST http://n8n:5678/webhook/quality-assessment-v2` → 200 OK | backend.log |
| 07:18:48,8 | 50,3 s | Textbewertung `qwen2.5:7b` fertig, **47 748 ms**, 821 Prompt-Token, 938 gesamt | ollama.log |
| 07:18:49,5 | 51,0 s | `embed_abgleich`: Urteil **unsicher**, Grund `zu_dicht`, **244 ms** | backend.log |
| 07:18:49,5 | 51,0 s | `article_compare`: „6171865 und 6167549 liegen zu dicht beieinander" | backend.log |
| 07:19:33,9 | 95,4 s | `vision_probe`, **44 436 ms**, `ok: true` (Bilddekodierung 19 378 ms) | backend.log / ollama.log |
| 07:20:25,2 | 146,7 s | `vision_probe`, **51 306 ms**, `ok: true` (Bilddekodierung 3 894 ms) | backend.log / ollama.log |
| 07:20:51,1 | 172,6 s | `vision_probe`, **25 856 ms**, `ok: true` | backend.log |
| 07:21:1x | ≈193 s | `POST /api/internal/n8n/v2/assessments/quality` → 200 OK, danach `/callbacks/status` → 200 OK | backend.log |
| 07:21:13 | 195 s | `ai_last_analyzed_at` in Odoo gesetzt | Odoo-Datensatz |

**Gesamtlaufzeit: 3 min 15 s.** Kein Grenzwert gerissen.

### 4.1 Inferenzzeiten

| Aufruf | Modell | Prompt | Erzeugte Token | Prompt-Durchsatz | Erzeugung | Gesamt |
|---|---|---|---|---|---|---|
| Textbewertung | `qwen2.5:7b` | 821 | 117 | — | — | **47,75 s** |
| Meldefoto beschreiben | `gemma4:12b` | 304 + Bild | 52 | 9,57 tok/s | 4,32 tok/s | **43,79 s** |
| Katalogbild beschreiben | `gemma4:12b` | 439 + Bild | 63 | 13,25 tok/s | 3,75 tok/s | **49,93 s** |
| Schadensprüfung | `gemma4:12b` | 232 | 23 | 12,44 tok/s | 4,52 tok/s | **23,74 s** |
| Artikelvergleich (Text) | `qwen2.5:7b` | 412 | 30 | 23,26 tok/s | 7,72 tok/s | **21,60 s** |

Alle Aufrufe liefen mit `n_threads = 8 (n_threads_batch = 8) / 14`.

## 5. Ergebnis der Systembewertung

```
ai_evaluation_status:  completed
ai_disposition:        scrap
ai_confidence:         1.0
ai_summary:            Noppe abgebrochen und nicht versandfähig.
ai_recommended_action: Ware sperren, aussondern und Schichtleitung informieren.
ai_provider:           ollama-local
ai_model:              qwen2.5:7b
ai_photo_analysis:
  Artikel: nicht geprüft (Bildmodell antwortet nicht).
  Bildabstand: 6171865 und 6167549 liegen zu dicht beieinander (0.0000)
               -- am Bild nicht trennbar.
  Schaden: SICHTBAR -- broken, gouged area on the side.
  Zustand: Abgleich mit dem Katalogbild bestätigt den Befund
           (Es gibt eine gebrochene und ausgeworfene Region auf der Oberfläche.)
```

Die Schadensachse trifft zu: der Bruch an der Seite wird benannt, der Abgleich mit dem Katalogbild
bestätigt ihn, und die Disposition `scrap` entspricht der Meldung.

## 6. Zwei Befunde, die dieser Lauf freilegt

### 6.1 Der Einbettungsabgleich trennt zwei Artikel derselben Formfamilie nicht

Im Lauf selbst lagen die beiden ersten Plätze **exakt gleichauf**:

```json
{"event_type": "embed_abgleich", "urteil": "unsicher", "grund_art": "zu_dicht",
 "erwartet": "6171865",
 "rang": [["6171865", 0.9318], ["6167549", 0.9318], ["6380873", 0.859]],
 "abstand": 0.0}
```

`6167549` ist *Brick 2x3 W. Inv. Bow gelb* — dieselbe Form, dieselbe Farbe, eine Noppenreihe
weniger. DINOv2 ist formdominant, das Farbhistogramm mit einem Viertel Gewicht hilft hier nicht,
weil beide Artikel gelb sind. Der Dienst rät nicht, sondern meldet `unsicher` mit Grund `zu_dicht`
— das ist das im Kopf von `embed/server.py` beschriebene Sollverhalten.

**Das ist kein Fehlurteil mehr, sondern eine offene Auflösungsgrenze**: die Anzahl der Noppen
unterscheidet die beiden Artikel, und diese Zahl steht in keinem der beiden Kanäle.

### 6.2 Eine Meldung im Datensatz widerspricht den Logs

`ai_photo_analysis` beginnt mit „Artikel: nicht geprüft (Bildmodell antwortet nicht)."
Diese Zeile stammt aus `backend/app/routers/n8n_v2.py:600` und wird gesetzt, wenn
`vision.describe(candidate)` mit `ok = False` zurückkommt. In den Logs dieses Laufs stehen aber
**drei** Bildaufrufe, alle mit `ok: true` (44 436 ms, 51 306 ms, 25 856 ms), und die Zeile
„Zustand: Abgleich mit dem Katalogbild bestätigt den Befund" belegt, dass ein Katalogbildvergleich
stattgefunden hat.

`VisionClient.describe` liefert auch dann `ok = False`, wenn der Aufruf zwar antwortet, die
Antwort aber keine verwertbaren Felder enthält (`backend/app/services/vision_client.py:219-234`):
in dem Fall ist die Meldung „Bildmodell antwortet nicht" **sachlich falsch** — das Modell hat
geantwortet, nur unbrauchbar. Welcher der Aufrufe betroffen war, lässt sich aus den Logs nicht
zuordnen, weil der Fall keine eigene Logzeile schreibt.

**Offen:** eine Logzeile für „geantwortet, aber ohne verwertbare Felder", und ein Meldungstext,
der den Unterschied benennt. Ohne beides zeigt der Datensatz einen Ausfall an, wo eine
unbrauchbare Antwort vorliegt.

## 7. Vergleich mit den bisherigen Läufen

| | Lauf 2 | Lauf 3 A | Lauf 3 B | **Lauf 5** |
|---|---|---|---|---|
| Threads | 14 | 14 | 8 | **8** |
| Foto | Lagerfoto | Lagerfoto | Lagerfoto | **freigestellt** |
| Artikelachse | mismatch (falsch) | mismatch (falsch) | mismatch (falsch) | **unsicher, richtiger Artikel Platz 1** |
| Schadensachse | kein Ergebnis | Timeout | erkannt | **erkannt** |
| Endzustand | `assessment unavailable` | `assessment unavailable` | Bewertung, `review_required` | **`completed`** |
| Laufzeit | 4 min 30 s | ≈5 min 6 s | 2 min 23 s | 3 min 15 s |

Lauf 5 dauert länger als Lauf 3 B, weil er **fünf** Modellaufrufe fährt statt drei: der
`unsicher`-Befund des Einbettungsabgleichs löst zusätzlich den bildgestützten Artikelvergleich aus
(Meldefoto beschreiben, Katalogbild beschreiben, Textvergleich). Das sind 115,3 s der 195 s.

## 8. Wo die Zeit hingeht

195 s gesamt, davon 144 s Backend und ollama ab dem ersten Bildaufruf.

| Posten | Zeit | Anteil |
|---|---|---|
| Textbewertung `qwen2.5:7b` | 47,7 s | 24 % |
| Meldefoto beschreiben (ohne verwertbares Ergebnis) | 44,4 s | 23 % |
| Katalogbild beschreiben | 51,3 s | 26 % |
| Schadensprüfung | 25,9 s | 13 % |
| Artikelvergleich im Text | 21,6 s | 11 % |
| Einbettungsabgleich | 0,5 s | 0,3 % |
| Lücke zwischen Freigabe der Position und Medienabruf in Odoo | 22,2 s | 11 % |

Die Grenzwerte blieben unausgeschöpft: `vision_budget_ms` (240 s) zu 51 %, das n8n-Knotenlimit
von 270 s zu 53 %.

### 8.1 Der teuerste Posten liefert nichts

Der 44,4-s-Aufruf beschreibt das Meldefoto für den bildgestützten Artikelvergleich. Er endete mit
`ok: true` auf der HTTP-Ebene, lieferte aber keine verwertbare Beschreibung — sonst stünde in
`ai_photo_analysis` nicht „Artikel: nicht geprüft". 23 % der Verarbeitungszeit ohne Beitrag zum
Urteil.

Dieser Aufruf wird ausgelöst, weil der Einbettungsabgleich `unsicher` meldet. Im selben Log steht
aber der Grund: `zu_dicht`, Abstand 0,0000 zwischen zwei Artikeln derselben Formfamilie. **Wenn
zwei Artikel am Bild nicht trennbar sind, kann auch der bildgestützte Textweg sie nicht trennen**
— er beschreibt beide als „yellow curved brick". Für `grund_art = zu_dicht` direkt auf
`review_required` zu gehen, spart die 44,4 s und die nachfolgenden 21,6 s des Textvergleichs, ohne
Erkenntnis zu verlieren. Für `grund_art = anderer_artikel` bleibt der Textweg sinnvoll, weil dort
die Einbettung eine Aussage trifft, die geprüft gehört.

### 8.2 Bilddekodierung streut um Faktor 5

19 378 ms für das Meldefoto gegen 3 894 ms für das Katalogbild, bei gleicher Zielkantenlänge. Der
Unterschied ist mit dem Bildinhalt allein nicht erklärbar. Zu prüfen bei der nächsten Messung:
`docker stats mobilepickingundvoiceassistant-ollama-1` mitlaufen lassen und Fremdlast auf dem
ollama-Container von der reinen Rechenzeit trennen.

### 8.3 22 Sekunden außerhalb der beobachteten Container

Zwischen der Freigabe der Position (07:18:26,606) und dem Medienabruf in Odoo (07:18:48,838)
liegen 22,2 s, die weder backend noch ollama noch n8n nach stdout protokollieren. Sie fallen in
die n8n-Workflow-Ausführung. Ohne `N8N_LOG_LEVEL=debug` oder die Auswertung des Execution-Logs
ist dieser Anteil nicht aufzuschlüsseln — 11 % der Gesamtkette liegen damit im Dunkeln.

## 9. Belege im Ordner

| Datei | Inhalt |
|---|---|
| `run5_brick2x4_bows_gelb_p92.png` | Katalogbild aus Odoo, Vorlage |
| `fotos_original/run5_damage_01.png` | von ChatGPT erzeugtes Schadensbild, weißer Grund |
| `fotos/qa_photo_01.jpg` | auf 1 024 px skalierte Fassung, Eingabe der Meldung |
| `pruefsummen.txt` | MD5-Summen |
| `logs/` | backend, ollama, n8n, odoo, Containerstände |
