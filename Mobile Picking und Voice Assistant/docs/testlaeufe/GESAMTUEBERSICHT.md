# Qualitätsmeldung mit lokaler Bilderkennung — Gesamtübersicht aller Testläufe

**Stand:** 16.09.2026
**Kette:** Picking-PWA → Backend → n8n „Quality Assessment v2" → ollama (CPU) und
Einbettungsdienst → Odoo Quality Alert
**Zweck dieses Dokuments:** eine Seite, auf der alle Läufe, alle Messwerte und alle offenen
Punkte zusammenstehen. Die Einzelprotokolle in den Unterordnern bleiben die Quelle je Lauf.

Alle Zeitangaben stammen aus Container-Logs, n8n-Executions und Odoo-Datensätzen, nicht aus
Schätzungen. Uhrzeiten in UTC, wie dort protokolliert; die Ortszeit liegt zwei Stunden davor.

---

## 1. Alle Läufe auf einen Blick

| Lauf | Datum | Artikel | Fotos | Hintergrund | Threads | Artikelachse | Endzustand | Dauer |
|---|---|---|---|---|---|---|---|---|
| 1 (QA/0365) | 14.09. | Brick 2x2 hellgelb | 5 | Lager | 14 | `mismatch` (falsch) | `assessment unavailable` | 4 min 31 s |
| 2 (QA/0366) | 14.09. | Brick 1x2x2 weiß | 1 | Lager | 14 | `mismatch` (falsch) | `assessment unavailable` | 4 min 30 s |
| 3 A (QA/0367) | 15.09. | Brick 1x2x2 weiß | 1 | Lager | 14 | `mismatch` (falsch) | `assessment unavailable` | ≈5 min 6 s |
| 3 B (QA/0368) | 15.09. | Brick 1x2x2 weiß | 1 | Lager | **8** | `mismatch` (falsch) | Bewertung da, `review_required` | 2 min 23 s |
| 4 | 15.09. | Brick 1x2x2 weiß | 1 | **weiß** | — | **`match`** | nur Einbettungstest, ohne Kette | — |
| 5 (QA/0369) | 15.09. | Brick 2x4 Bows gelb | 1 | weiß | 8 | `unsicher` | **`completed`** | 3 min 15 s |
| 6 (QA/0370) | 15.09. | Roof Tile 4x2 rot | 2 | weiß | 8 | **`match`** | **`completed`** | 2 min 42 s |
| 7 A (QA/0371) | 15.09. | Brick 2x2 blau | 3 | weiß | 8 | `match` | `assessment unavailable` (Fremdlast) | Abbruch nach 270 s |
| 7 B (QA/0372) | 15.09. | Brick 2x2 blau | 3 | weiß | 8 | **`match`** | **`completed`** | 4 min 17 s |
| 8 (QA/0373) | 15.09. | Plate 2x4 blau | 4 (3 geprüft) | weiß | 8 | **`match`** | **`completed`** | 3 min 10 s |
| 9 (QA/0374) | 15.09. | Brick Bow 2x3x1 hellblau | 5 (3 geprüft) | weiß | 8 | **`match`** | `assessment unavailable` | **Abbruch nach 270 s** |
| 10 (QA/0375) | 15.09. | Brick Bow 2x3x1 hellblau | 5 (3 geprüft) | weiß | 8 | **`match`** | **`completed`** | **3 min 31 s** |
| 11 (QA/0376) | 15.09. | Plate 2x4 grün | 5 (2 geprüft) | weiß | 8 | **`match`** | **`completed`** | **4 min 8 s** |
| 12 (QA/0377) | 15.09. | Brick 2x4 hellgelb | 5 (**4 geprüft**) | weiß | 8 | **`match`** | **`completed`** | **4 min 13 s** |
| 13 (QA/0378) | 15.09. | Brick 2x2 hellblau | 5 (**5 geprüft**) | weiß | 8 | **`match`** | **`completed`** | **4 min 8 s** |
| 14 (QA/0379) | 15.09. | Brick 2x2 hellblau (dieselben Fotos wie 13) | 5 (4 geprüft) | weiß | 8 | **`match`** | **`completed`** | **4 min 4 s** |
| 15 (QA/0380) | 15.09. | Brick 2x2 grün, **sauber fehlende Ecke** | 3 (3 geprüft) | weiß | 8 | `unsicher` | `review_required` (Widerspruch) | **4 min 11 s** |
| 16 (QA/0381) | **16.09.** | Brick 2x2 grün (dieselben Fotos wie 15) | 3 (3 geprüft) | weiß | 8 | `unsicher` | `review_required` (Widerspruch) | **4 min 35 s** |
| 17 (QA/0382) | 16.09. | Brick 2x2 grün (dieselben Fotos wie 15) | 3 (3 geprüft) | weiß | 8 | **`match`** (Foto 2) | `review_required` (Widerspruch) | **4 min 4 s** |
| 18 (QA/0383) | 16.09. | Brick 2x2 grün (dieselben Fotos wie 15) | 3 (3 geprüft) | weiß | 8 | **`match`** (Foto 2) | `review_required` (Widerspruch) | **2 min 52 s** |
| 19 | 16.09. | — | — | — | — | — | Messung ohne Kettenlauf: drei Modellplätze | — |
| 20 (QA/0384) | 16.09. | **Plate 2x4 blau** (dieselben Fotos wie 8) | 3 (3 geprüft) | weiß | 8 | **`match`** | **`completed`**, `scrap` 0.9 | **2 min 31 s** |

Zwei Stellschrauben erklären die ganze Tabelle: **die Threadzahl** entscheidet, ob die Kette
überhaupt fertig wird, und **der Bildhintergrund** entscheidet, ob die Artikelachse trägt.

---

## 2. Befund 1: Die Threadzahl war die Ursache aller Zeitüberschreitungen

### Die Messung

Auf leerem Ollama, `qwen2.5:7b`, 60 Token Ausgabelänge, identischer Prompt, `temperature: 0`:

