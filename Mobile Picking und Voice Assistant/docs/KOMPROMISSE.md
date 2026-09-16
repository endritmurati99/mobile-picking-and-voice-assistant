# Bezahlte Entscheidungen der Qualitätsbewertungs-Kette

**Zweck:** Jede Zeile hier ist eine Entscheidung, die schon einmal Messzeit gekostet hat. Wer an
der Kette etwas ändert, liest diese Seite vorher — sonst dreht er einen Kompromiss zurück, dessen
Preis bereits bezahlt wurde.

**Stand:** 15.09.2026. Die Belege stehen in den Codekommentaren und in `docs/testlaeufe/`.

---

## 1. Wie diese Seite zu lesen ist

Ein Kompromiss steht hier nur, wenn drei Dinge feststehen: **was** entschieden wurde, **welche
Messung** sie begründet, und **was passiert**, wenn man sie zurückdreht. Fehlt der Messwert, ist
es keine Entscheidung, sondern eine Annahme — die gehört in Abschnitt 4.

---

## 2. Die Entscheidungen

### Bildaufbereitung

| Entscheidung | Wo | Messwert | Beim Zurückdrehen |
|---|---|---|---|
| `DAMAGE_MAX_EDGE = 1024` statt 512 | `backend/app/services/assessment_media.py:56` | Bei 512 px verschwanden 2 von 3 Rissen; bei 768 px wurde eine Kerbe als „DESIGN" gelesen, bei 1024 px als „INDENTATION" | Echte Risse werden wieder als Dekor gelesen, `damaged: false` |
| Artikelabgleich bleibt bei 512 px | `assessment_media.py:42-45` | Zwei Bilder in einem Fenster stoßen bei 1024 px an die Kachelgrenze des Modells | HTTP 400 durch Kachelüberlauf |

### Prompts

| Entscheidung | Wo | Messwert | Beim Zurückdrehen |
|---|---|---|---|
| JSON-Schlüsselreihenfolge normativ: erst beschreiben, dann urteilen | `vision_client.py:10-13`, `llm_client.py:53-60` | Bei umgekehrter Reihenfolge antwortete das Modell „aus dem Schema statt aus dem Bild", Konfidenz 0,95 bei Fehlurteil | Urteile ohne Bildgrundlage, hohe Konfidenz |
| Satz über „ragged, torn or gouged" im Schadensprompt | `vision_client.py:92-95` | Ohne ihn 0 von 4 Prüfbildern getroffen, mit ihm 3 von 4, kein Fehlalarm auf heilen Teilen | Schadenserkennung bricht zusammen |
| `anomalies`: ein bis drei Wörter je Befund | `vision_client.py:85-88` | 15.09.2026, fünf Fotos: vorher längster Befund 8 Wörter, Schnitt 2,6, zwei über drei Wörtern; nachher längster 2 Wörter, Schnitt 1,4, keiner über drei. `damaged` blieb 5× true | Ganze Sätze im Odoo-Formular, Glossar greift nicht mehr |
| Schweregrad-Prompt mit `belegstelle`/`grundlage` | `llm_client.py:42-73` | 21 Meldetexte: alter Prompt 11/21 richtig (3× falsches `scrap`), neuer 19/21 (1×). Median 10 s → 15 s | Vorschnelles `scrap` vernichtet verkäufliche Ware |
| Im Zweifel „dasselbe Teil" statt `mismatch` | `llm_client.py:134-146` | QA/0227: falsches `mismatch` verwarf eine korrekte `sellable`-Bewertung mit Konfidenz 1,0 | Mehr korrekte Bewertungen landen fälschlich in der Handprüfung |

### Aufrufstruktur