| Variante | Ladezeit | eval | Durchsatz |
|---|---|---|---|
| Umgebungsvariable `OLLAMA_NUM_THREAD=8`, kalt | 47,4 s | 59,5 s | 1,01 tok/s |
| Umgebungsvariable, warm | 0,2 s | 49,6 s | 1,21 tok/s |
| `options.num_thread: 8` im Request | 23,5 s | 8,1 s | **7,40 tok/s** |

Der ollama-Log belegt die Ursache direkt: die ersten beiden Anfragen starteten mit
`n_threads = 14 (n_threads_batch = 14) / 14`, die dritte mit `n_threads = 8`.

**Die Umgebungsvariable wirkt nicht.** Docker meldet 14 CPUs; der Host ist ein Intel Core Ultra 7
255H mit 6 P-Cores, 8 E-Cores und 2 LP-E-Cores. llama.cpp synchronisiert bei jedem Token, der
schnellste Kern wartet also auf den langsamsten.

### Der Beweis am Gesamtsystem

Lauf 3, zweimal dieselbe Meldung — gleicher Auftrag, gleiche Position, dasselbe Foto (identische
MD5-Summe), gleicher Text, gleiche Priorität. Verändert wurde allein die Threadzahl:

| | Versuch A, 14 Threads | Versuch B, 8 Threads |
|---|---|---|
| Textbewertung `qwen2.5:7b` | Abbruch nach 90 s | **70,95 s, Ergebnis** |
| Bildprüfung `gemma4:12b` | `ReadTimeout` nach 200,0 s | **56,65 s, `ok: true`** |
| Kette gesamt | ≈5 min 6 s | **2 min 23 s** |

### Die Gegenprobe von außen: n8n-Executions

| Execution | Dauer | Lauf |
|---|---|---|
| 136 (10.09.) | 259,8 s | — |
| 137 | **271,2 s** | Lauf 1, 14 Threads |
| 138 | **270,5 s** | Lauf 2, 14 Threads |
| 139 | **271,8 s** | Lauf 3 A, 14 Threads |
| 140 | 141,6 s | Lauf 3 B, 8 Threads |
| 141 | 192,6 s | Lauf 5, 8 Threads |
| 142 | 161,4 s | Lauf 6, 8 Threads |
| 143 | 270 s | Lauf 7 A — Abbruch durch Fremdlast, siehe Abschnitt 7 |
| 144 | ≈257 s | Lauf 7 B, drei Fotos |

Drei Läufe enden auf die Sekunde am Knotenlimit `timeoutMs: 270000`. Das sind keine langsamen
Läufe, das sind abgeschnittene.

### Was daraus geändert wurde

`num_thread` steht jetzt in den `options` jedes Ollama-Requests:
`backend/app/services/vision_client.py`, `llm_client.py`, `voice_intent_classifier.py`. Die
Umgebungsvariable wurde aus dem ollama-Dienst in `docker-compose.yml` entfernt; der Messwert steht
als Kommentar dort, damit niemand sie erneut setzt.

---

## 3. Befund 2: Der Artikelabgleich ist gut, die Fotos waren falsch

In den Läufen 1 bis 3 gewann dreimal derselbe falsche Artikel `301124`. Der Gegentest fragte den
Einbettungsdienst direkt, ohne die übrige Kette, mit demselben Teil in drei Bildwelten:

| Eingabe | Urteil | Platz 1 | Wert des erwarteten Artikels |
|---|---|---|---|
| unverändertes Katalogbild | `match` | 6101121 — **1,0** | Platz 1 |
| Schaden, **weißer** Hintergrund | `match` | 6101121 — **0,8723** | Platz 1 |
| Schaden, Lagerhintergrund | `mismatch` | 301124 — 0,4973 | **0,393, Platz 5** |

Dasselbe Objekt, derselbe Schaden. Nur der Hintergrund entscheidet zwischen Platz 1 mit 0,87 und
Platz 5 mit 0,39. Im Regalfoto brechen **alle** Ähnlichkeitswerte ein — der beste Kandidat kommt
dort nicht über 0,4973.

DINOv2 bettet ein, was im Bild ist: Karton, Regalboden, Streulicht. Diese Anteile haben im Katalog
kein Gegenstück, weil dort jedes Bild freigestellt ist. Verglichen werden dann zwei Bildwelten,
nicht zwei Teile.

### Wie gut die Artikelachse trägt, hängt am Katalog

| Lauf | Artikel | Urteil | Platz 1 | Abstand zu Platz 2 |
|---|---|---|---|---|
| 4 | Brick 1x2x2 weiß | `match` | richtig, 0,8723 | 0,0694 |
| 5 | Brick 2x4 Bows gelb | `unsicher` | richtig, 0,9318 | **0,0000** |
| 6 | Roof Tile 4x2 rot | `match` | richtig, 0,846 | **0,2396** |
| 7 | Brick 2x2 blau | `match` | richtig, 0,8467 | 0,0223 |
| 8 | Plate 2x4 blau | `match` | richtig, **0,8978** | 0,08 |
| 9 | Brick Bow 2x3x1 hellblau | `match` | richtig, **0,9176** | 0,0886 |
| 10 | Brick Bow 2x3x1 hellblau (dieselben Fotos wie 9) | `match` | richtig, **0,9176** | 0,0886 |
| 11 | Plate 2x4 grün | `match` | richtig, **0,8829** | 0,0654 |
| 12 | Brick 2x4 hellgelb | `match` | richtig, 0,8521 | **0,0276** (Geschwister im selben Auftrag) |
| 13 | Brick 2x2 hellblau | `match` | richtig, **0,9139** | 0,0372 |
| 15 | Brick 2x2 grün | **`unsicher`** | richtig, 0,8799 | **0,0155** (`zu_dicht`) |

In Lauf 5 lag *Brick 2x3 W. Inv. Bow gelb* punktgleich daneben: dieselbe Form, dieselbe Farbe,
eine Noppenreihe weniger. Der Dienst rät nicht, sondern meldet `unsicher` mit Grund `zu_dicht`.
Der Dachstein in Lauf 6 hat dagegen eine Silhouette, die im Katalog kein zweites Mal vorkommt.

**Der Hintergrund entscheidet, ob der richtige Artikel vorne landet. Die Formvielfalt des Katalogs
entscheidet, ob der Abstand für ein Urteil reicht.**

---

## 4. Befund 3: Die Fotoanzahl ist nicht der Kostentreiber

| | Lauf 5, **1** Foto | Lauf 6, **2** Fotos |
|---|---|---|
| Artikelachse | `unsicher` | `match` |
| Bildaufrufe | 3 | 3 |
| davon ohne Beitrag zum Urteil | **44,4 s** | 0 s |
| Textaufrufe | 47,7 s + 21,6 s | 24,0 s + 6,1 s |
| Gesamt | 3 min 15 s | **2 min 42 s** |

Der Lauf mit zwei Fotos war 33 s **schneller** als der mit einem. Grund: In Lauf 5 stand der
Einbettungsabgleich auf `unsicher` und löste den bildgestützten Artikelvergleich aus — zwei
Bildaufrufe plus Textvergleich, von denen einer nichts lieferte. In Lauf 6 entschied die
Einbettung in **0,741 s**, und dieser ganze Zweig entfiel.

Die Aufrufe verteilen sich so (`backend/app/routers/n8n_v2.py`):

- `_check_article` sieht **nur das erste Foto** (Zeile 321)
- `_check_damage` geht über **alle** Fotos (Zeile 689) — jedes Foto ein Bildaufruf
- der Zustandsvergleich läuft **einmal je Meldung** gegen das Katalogbild

Das zweite Foto kostete in Lauf 6 also genau einen zusätzlichen Bildaufruf: **52,75 s**.

---

## 5. Zeitgrenzen: die Budgets addieren sich nicht auf das Knotenlimit

| Grenze | Wert | Quelle |
|---|---|---|
| Textbewertung je Aufruf | 90 s | `LLM_TIMEOUT_MS` (Umgebung, überschreibt 30 s in `config.py:117`) |
| Bildaufruf einzeln | 200 s | `config.py:187` |
| Bildbudget für alle Bildaufrufe | 240 s | `config.py:192` |
| Wartezeit auf die Assessment-Sperre | 150 s | `config.py:235` |
| **n8n-Knoten `PWR Signed Assessment`** | **270 s** | `n8n/workflows/quality-assessment-v2.json` |

90 s Text plus 240 s Bild ergeben 330 s. Dazu kommen die Textvergleiche für Artikel und Zustand
mit je bis zu 90 s, die in **keinem** Budget stecken. Das Backend darf also deutlich länger
arbeiten, als der Knoten wartet.

Gemessene Auslastung in Lauf 6: 59 % des Knotenlimits, 54 % des Bildbudgets, 26 % des größten
Einzelaufrufs. Mit vier Fotos blieben vom Bildbudget noch 20–30 s.

**Geändert am 15.09. nach Lauf 9, gegengeprüft in Lauf 10.** Die Einzelbudgets sind unverändert —
sie addieren sich weiterhin auf mehr als das Knotenlimit. Darüber liegt jetzt aber eine zweite
Grenze, die von der Frist des Anrufers her rechnet:

| Neu | Wert | Was sie tut |
|---|---|---|
| `caller_budget_ms` | 255 s | Frist ab Eintreffen der Anfrage im Backend, 15 s unter dem Knotenlimit. Es gilt die frühere aus ihr und dem Bildbudget. |
| `vision_call_estimate_ms` | 60 s | Ein Bildaufruf startet nur, wenn so viel Restzeit bleibt. Die Frage lautet „passt der nächste Aufruf noch", nicht „ist das Budget erschöpft". |

Der garantierte erste Bildaufruf startet weiterhin auch bei knapper Restzeit — eine Bildprüfung,
die stillschweigend gar nichts ansieht, wäre schlimmer —, läuft aber nicht mehr ungefesselt: er
wird gekappt, statt den Anrufer zu überleben.

Welche Seite grundsätzlich verschoben wird — Knotenlimit hoch oder Einzelbudgets runter — bleibt
eine offene Entscheidung. Der Rechenfehler selbst ist behoben.

---

## 6. Modellwahl

| Aufgabe | Modell | Konfigurationsfeld |
|---|---|---|
| Textbewertung der Meldung | `qwen2.5:7b` | `llm_model` (`config.py:116`) |
| Artikelabgleich per Bild | `gemma4:12b` | `vision_article_model` (`config.py:178`) |
| Schadensprüfung | `gemma4:12b` | `vision_model` (`config.py:150`) |
| Sprachbefehl-Klassifikation | `qwen2.5:1.5b` | `llm_voice_model` (`config.py:119`) |
| Artikelabgleich per Einbettung | `facebook/dinov2-base` | Dienst `embed` |

### Kann `gemma4:12b` die Textbewertung übernehmen?

Gemessen mit dem Produktiv-Systemprompt und dem Nutzerprompt aus `llm_client._build_user_prompt`,
`format: json`, `num_thread: 8`, beide Modelle warm:

| Modell | erzeugte Token | Tempo | Ergebnis |
|---|---|---|---|
| `qwen2.5:7b` | **118** | 5,82 tok/s | `scrap`, Konfidenz 0,95, nach 20,3 s fertig |
| `gemma4:12b` | **467, kein Ende** | 3,98 tok/s | nach über vier Minuten abgebrochen |

`gemma4:12b` hält sich bei dieser Aufgabe nicht an das knappe JSON-Schema. Ein Wechsel würde die
Textbewertung nicht billiger machen, sondern um Faktor 5 teurer. **`qwen2.5:7b` bleibt.** Wer es
weiterverfolgen will, müsste `num_predict` setzen und den Prompt kürzen — das wäre eine
Prompt-Änderung, keine Modellumstellung.

---

## 7. Lauf 7 — drei Fotos, und wo die Grenze liegt

Drei Fotos kosten **vier** Bildaufrufe: je Foto eine Schadensprüfung plus einmal das Katalogbild
für den Zustandsvergleich.

| | Lauf 5, **1** Foto | Lauf 6, **2** Fotos | **Lauf 7 B, 3 Fotos** |
|---|---|---|---|
| Bildaufrufe | 3 | 3 | **4** |
| Bildzeit gesamt | 121,6 s | 129,3 s | **169,9 s** |
| Gesamtlaufzeit | 3 min 15 s | 2 min 42 s | **4 min 17 s** |
| Auslastung Bildbudget (240 s) | 51 % | 54 % | **72 %** |
| Auslastung n8n-Knoten (270 s) | 71 % | 59 % | **94 %** |