| Entscheidung | Wo | Messwert | Beim Zurückdrehen |
|---|---|---|---|
| Artikelabgleich und Schadensprüfung getrennt, je ein Bild | `vision_client.py:43-57` | Zweibild-Aufruf beschrieb hellblauen Duplo-Stein und gelbes Katalogbild gleich → `same_article: true`; sichtbarer Bruch wurde als „decorative element" abgetan | Verwechselte Artikel durchgewinkt, Schäden übersehen |
| Bildbefund geht **nicht** in den Textprompt | `llm_client.py:279-291` | QA/0011: mit „keine Bildinhalte verfügbar" begründete das Modell `scrap` — das fehlende Bild wurde als erschwerender Umstand gewertet | Textmodell kann den Widerspruch zum Bildurteil wegerklären, statt ihn zu zeigen |
| Bei `mismatch` kein Zustandsvergleich | `n8n_v2.py:335-343` | QA/0229: Hundefoto gegen Katalogbild ergab „keine Abweichung vom Neuzustand" | Bedeutungsloser Soll-Ist-Vergleich erscheint als Aussage über den Zustand |
| Zustandsvergleich **nur bei `intact`** | `n8n_v2.py`, `_check_damage` | Er darf nur eskalieren, kann an `damaged` also nichts mehr ändern — kostete aber den letzten Bildaufruf. In den Läufen 9 bis 13 kam er deshalb nie mehr dran. Lauf 14 mit denselben Fotos wie 13: Zeile entfällt, ein Aufruf frei | Der Vergleich frisst wieder den Aufruf, den das letzte Foto braucht, und entscheidet dabei nichts |
| Glossar setzt Zweiwortbefunde zusammen | `_zusammengesetzt`, `n8n_v2.py` | Gemessen über 80 Alerts: 29 Begriffe, 5 übersetzt. Nach der Wortgrenze im Prompt blieb `gouged stud` (QA/0378) als einziger Fall; Lauf 14 liefert dafür `ausgekerbte Noppe` | Kurze Kombinationen stehen wieder englisch im Odoo-Formular |
| Zustandsvergleich darf nur eskalieren | `n8n_v2.py:905-916` | QA/0223: Vergleich erklärte einen gefundenen Riss weg („beide Beschreibungen enthalten 'smooth'") | Gefundene Schäden werden wieder gesund geschrieben |
| Keine Heuristik als Rückfallebene | `llm_client.py:5-7` | Architekturentscheidung des v2-Umbaus | Ersatzurteile ohne Grundlage statt ehrlichem `review_required` |

### Artikelabgleich über Einbettung

| Entscheidung | Wo | Messwert | Beim Zurückdrehen |
|---|---|---|---|
| DINOv2 als Primärweg, Text nur als Rückfall | `config.py:193-212` | 10 Meldungen: Textvergleich 3 falsche Abweisungen, Einbettung 7/7 in 0,36–1,78 s gegen 45–165 s | Rückfall auf den wortbasierten Vergleich, der an Wortwahl statt Bildinhalt scheitert |
| Farbkanal mit Gewicht 0,25 | `embed/server.py:47-50` | 44 Artikel gegen ihr gedrehtes Abbild: reine Form 33/44, mit 0,25 Farbe 41/44; bei 0,40 entscheidet zunehmend die Beleuchtung | Formdominante Fehltreffer bei gleich geformten, verschiedenfarbigen Artikeln (0,9157 Ähnlichkeit zwischen grünem und blauem 2x2) |
| Fremdschwelle 0,45, Knappheitsschwelle 0,02 | `embed/server.py:52-62` | Echte Teile 0,819–0,997, Hundefoto 0,047; Paar 6167549/6171865 real zu ähnlich | Niedriger: Fremdobjekte gelten als Artikel. Höher: knappe echte Treffer werden verworfen |
| `unsicher` fällt auf den Textweg zurück statt `mismatch` zu werden | `n8n_v2.py:408-414` | Hundefoto 0,203 gegen Schwelle 0,45 | Falsches Abweisen echter Meldungen |

### Betrieb und Zeitgrenzen

| Entscheidung | Wo | Messwert | Beim Zurückdrehen |
|---|---|---|---|
| `num_thread: 8` im Request, **nicht** über `OLLAMA_NUM_THREAD` | `vision_client.py`, `llm_client.py`, `docker-compose.yml` | 15.09.2026: Umgebungsvariable 1,21 tok/s, Option im Request 7,40 tok/s. Log: `n_threads = 14` gegen `n_threads = 8` | Threadzahl wird stillschweigend ignoriert — Ursache aller drei abgebrochenen Läufe 1 bis 3 A |
| Nur eine Bewertung gleichzeitig (Semaphore 1) | `n8n_v2.py:105-115` | 07.08.2026: zwei Meldungen 20 s auseinander; 8-s-Aufrufe brauchten 1:30 bis 3:20, zwei endeten in HTTP 500, **beide** Bewertungen fielen aus | Parallele Bewertungen zerlegen sich gegenseitig auf einem Rechner ohne GPU |
| `OLLAMA_MAX_LOADED_MODELS = 2` | `docker-compose.yml` | Dritter Ladeversuch endete in `signal: killed` | Wieder OOM |
| Textbewertung bleibt `qwen2.5:7b` | `config.py:123` | **Neu gemessen am 16.09.2026** mit `bench_text_models.py`, 12 beschrifteten Meldetexten, beide Modelle warm, `format: "json"`: `qwen2.5:7b` 11/12 Disposition, 10/12 Grundlage, Median **11,7 s**; `gemma4:12b` 11/12 Disposition, 12/12 Grundlage, Median **216,1 s**. Gleichstand in der Qualität, Faktor 18 im Preis | `LLM_TIMEOUT_MS` steht auf 90 s — `gemma4:12b` liefe in **jeder** Textbewertung in die Zeitschranke, und das Texturteil ist die Hälfte des Widerspruchszweigs |
| Ein Modell für Text und Bild scheidet aus | dieselbe Messung | Der frühere Befund „467 Token, kein Ende, nach 4 min abgebrochen" war ein Artefakt der fehlenden Formatbindung: mit `format: "json"` läuft `gemma4:12b` sauber durch, es ist schlicht zu langsam | Scheitert nicht an der Architektur, sondern an der fehlenden GPU — auf einer GPU wäre die Zusammenlegung zu prüfen, dann passten auch drei Modelle nicht mehr in zwei Plätze |
| Modelle beim Backend-Start vorwärmen, Reihenfolge Sprache → Text → Bild | `main.py`, `MODEL_WARMUP` | Lauf 16, 16.09.2026: Kaltstart Text 1 min 11 s, Bild 1 min 36 s, zusammen 3 min 11 s Startzeit. Ohne Vorwärmen steckten dieselben 96 s im ersten Schadensaufruf und hätten Katalogbild und Zustandsvergleich verdrängt | Die erste Meldung nach jedem Start zahlt den Kaltstart aus ihrem eigenen 255-s-Budget — in jeder Vorführung, weil dort niemand `warmlaufen.py` in den Container legt |
| `_MAX_ASSESSMENT_PHOTOS = 3` | `odoo/addons/quality_alert_custom/models/quality_alert.py` | Läufe 6 bis 8: je Foto 42–50 s; drei Fotos lasten den n8n-Knoten zu 94 % aus | Vier Fotos reißen das Knotenlimit — die Zahl steht jetzt in `QA_MAX_ASSESSMENT_PHOTOS` |
| `_schadensworte`: entdoppeln und übersetzen | `n8n_v2.py:689-732` | QA/0370: „crack, broken edge, crack, split" aus zwei Fotos desselben Risses | Aufzählung wirkt länger als der Schaden ist |

---

## 3. Was der Betrieb an Zeit hat

| Grenze | Wert | Quelle |
|---|---|---|
| Textbewertung je Aufruf | 90 s | `LLM_TIMEOUT_MS` |
| Bildaufruf einzeln | 200 s | `config.py:187` |
| Bildbudget für alle Bildaufrufe | 240 s | `config.py:192` |
| **Frist des Anrufers** | **255 s** | `caller_budget_ms`, seit 15.09. |
| **Reicht die Zeit für den nächsten Bildaufruf?** | **gemessen**, Vorgabe 60 s | `geschaetzte_schadensdauer` (80-%-Wert der letzten acht Aufrufe), Vorgabe `vision_call_estimate_ms` |
| Warten auf die Bewertungssperre | 150 s | `config.py:235` |
| **n8n-Knoten** | **270 s** | `n8n/workflows/quality-assessment-v2.json` |

Gemessene Auslastung des Knotenlimits: 59 % (2 Fotos), 70 % (4 Fotos, davon 3 geprüft),
94 % (3 Fotos), 78 % (Lauf 10, 5 Fotos, davon 3 geprüft), 92 % (Lauf 11, 5 Fotos, davon 2 geprüft). **Die Summe der Einzelbudgets übersteigt
das Knotenlimit** — 90 s Text plus 240 s Bild plus zwei Textvergleiche à 90 s.

**Bezahlt am 15.09. nach Lauf 9.** Die Einzelbudgets blieben, darüber liegt jetzt die Frist des
Anrufers: Die Bildstufe rechnet ab dem Eintreffen der Anfrage, nicht ab dem Start der Bildstufe,
und startet einen Aufruf nur, wenn dessen Schätzwert noch hineinpasst. Messwert: Lauf 9 und
Lauf 10 mit **denselben fünf Fotos** (MD5 gleich) — 270 s Abbruch mit leerem Befund gegen 210,9 s
mit vollem Befund und der Zeile `Fotos: 2 weitere ungeprüft.` Verlorene Rechenzeit 65,6 s gegen
0 s.

Der Preis: Fotos, die rechnerisch nicht mehr passen, werden nicht mehr versucht — auch dann nicht,
wenn der Aufruf schneller gewesen wäre als der Schätzwert. In Lauf 10 lagen die Aufrufe bei
40,2–46,2 s; ein viertes Foto hätte gepasst. Der Schätzwert ist bewusst konservativ: ein
liegengebliebenes Foto wird genannt, eine abgeschnittene Antwort ist ganz weg.

**Seit Lauf 12 misst die Kette selbst.** `vision_client` hält die Dauer der letzten acht
Schadensaufrufe je Modell fest; die Schranke fragt den **80-%-Wert** ab, vor drei Messungen die
Vorgabe. Nicht der Mittelwert — die Hälfte aller Aufrufe würde ihn reißen. Nicht der Höchstwert —
nach Lauf 11 stünde die Schätzung acht Aufrufe lang auf 83 s. Abgebrochene Aufrufe zählen nicht
mit: ihre Dauer ist die Restzeit, die sie noch hatten, nicht die, die sie gebraucht hätten.

Messwert dafür: Läufe 11, 12 und 13 bei praktisch gleicher Laufzeit (247,9 / 252,5 / 248,3 s) —
**2, dann 4, dann 5 von fünf Fotos geprüft**. In Lauf 13 fiel die Schätzung nach einem Aufruf von
37,48 s auf 49,9 s und ließ Foto 5 zu, das gegen die feste Vorgabe liegengeblieben wäre.

Der Preis: die Messreihe liegt im Prozess und überlebt keinen Neustart — nach jedem Backend-Start
laufen die ersten drei Aufrufe wieder gegen die Vorgabe. Bewusst so: eine kalte Maschine rechnet
ohnehin anders.

**Nachtrag Lauf 11: 60 s sind auch zu wenig.** Ein Bildaufruf brauchte dort 82,88 s bei 519 Token,
ein zweiter im selben Lauf 59,11 s bei 513 Token. Das Band ist damit **42–83 s**. Ein fester Wert
kann beides nicht abdecken; ein gleitender Mittelwert der letzten Aufrufe je Modell wäre die
ehrlichere Grenze. Dass Lauf 11 trotzdem durchkam, liegt an der zweiten Schranke: `_in_restzeit`
kappt einen laufenden Aufruf an der Frist und rettet die bereits fertigen Befunde. Der Schätzwert
spart Rechenzeit, die Kappung rettet Ergebnisse — erst beide zusammen tragen.

---

## 3b. Was gemessen und VERWORFEN wurde

| Idee | Warum sie naheliegt | Messung | Ergebnis |
|---|---|---|---|
| Feld `outline_description` im Schadensprompt | Lauf 15: beide Bildstufen übersahen eine sauber fehlende Ecke, weil `surface_description` nur die Oberfläche beschreibt | `bench_umriss.py` über vier Fotos aus den Läufen 12, 13 und 15 | **Verworfen.** Das Modell antwortet auf den Lauf-15-Fotos „The body is complete with all corners and edges present" — es sieht die fehlende Geometrie nicht. Zusätzlich 46–55 s statt 8–41 s je Aufruf |

Daraus die Eigenschaft, die für die Arbeit gilt: **die Kette erkennt Oberflächenschäden, keine
fehlende Geometrie.** Der Widerspruchszweig fängt diesen Fall ab (`review_required`, Lauf 15).

---

## 4. Angaben, die überholt sind

Diese Kommentare stehen so im Code und stimmen nicht mehr. Sie sind hier aufgeführt, damit sie
niemand als Beleg zitiert.

1. **`config.py:203-211` — „Einbettung 7/7"**. Die Zahl stammt von Fotos mit gutem Hintergrund.
   In den Läufen 1 bis 3 lieferte derselbe Weg dreimal in Folge ein falsches `mismatch`. Grund:
   Bei Lagerhintergrund fällt der beste Kandidat auf 0,4973 — **knapp über** der Fremdschwelle von
   0,45. Das Verfahren erkennt seine eigene Unsicherheit also nicht, sondern gibt ein
   selbstsicheres Fehlurteil aus, das laut `n8n_v2.py:524` das letzte Wort hat.
2. **`config.py:230-234` — „typische Bewertung rund 100 s"**, daraus abgeleitet 150 s Wartezeit.
   Gemessen: 141,6 s, 192,6 s, 161,4 s, 257 s, 188 s — im Mittel eher 200 s.
3. **`config.py:182-186` — „Schadensprüfung 9 s"**. Galt bei 512 px und altem Modell. Heute
   42–56 s je Aufruf.
4. **`config.py:112-113` gegen `llm_client.py:5-7`**: Das eine sagt „fällt auf die n8n-Heuristik
   zurück", das andere „eine Heuristik gibt es seit dem v2-Umbau nicht mehr". Einer der beiden
   Kommentare ist falsch.
5. **`vision_client.py:88-92` — „768 px bei der Schadensprüfung"**. Tatsächlich 1024 px seit dem
   08.08.2026.
6. **`config.py:172-177` — Artikelmodell 10/12**: Die Messung lief auf einer Montage beider Teile
   in einem Bild, nicht auf dem Produktivpfad. Der Kommentar sagt das selbst; wer die Zahl
   zitiert, muss es mitzitieren.

---

## 5. Was die Kette empfindlich macht

1. **Fremdlast auf ollama kippt jede Bewertung.** Ein einzelner fremder Generierungslauf verdrängte
   `qwen2.5:7b`, trieb die Textbewertung in ihr 90-s-Limit und den n8n-Knoten in den Abbruch
   (Lauf 7 A). Ein abgebrochener Client beendet die Generierung **nicht** — aufräumen nur über
   `docker restart`.
2. **Der Bildhintergrund entscheidet über die Artikelachse.** Freigestellt 0,8723 auf Platz 1,
   im Regalfoto 0,393 auf Platz 5 — dasselbe Teil, derselbe Schaden.
3. **Die Formvielfalt des Katalogs entscheidet über den Abstand.** Dachstein 0,2396 Abstand,
   zwei Artikel derselben Formfamilie 0,0000.
4. **Die Geschwätzigkeit des Bildmodells ist nicht stabil.** Dasselbe Foto, derselbe Prompt,
   `temperature: 0` — einmal fünf Sätze, einmal zwei Wörter. Einzelmessungen taugen nicht.
5. **Der Soll-Befund-Cache überlebt keinen Neustart** (`n8n_v2.py:812`). Erste Meldung je Artikel
   kostet danach 25–33 s extra.

---

## 6. Belege

- Einzelprotokolle: `docs/testlaeufe/*/protokoll.md`
- Gesamtübersicht aller Läufe: `docs/testlaeufe/GESAMTUEBERSICHT.md`
- Messskripte: `.claude/skills/qa-testlauf/scripts/`

---

## 7. Nachgemessen am 15.09.2026: die Fremdschwelle bleibt

Aus den Läufen 1 bis 3 entstand der Verdacht, `EINBETT_FREMD_SCHWELLE = 0.45` sei zu niedrig: Der
falsche Gewinner im Lagerfoto kam auf 0,4973 und damit knapp darüber, das Verfahren gab also ein
selbstsicheres Fehlurteil statt `unsicher`. Eine Auswertung der in den Protokollen notierten Werte
legte eine Schwelle um 0,78 nahe — sie hätte alle drei Fehlurteile verhindert, ohne einen
dokumentierten Treffer zu kosten.

**Die Nachmessung über 23 Fotos widerlegt das.** Gemessen mit
`scripts/probe_schwellen.py` direkt gegen den Einbettungsdienst:

| Bildwelt | n | kleinster Spitzenwert | größter Spitzenwert |
|---|---|---|---|
| unverändertes Katalogbild | 2 | 1,0000 | 1,0000 |
| Schadensfoto freigestellt | 14 | **0,6391** | 0,9301 |
| Schadensfoto im Lager | 7 | 0,4263 | **0,7655** |

Die Bereiche überlappen von 0,639 bis 0,766. Eine Schwelle bei 0,78 hätte **vier von vierzehn**
korrekten Treffern auf weißem Grund zerstört (0,6640, 0,6937, 0,7108, 0,7681). Die frühere
Empfehlung beruhte auf den Bestwerten, die zufällig in den Protokollen standen.

**Die Schwelle bleibt bei 0,45.** Der Hebel gegen die Fehlurteile ist und bleibt der Hintergrund
des Meldefotos, nicht die Schwelle.

### Nebenbefund: nicht jede Ansicht taugt für die Artikelachse

```
pr_r8_04.jpg  frei  mismatch  6294943  0.6391  Abstand 0.0468  4216758 auf Platz 5
```

Die Unteransicht der Platte aus Lauf 8 liefert **freigestellt** ein Fehlurteil. `_check_article`
(`backend/app/routers/n8n_v2.py:322`) sieht nur `candidates[0]` — das zuerst hochgeladene Foto.
Wäre diese Ansicht zuerst gekommen, hätte die Artikelachse falsch entschieden. In Lauf 8 hat die
Odoo-Obergrenze von drei Fotos sie zufällig ausgeschlossen.

**Vorschlag, gemessen begründet:** Den Einbettungsabgleich über **alle** Fotos laufen lassen und
den besten Spitzenwert nehmen, statt blind das erste Foto zu verwenden. Kosten: 0,24 bis 0,66 s je
Abfrage, bei drei Fotos also unter 2 s — gegen einen Fehlurteilstyp, der die ganze Bewertung
entwertet. Noch nicht umgesetzt; die Änderung gehört gemessen, bevor sie eingebaut wird.