Einzelzeiten in Lauf 7 B: Foto 1 46,55 s, Foto 2 49,28 s, Foto 3 48,38 s, Katalogbild 25,65 s.
Textbewertung 59,41 s, abschließender Artikelvergleich 20,43 s.

### Lauf 8 mit vier Fotos: die Grenze liegt woanders

Erwartet war ein Abbruch. Eingetreten ist: **3 min 10 s, `completed`, ein Foto ungeprüft.**
Im Formular steht `Fotos: 1 weitere ungeprüft.` Die Ursache steht in
`odoo/addons/quality_alert_custom/models/quality_alert.py:237`:

```python
_MAX_ASSESSMENT_PHOTOS = 3
```

`api_get_assessment_media` übergibt höchstens drei Anhänge an die Kette, zählt aber alle
(`photo_total`). **Die Fotoanzahl war also längst gedeckelt, bevor ich sie gemessen habe.** Die
Schlussfolgerung aus Lauf 7 — drei Fotos sind das Maximum — war im Ergebnis richtig, in der
Begründung falsch: Es deckelt diese Konstante, nicht das Zeitbudget. Vier Fotos können die Kette
gar nicht überlasten.

| | 1 Foto | 2 Fotos | 3 Fotos | 4 Fotos |
|---|---|---|---|---|
| übergeben | 1 | 2 | 3 | **3 von 4** |
| Bildaufrufe | 3 | 3 | 4 | 4 |
| Bildzeit | 121,6 s | 129,3 s | 169,9 s | 156,5 s |
| Gesamt | 3 min 15 s | 2 min 42 s | 4 min 17 s | 3 min 10 s |
| Knotenlimit-Auslastung | 71 % | 59 % | 94 % | 70 % |

Lauf 8 war mit einem Foto mehr **schneller** als Lauf 7: Die Streuung zwischen zwei Läufen
(Textbewertung 25,1 s gegen 59,4 s) ist größer als der Unterschied zwischen drei und vier Fotos.

### Lauf 9 mit fünf Fotos: die Budgetbremse greift nicht

Für diese Messung wurde `QA_MAX_ASSESSMENT_PHOTOS` auf 5 gesetzt — zum ersten Mal gingen mehr als
drei Fotos in die Kette. Ergebnis: **Abbruch am Knotenlimit nach 270 s**, `assessment unavailable`.
Drei der fünf Fotos waren geprüft (59,8 s + 50,1 s + 58,1 s = 168,0 s), Foto 4, Foto 5 und der
Katalogbildvergleich kamen nicht mehr dran.

**Der Befund ist nicht der Abbruch, sondern warum die Bremse ihn nicht verhindert hat.** Zum
Zeitpunkt des Abbruchs waren 168 s von 240 s Bildbudget verbraucht — 70 %. `_check_damage` hatte
also keinen Grund, ein Foto zu überspringen, und hätte weitergeprüft. Der Aufrufer hatte da schon
aufgegeben.

| Posten | Grenze |
|---|---|
| Textbewertung | 90 s |
| Bildbudget | 240 s |
| zwei Textvergleiche | je bis 90 s |
| **Summe möglich** | **bis 510 s** |
| **n8n-Knoten wartet** | **270 s** |

Das Backend misst gegen 240 s statt gegen die verbleibende Zeit bis 270 s. Die Odoo-Konstante
`_MAX_ASSESSMENT_PHOTOS = 3` ist derzeit das Einzige, was diesen Rechenfehler verdeckt — sie ist
kein Sparmaßnahme, sondern Schutz.

Lauf 8 und Lauf 9 bekamen beide mehr Fotos, als die Kette prüfen kann. In Lauf 8 schnitt **Odoo**
vorher ab: kostete nichts, endete sauber. In Lauf 9 nahm die Kette alle fünf an und starb über der
Zeit — 168 s Rechenzeit und drei fertige Bildbefunde gingen dabei verloren.

**Die bindende Grenze ist das Knotenlimit, nicht das Bildbudget.** Webhook bis Antwort:
254,5 s von 270 s, **Reserve 15,5 s**. Das Bildbudget hat dagegen noch 66,7 s frei (173,3 s von
240 s verbraucht). Grund: Die beiden Textaufrufe kosten zusammen 79,9 s, zählen gegen das
Knotenlimit, stecken aber in keinem Budget. Ein viertes Foto — rund 48 s — würde das Bildbudget
aushalten, das Knotenlimit aber um gut 30 s reißen. Damit ist die Obergrenze gemessen statt geschätzt: **drei Fotos je Meldung sind
das Maximum, das die Kette in dieser Konfiguration trägt.** Die Hochrechnung aus Lauf 6 („bei
vier Fotos noch 20-30 s Reserve") war zu optimistisch; sie hatte den Zustandsvergleich mit 33 s
angesetzt statt der hier gemessenen 25,7 s und die Fotos mit 40 s statt 48 s.

### Lauf 10: dieselben fünf Fotos, diesmal mit Budgetbremse

Gegenprobe zu Lauf 9 mit **denselben Bilddateien** (MD5 gleich, nur neue Namen wegen des
Idempotenzschlüssels), demselben Auftrag und derselben Position. Einzige Änderung: die zwei neuen
Grenzen aus Abschnitt 5.

| | Lauf 9 | Lauf 10 |
|---|---|---|
| Artikelabgleich | `match`, 0,9176 | `match`, 0,9176 |
| Textbewertung | 51,14 s | 54,16 s |
| Fotos geprüft | 3 (+ Foto 4 angefangen und verloren) | 3 (Foto 4 und 5 gar nicht erst gestartet) |
| Bildaufrufe | 59,8 / 50,1 / 58,1 s | 47,1 / 42,5 / 42,2 s |
| Laufzeit bis Antwort | **Abbruch bei 270,1 s** | **210,9 s** |
| verlorene Rechenzeit | 65,6 s | 0 s |
| Odoo | `assessment unavailable` | `completed`, `scrap`, Konfidenz 0,95 |

Foto 4 startete nicht, weil bei 210,9 s noch rund 48 s bis zur Anruferfrist blieben — weniger als
die veranschlagten 60 s je Aufruf. Dieselbe Prüfung hielt den Katalogbildvergleich zurück. Beides
steht im Klartext im Alert: `Zustand: nicht verglichen (Zeitbudget erschöpft).` und
`Fotos: 2 weitere ungeprüft.` Im ollama-Log steht **kein** `cancel task` — in Lauf 9 stand dort
`id_task=198` und 65,6 s Rechenzeit ohne Ergebnis.

**Was der Lauf nicht zeigt:** dass fünf Fotos jetzt durchlaufen. Sie laufen nicht durch — die
Kette trägt weiterhin drei. Der Unterschied ist, dass sie das jetzt sagt, statt daran zu sterben.

Nebenbefund: Die Bildaufrufe lagen mit 40,2–46,2 s (ollama) am unteren Rand des Bandes 42–60 s.
Der Schätzwert 60 s ist also konservativ — er lässt eher ein Foto liegen, als eine Antwort zu
verlieren. Ein gleitender Mittelwert der letzten Aufrufe wäre genauer.

### Läufe 12 und 13: der gleitende Schätzwert

Nach Lauf 11 stand fest, dass ein fester Wert das Band 42–83 s nicht abdecken kann. Seit dem
15.09. hält `vision_client` die Dauer der letzten **acht** Schadensaufrufe je Modell fest und
liefert daraus den **80-%-Wert**; vor drei Messungen gilt weiter `vision_call_estimate_ms`.
Warum nicht der Mittelwert: die Hälfte aller Aufrufe würde ihn reißen. Warum nicht der
Höchstwert: nach Lauf 11 stünde die Schätzung acht Aufrufe lang auf 83 s.

Dazu die Logzeile `vision_budget_stop` mit `stelle`, `restzeit_s`, `schaetzung_s` und
`offene_fotos` — vorher stand über ein zurückgestelltes Foto **nichts** im Backend-Log.

| | Lauf 11 | Lauf 12 | Lauf 13 |
|---|---|---|---|
| Schätzwert | fest 60 s | gleitend ab Foto 3 | gleitend von Anfang an |
| **Fotos geprüft** | 2 von 5 | 4 von 5 | **5 von 5** |
| Bildaufrufe | 82,9 / 59,1 s | 49,0 / 42,4 / 56,1 / 49,9 s | 45,8 / 37,5 / 39,6 / 42,3 / 40,6 s |
| Laufzeit | 247,9 s | 252,5 s | 248,3 s |
| Auslastung Knotenlimit | 92 % | 94 % | 92 % |

**Bei praktisch gleicher Laufzeit steigt die Zahl der geprüften Fotos von zwei auf fünf.** Der
Gewinn kommt nicht aus mehr Rechenleistung, sondern aus einer Schätzung, die dem tatsächlichen
Verhalten folgt. In Lauf 12 sank sie nach drei Messungen auf 56,1 s und ließ damit Foto 4 zu, das
gegen die 60-s-Vorgabe liegengeblieben wäre. In Lauf 13 fiel sie nach einem Aufruf von 37,48 s —
dem schnellsten aller Läufe — auf 49,9 s und ließ Foto 5 zu.

Der Artikel entscheidet mit: ein 2x2-Stein kostet 37–46 s je Aufruf, eine 2x4-Platte 42–83 s. Ein
fester Wert kann das grundsätzlich nicht abbilden.

### Lauf 14: der Zustandsvergleich war gar nicht das Zeitproblem

Dass der Zustandsvergleich seit Lauf 9 nie mehr drankam, sah nach einem Zeitproblem aus. Es war
eins der Reihenfolge — und darunter ein Denkfehler: **der Vergleich darf nur eskalieren**
(`intact` auf `damaged`, nie zurück, seit QA/0223). Steht `damaged` schon fest, kann er am Urteil
nichts mehr ändern und liefert bestenfalls einen Satz über sich selbst. In den Läufen 9 bis 13
hätte er also in keinem einzigen Fall etwas entschieden, hätte aber jedes Mal den letzten
Bildaufruf gekostet.

Seit dem 15.09. läuft er nur noch bei `intact`, also dort, wo er als Einziger ein sauber
abgebrochenes Eck findet — dort ist auch Zeit für ihn. Bei `damaged` steht der Grund im Log
(`condition_compare_skipped`), nicht im Odoo-Formular: dass die Kette einen Vergleich nicht
brauchte, ist keine Aussage über die Ware.

Lauf 14 belegt es an denselben fünf Fotos wie Lauf 13: die Zeile „Zustand: nicht verglichen
(Zeitbudget erschöpft)" ist verschwunden, und `gouged stud` heißt jetzt `ausgekerbte Noppe`.

Nebenbei vermessen: Lauf 14 prüfte vier statt fünf Fotos, weil das Backend für den neuen Code neu
gestartet war und die Messreihe leer begann. **Eine leere Messreihe kostet genau ein Foto in der
ersten Meldung nach einem Neustart** — mehr nicht.

### Lauf 15: die Grenze des Verfahrens ist nicht die Zeit, sondern das Sehen

Der Lauf konstruiert den Fall, für den der Zustandsvergleich gebaut ist: einem grünen 2x2-Stein
fehlt **eine Ecke vollständig**, die Bruchfläche ist glatt wie geschnitten, kein Riss, keine
ausgefranste Kante. Drei Fotos, `QA_MAX_ASSESSMENT_PHOTOS = 3` wie im Betrieb.

Der Vergleich **lief zum ersten Mal seit Lauf 8** vollständig durch — Bildaufruf für das
Katalogbild (252 Token, 21,2 s) plus Textvergleich (19,3 s). Und fand nichts:

```json
{"event_type": "condition_compare", "new_damage": false, "damage": "intact",
 "reason": "Die Beschreibungen stimmen überein und deuten auf einen Neuzustand hin."}
```

Beide Bildstufen haben den Schaden übersehen. Die Ursache steht im Prompt: `surface_description`
fragt ausschließlich nach der **Oberfläche**, und eine sauber fehlende Ecke lässt jede Oberfläche
glatt. Soll und Ist sagen beide „glatt", der Textvergleich findet keinen Unterschied.

**Der naheliegende Fix trägt nicht.** Mit `bench_umriss.py` gemessen, derselbe Prompt plus ein
Feld `outline_description`: Auf beiden Lauf-15-Fotos antwortet das Modell *„The body is complete
with all corners and edges present"* — es behauptet die Vollständigkeit eines Steins, dem sichtbar
eine Ecke fehlt. Auf den beschädigten Teilen aus den Läufen 12 und 13 bleibt `damaged` korrekt
true, aber jeder Aufruf kostet 46–55 s statt 8–41 s. Kosten ohne Nutzen, nicht eingebaut.

**Damit ist die Grenze benannt und belegt: Die Kette erkennt Oberflächenschäden, keine fehlende
Geometrie.** Für die Arbeit ist das eine Eigenschaft des Verfahrens, kein offener Fehler.

**Die Kette selbst hat richtig entschieden.** Texturteil `scrap` gegen Bildbefund „keine
Auffälligkeit" — der Widerspruchszweig machte daraus `review_required` mit beiden Seiten im
Klartext, statt eine der Halbwahrheiten wirksam zu machen. Zum ersten Mal greift dieser Zweig an
einem echten Fall.

Nebenbefund: Der Artikelabgleich meldete `unsicher` (`zu_dicht`, Abstand 0,0155) und löste den
Textweg aus — 72,3 s, 29 % der Laufzeit. Ironischerweise hat genau dieser Umweg den Lauf
gerettet: ohne ihn wäre die Zeit früher verbraucht gewesen.

Offen bleibt die Frage nach einem **anderen Bildmodell** auf dieser Achse. Die Messung vom 14.08.
(`gemma4:12b` 4/4 gegen `qwen2.5vl:7b` 2/4) lief über acht Bilder, die alle Oberflächenschäden
zeigten. Für fehlende Geometrie liegt keine Modellmessung vor.

### Lauf 11: der Schätzwert war zu niedrig, und es hat trotzdem gehalten

Neuer Artikel (Plate 2x4 grün, in keinem Vorlauf), fünf Fotos, Antwort nach **247,9 s** mit
`completed`. Zwei Stufen liefen aus dem Rahmen: die Textbewertung brauchte **74,94 s** statt der
51–54 s der Vorläufe, und **Foto 1 brauchte 82,88 s** — bei 519 Token gegen 513 Token bei Foto 2,
das 59,11 s brauchte. Fast gleiche Tokenzahl, 26 s Unterschied: **das Bildmodell schwankt auch in
der Dauer**, nicht nur im Wortlaut.

Damit ist `vision_call_estimate_ms = 60 s` gemessen zu niedrig; das Band der Bildaufrufe ist nach
elf Läufen **42–83 s**. Gehalten hat der Lauf trotzdem, weil zwei Schranken hintereinander greifen:

* Der Schätzwert entscheidet, ob ein Aufruf **startet** — er verhindert verlorene Rechenzeit.
* `_in_restzeit` kappt einen laufenden Aufruf an der Frist — es verhindert verlorene **Ergebnisse**.

Foto 2 startete mit rund 75 s Restzeit und kam mit 13 s Reserve durch. Hätte es wie Foto 1
gedauert, wäre es gekappt worden und der fertige Befund von Foto 1 trotzdem in Odoo gelandet.

**Ohne den Fix wäre Lauf 11 ein zweiter Lauf 9 geworden:** Vom alten Bildbudget (240 s ab
≈12:55:10) waren nach Foto 2 erst 149 s verbraucht, die alte Prüfung hätte Foto 3 gestartet, und
der Knoten hätte um ≈12:58:07 mitten hinein abgebrochen — beide fertigen Befunde verloren.

Artikelachse: `match`, 0,8829, Abstand 0,0654. Auf Platz 3 landete ein Teil **derselben Farbe**
aus demselben Auftrag (Brick 2x2 grün, 0,8083) — die Farbe zieht die Kandidaten zusammen, die Form
trennt sie wieder.

### Erster Versuch: was Fremdlast anrichtet

Lauf 7 A (QA/0371) endete nach exakt 270 s mit `assessment unavailable` — nicht wegen der drei
Fotos. Eine abgebrochene Modellmessung lief in ollama weiter: **das Abbrechen des Clients beendet
die Generierung nicht.** Der Auftrag stand bei 1 718 erzeugten Token und belegte acht Kerne.

| Zeit (UTC) | Ereignis |
|---|---|
| 08:06:00 | `llm_quality_disposition_failed` — Textbewertung reißt ihr 90-s-Limit, weil `qwen2.5:7b` verdrängt war und neu laden musste |
| 08:06:27 | `embed_katalog`: 47 Artikel neu eingebettet, **25 859 ms** (Cache nach Backend-Neustart leer) |
| 08:09:00 | n8n-Knoten bricht nach 270 s ab |

Das ist zugleich der Beleg dafür, wie empfindlich die Kette auf Nebenlast reagiert: Ein einziger
fremder Generierungslauf genügt, um eine Bewertung zu kippen, die sonst in 257 s durchläuft.

---

## 8. Was an der Kette geändert wurde

| Datei | Änderung | Beleg |
|---|---|---|
| `backend/app/services/vision_client.py` | `num_thread` in den `options` | Abschnitt 2 |
| `backend/app/services/llm_client.py` | dito, drei Aufrufstellen | Abschnitt 2 |
| `backend/app/services/voice_intent_classifier.py` | dito | Abschnitt 2 |
| `docker-compose.yml` | `OLLAMA_NUM_THREAD` entfernt, Messwert als Kommentar | Abschnitt 2 |
| `backend/app/routers/n8n_v2.py` | `_schadensworte`: Dopplungen raus, Begriffe auf Deutsch | Abschnitt 9 |

---

## 9. Klartext im Odoo-Formular

Vor der Änderung stand in `ai_photo_analysis` von QA/0370:

```
Schaden: SICHTBAR -- crack, broken edge, crack, split.
```

Zwei Mängel: Die Befunde aller Fotos werden aneinandergehängt, ohne Dopplungen zu entfernen —
zwei Fotos desselben Risses liefern denselben Begriff zweimal. Und die Begriffe bleiben englisch,
wie das Bildmodell sie liefert.

`_schadensworte` entfernt Dopplungen (Reihenfolge bleibt, Groß- und Kleinschreibung sowie
Satzzeichen zählen nicht) und übersetzt die häufigen Begriffe. Unbekanntes bleibt wörtlich stehen
— ein falsch geratenes deutsches Wort wäre schlimmer als ein englisches, das man nachschlagen
kann. Aus dem Beispiel oben wird:

```
Schaden: SICHTBAR -- Riss, gebrochene Kante, Bruch.
```

Der Selbsttest dazu liegt bei den Skripten und deckt den Originalbefund aus QA/0370, Dopplungen
mit abweichender Schreibung, unbekannte Begriffe und leere Eingaben ab.

Am lebenden System bestätigt, QA/0372 mit **drei** Fotos desselben Schadens:

```
Schaden: SICHTBAR -- Riss, broken piece, aufgerissene Stelle.
```

Drei Begriffe statt neun. `broken piece` steht nicht im Glossar und bleibt wörtlich stehen.

**Grenze des Glossars, sichtbar in Lauf 8:** `gemma4:12b` lieferte dort ganze Sätze als
Einzelbefunde (`crack running through the middle`, `broken piece missing from front left corner`,
…). Die Entdopplung griff, aber ein Satz steht in keinem Glossar und bleibt wörtlich stehen — fünf
englische Sätze im Formular. Offen: entweder `DAMAGE_PROMPT` in `vision_client.py` verlangt
ausdrücklich Ein- bis Zweiwortbefunde statt „array of short strings", oder `_schadensworte` kürzt
zu lange Einträge. Die erste Variante ändert, was das Modell liefert, statt nachträglich zu raten.

---

## 10. Offene Punkte

1. ~~**Budgetrechnung gegen Knotenlimit**~~ — **behoben am 15.09., gegengeprüft in Lauf 10.**
   `caller_budget_ms` (255 s) und `vision_call_estimate_ms` (60 s), Details in Abschnitt 5.
   Offen bleibt daran zweierlei: der Schätzwert je Bildaufruf ist fest verdrahtet statt gemessen
   (ein gleitender Mittelwert wäre genauer), und das Backend schreibt **keine Logzeile**, wenn es
   ein Foto zurückstellt — die Zahl steht nur im Alert. Ob stattdessen das Knotenlimit steigen
   oder die Einzelbudgets sinken sollen, ist weiterhin eine Entscheidung, keine Reparatur.
2. **Irreführende Meldung „Bildmodell antwortet nicht".** In Lauf 5 stand sie im Datensatz,
   obwohl drei Bildaufrufe mit `ok: true` protokolliert sind. `VisionClient.describe` liefert auch
   dann `ok = False`, wenn das Modell antwortet, die Antwort aber keine verwertbaren Felder
   enthält (`vision_client.py:219-234`). Der Fall schreibt keine eigene Logzeile, deshalb ist er
   im Nachhinein keinem Aufruf zuzuordnen. Nötig: eine Logzeile und ein Text, der den Unterschied
   benennt.
3. **`gemma4:12b` lädt nicht zuverlässig.** Am 15.09. dreimal gescheitert, einmal mit
   `llama-server process has terminated: signal: killed` und anschließendem Nil-Pointer-Absturz im
   Scheduler. `docker stats` zeigte dabei rund 25,3 GiB frei, `OOMKilled = false`, kein
   Speicherlimit am Container — die Ursache ist **nicht** geklärt. Zweimal lud dasselbe Modell am
   selben Tag in 87 s und 93 s.
4. ~~**Soll-Befund-Cache überlebt keinen Neustart.**~~ — **behoben am 16.09., belegt in Lauf 18.**
   `_SOLL_BEFUNDE` liegt jetzt zusätzlich als Datei im Volume `backend_cache`
   (`SOLL_BEFUND_CACHE`, Vorgabe `/var/cache/pwr/soll_befunde.json`). Nach dem Neustart meldete
   Lauf 18 `soll_cache_geladen` mit einem Eintrag, und der Zustandsvergleich kostete **3,9 s statt
   22,2 s** — der Katalogbildaufruf entfiel ganz. Nicht über einen Warmlauf aller Artikel gelöst:
   44 Artikel mal rund 22 s wären gut 16 Minuten Startzeit.
5. ~~Fotoanzahl deckeln~~ — **erledigt, war bereits umgesetzt.** `_MAX_ASSESSMENT_PHOTOS = 3`
   in `odoo/addons/quality_alert_custom/models/quality_alert.py:237`. In Lauf 8 mit vier Fotos
   belegt: drei geprüft, `Fotos: 1 weitere ungeprüft.` im Formular.
6. **Verwaiste Arbeit abbrechen.** In Lauf 7 A gab der n8n-Knoten um 08:09:00 auf, das Backend
   rechnete aber bis 08:09:40 weiter — 40 s auf einer ohnehin knappen CPU, deren Ergebnis niemand
   mehr abholt. Ein `request.is_disconnected()` vor jedem teuren Bildaufruf würde das beenden.
7. **Katalog-Einbettung aus dem Zeitfenster nehmen.** In Lauf 7 A kostete `embed_katalog`
   **25 859 ms**, weil der Cache nach einem Backend-Neustart leer war — diese Zeit geht direkt vom
   Bildbudget ab. In Lauf 7 B war der Katalog warm und kostete nichts. Ein periodischer Aufbau im
   Hintergrund statt im Request gibt bei jedem kalten Start rund 26 s zurück.
8. **Freistellen vor dem Abgleich.** Solange Meldefotos im Lager entstehen, trägt die Artikelachse
   nicht (Abschnitt 3). Ein Segmentierungsschritt vor der Einbettung wäre der kleinere Eingriff
   als ein zweiter Katalog mit Lageraufnahmen.
9. ~~**Kaltstart geht vom Zeitbudget der ersten Meldung ab.**~~ — **behoben am 16.09., belegt in
   Lauf 16.** `MODEL_WARMUP` wärmt Text- und Bildmodell beim Backend-Start vor
   (`main.py`, `LlmClient.warmup`, `VisionClient.warmup`). Vorher tat das nur das Testskript
   `warmlaufen.py`, das von Hand in den Container gelegt werden muss — in einer Vorführung also
   nie. Messwert: 3 min 11 s Startzeit, danach lief die Kette mit drei von drei Fotos **und**
   Zustandsvergleich durch.
10. **Das Sprach-Vorwärmen wärmt nichts.** `llm_voice_timeout_ms = 4000` reicht nicht, um ein
   Modell von der Platte zu laden; auf kaltem ollama endet der Aufruf in Lauf 16 nach rund 11 s
   mit `{"event_type": "voice_intent_llm_failed", "error": ""}`. Best-effort, blockiert nichts,
   nützt aber auch nichts. Entweder eigenes, längeres Zeitlimit für den Warmlauf oder den Zweig
   streichen.
11. ~~**Das Sprach-Vorwärmen verdrängt das Bildmodell.**~~ — **behoben am 16.09., gemessen in
   Lauf 19.** Seit der Warmlauf eine eigene Frist hat (Lauf 17), lädt er das Sprachmodell
   wirklich — und bei zwei Plätzen flog dafür `gemma4:12b` heraus, Nachladen 121 s. Gemessen mit
   den Produktiv-Kontextgrößen: drei Modelle belegen **15,62 GiB von 25,44 GiB (61 %)**, der OOM
   vom 14.08. lag bei 20,5 GB Modellgewicht gegen 15,4 GB hier. `OLLAMA_MAX_LOADED_MODELS` steht
   jetzt auf **3**; der Bild-Warmlauf nach einem Neustart kostet damit **7,76 s statt 88,8 s**.
   Die Zahl gilt für genau diese drei Modelle — ein weiteres 7B verlangt eine neue Messung.
12. **Der runde Stein ist nicht gemessen.** Für Lauf 20 war `Brick Round 2x2x2 weiß`
   (SKU 6096680, L1/OUT/00239 Position 3) vorgesehen — eine Formfamilie, die in keinem Lauf
   vorkommt. ChatGPT blockte die Bilderzeugung mit `You've hit your rate limit.`, deshalb lief
   Lauf 20 mit den Fotos aus Lauf 8. Katalogbild und Auftragsdaten liegen unter
   `2026-09-16_run20_brickround_weiss/`; es fehlen nur drei Schadensfotos.
13. **Für fehlende Geometrie gibt es weiterhin keinen Modellvergleich.** Offen aus Lauf 15:
   `gemma4:12b` sieht ein sauber fehlendes Eck nicht. `bench_vision_models.py` auf den
   Lauf-15-Fotos gegen `qwen2.5vl:7b` wäre die letzte offene Zahl — ohne Kettenlauf.

---

## 11. Stolperfallen der Umgebung

Alle sechs im Skill `.claude/skills/qa-testlauf/SKILL.md` festgehalten, damit sie nicht erneut
Zeit kosten:

1. Der Stack mountete den Backend-Code aus einem Worktree — Änderungen im Projektverzeichnis
   erreichten den Container nie. Vor jeder Messung `docker inspect` auf die Mounts.
2. Die Threadzahl gehört gegengeprüft: `n_threads = 8` im ollama-Log, nicht nur in der Konfiguration.
3. Modelle vor dem Lauf warmlaufen lassen, **mit der Produktiv-Kontextgröße** — sonst lädt ollama
   beim ersten echten Aufruf neu. Seit dem 16.09. erledigt `MODEL_WARMUP` das beim Backend-Start
   selbst; `warmlaufen.py` braucht nur noch, wer ohne Backend misst.
4. Ein neuer Browser-Tab hat keinen CSRF-Token; die PWA meldet das irreführend als
   „Profil bitte neu wählen".
5. Zwei große Modelle gleichzeitig: siehe offener Punkt 3.
6. Der Idempotenzschlüssel verhindert Wiederholungen mit identischer Eingabe — dieselbe Datei
   unter anderem Namen hochladen und die MD5-Gleichheit protokollieren.
7. Ein abgebrochener Client beendet keine laufende Generierung in ollama. Vor jeder Messung
   `docker stats mobilepickingundvoiceassistant-ollama-1` prüfen: steht die CPU über 100 %, läuft
   noch etwas. Aufräumen nur über `docker restart` des Containers.

---

## 12. Einzelprotokolle

| Lauf | Ordner |
|---|---|
| 1 | `2026-09-14_QA0365/protokoll.md` |
| 2 | `2026-09-14_run2_brick1x2x2_weiss/` (ohne Protokoll) |
| 3 A und B | `2026-09-15_run3_brick1x2x2_weiss/protokoll.md` |
| 4 | `2026-09-15_run4_weisser_hintergrund/protokoll.md` |
| 5 | `2026-09-15_run5_brick2x4bows_gelb/protokoll.md` |
| 6 | `2026-09-15_run6_rooftile_rot/protokoll.md` |
| 7 A und B | `2026-09-15_run7_brick2x2_blau/protokoll.md` |
| 8 | `2026-09-15_run8_plate2x4_blau/protokoll.md` |
| 9 | `2026-09-15_run9_brickbow_hellblau/protokoll.md` |
| 10 | `2026-09-15_run10_budgetbremse/protokoll.md` |
| 11 | `2026-09-15_run11_plate2x4_gruen/protokoll.md` |
| 12 | `2026-09-15_run12_brick2x4_hellgelb/protokoll.md` |
| 13 | `2026-09-15_run13_brick2x2_hellblau/protokoll.md` |
| 14 | `2026-09-15_run14_zustandsvergleich/protokoll.md` |
| 15 | `2026-09-15_run15_sauberer_bruch/protokoll.md` |
| 16 | `2026-09-16_run16_kaltstart_vorwaermen/protokoll.md` |
| 17 | `2026-09-16_run17_artikelsuche/protokoll.md` |
| 18 | `2026-09-16_run18_sollbefund_cache/protokoll.md` |
| 19 | `2026-09-16_run19_drei_modellplaetze/protokoll.md` (Messung ohne Kettenlauf) |
| 20 | `2026-09-16_run20_plate2x4_blau/protokoll.md` |
