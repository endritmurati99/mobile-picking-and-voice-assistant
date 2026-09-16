# Testlauf 17 — Artikelsuche über mehrere Fotos, Sprach-Vorwärmen, Soll-Befund-Cache

**Datum:** 16.09.2026
**Alert:** QA/0382 (id 383)
**Auftrag:** L1/OUT/00248, Position 4 von 5
**Artikel:** Brick 2x2 grün, SKU 4183780, Produkt 76, Regal C-02, 5 Stück
**Fotos:** 3 (201 KB), **MD5-identisch mit den Läufen 15 und 16**
**Fotoobergrenze:** `QA_MAX_ASSESSMENT_PHOTOS=3` (Produktivwert)

---

## 1. Was dieser Lauf prüft

Drei Änderungen, alle aus den Zahlen von Lauf 16 abgeleitet:

| | Änderung | Erwartung aus Lauf 16 |
|---|---|---|
| a | Artikelabgleich weicht bei `zu_dicht` auf das nächste Foto aus | 59,8 s gespart |
| b | Sprach-Warmlauf bekommt eine eigene Frist statt der 4 s für echte Äußerungen | wärmt überhaupt erst |
| c | Zustandsbefund des Katalogbilds überlebt einen Neustart | 22,0 s bei der jeweils ersten Meldung je Artikel |

Fotos, Auftrag, Position und Text sind gegen die Läufe 15 und 16 konstant gehalten.

### Bedienung ohne Hilfsmittel

Dieser Lauf wurde **ausschließlich über die Oberfläche** bedient: Auftrag anklicken, Position
wählen, Problem melden, Fotos anhängen, absenden. Kein `warmlaufen.py`, kein `docker cp`, kein
Eingriff in laufende Prozesse. Alles, was vor der Meldung passierte, hat der Code selbst getan.
Gemessen wird also der Weg, den auch eine Vorführung nimmt.

---

## 2. Vorwärmen

| Zeit | Dauer | Ereignis |
|---|---|---|
| 10:02:01,7 | — | Backend neu erzeugt, ollama zuvor leer |
| 10:02:32 | ~30 s | **`qwen2.5:1.5b` geladen** |
| 10:02:52 | ~20 s | `qwen2.5:7b` geladen |
| 10:03:32 | — | `qwen2.5:1.5b` verdrängt |
| 10:04:33 | ~60 s | `gemma4:12b` geladen |

**Gesamt 2 min 32 s** (Lauf 16: 3 min 11 s).

**(b) wirkt.** In Lauf 16 endete der Sprach-Warmlauf nach rund 11 s mit
`{"event_type": "voice_intent_llm_failed", "error": ""}` und lud nichts. Hier steht das Modell im
Speicher, und die Logzeile fehlt.

Die Verdrängung um 10:03:32 lief in der beabsichtigten Richtung: das billigste Modell fiel heraus,
nicht das teuerste.

---

## 3. Zeitlicher Ablauf

| Zeit | seit Start | Dauer | Ereignis | Quelle |
|---|---|---|---|---|
| **10:09:16,8** | 0 s | — | **Meldung abgesendet** | Browser |
| 10:09:17,8 | 1,0 s | — | `POST /webhook/quality-assessment-v2` → 200 | backend.log |
| 10:10:09 | 52 s | 46,9 s | Textbewertung (Disposition) | ollama.log |
| 10:10:24,04 | 67 s | 0,25 s | `embed_abgleich` **Foto 1**: `unsicher`, `zu_dicht`, Abstand 0,0155 | backend.log |
| 10:10:24,05 | 67 s | — | **`article_retry`**, `foto: 1, von: 3` | backend.log |
| 10:10:24,29 | 68 s | 0,24 s | `embed_abgleich` **Foto 2**: **`match`**, Abstand 0,0362 | backend.log |
| 10:11:14,8 | 118 s | 45,6 s | Schadensprüfung Foto 1 | backend.log |
| 10:11:55,6 | 159 s | 38,4 s | Schadensprüfung Foto 2 | backend.log |
| 10:12:35,8 | 199 s | 37,8 s | Schadensprüfung Foto 3 | backend.log |
| 10:13:00,5 | 224 s | 22,2 s | Katalogbild (Soll-Befund, erstmals) | backend.log |
| 10:13:19,99 | 243 s | 17,0 s | `condition_compare` | backend.log |
| 10:13:20 | 244 s | — | Alert geschrieben | Odoo |

**Gesamtdauer 4 min 4 s.**

---

## 4. Ergebnis

```
name:                  QA/0382
ai_evaluation_status:  review_required
ai_failure_reason:     Foto widerspricht der Meldung, siehe Fotoanalyse.
ai_photo_analysis:     Schaden: keine Auffälligkeit sichtbar.
                       Hinweis: Die Einstufung lautet „Aussondern", aber kein Foto belegt einen
                       Schaden. Aussondern lässt sich nicht zurücknehmen — bitte manuell
                       entscheiden.
                       Texturteil der Meldung (nicht wirksam): scrap, Konfidenz 0.95.
```

Derselbe Endzustand wie in den Läufen 15 und 16 — dritte Wiederholung, dieselbe Entscheidung.

---

## 5. Befunde

### 5.1 (a) trägt, und zwar deutlich

```json
{"event_type": "embed_abgleich", "urteil": "unsicher", "grund_art": "zu_dicht",
 "rang": [["4183780", 0.8799], ["343724", 0.8644]], "abstand": 0.0155, "duration_ms": 250}
{"event_type": "article_retry", "grund": "zu_dicht", "foto": 1, "von": 3}
{"event_type": "embed_abgleich", "urteil": "match", "grund_art": "treffer",
 "rang": [["4183780", 0.7619], ["301124", 0.7257]], "abstand": 0.0362, "duration_ms": 244}
```

**246 ms statt 59,8 s.** In Lauf 16 sprang an derselben Stelle der Textweg an: eine
Bildbeschreibung des Meldefotos (33,1 s) plus ein Textvergleich (26,7 s). Beides entfällt, und
damit sinkt die Zahl der Bildaufrufe von fünf auf **vier**.

Der Artikelabgleich liefert zusätzlich ein besseres Ergebnis: `match` statt `unsicher`, also eine
Aussage statt einer Enthaltung.

### 5.2 Warum unterm Strich nur 31 s übrig bleiben

| | Lauf 16 | Lauf 17 | Differenz |
|---|---|---|---|
| Gesamt | 275 s | 244 s | **−31 s** |
| Artikelachse | 59,8 s | 0,25 s | −59,6 s |
| Schadensprüfung (3 Fotos) | 108,1 s | 121,8 s | +13,7 s |
| Textbewertung | 30,1 s | 46,9 s | +16,8 s |

Die Ersparnis auf der Artikelachse ist eindeutig. Dass davon nur 31 s ankommen, liegt an der
bekannten Streuung der Modelle bei **identischen Fotos und identischem Prompt** — Stolperfalle 9.
Die Schadensprüfung war 13 % langsamer, die Textbewertung 56 %. Das ist kein Gegenargument gegen
(a), sondern die Bestätigung, dass Einzelmessungen an dieser Kette nichts entscheiden.

### 5.3 (c) schreibt, bleibt aber unbewiesen

Der Cache wurde erstmals gefüllt:

```json
{"c8b8082...": {"ok": true, "damaged": false, "anomalies": [],
                "description": "smooth and continuous everywhere"}}
```

Ob er einen Neustart überlebt, prüft Lauf 18. In diesem Lauf kostete der Katalogbildaufruf noch
die vollen 22,2 s, weil der Cache leer anfing.

### 5.4 (b) hat eine Verschlechterung eingebracht

Ein funktionsfähiger Sprach-Warmlauf **verdrängt bei bereits warmem ollama das Bildmodell**.
Belegt beim Backend-Neustart um 10:13:59:

```
10:14:13  POST /api/chat  10.1s    qwen2.5-1.5B geladen
10:16:01  vision_probe    88798ms  gemma4:12b neu geladen
```

`OLLAMA_MAX_LOADED_MODELS` steht auf 2, im Spiel sind drei Modelle. Ollama räumt das am längsten
ungenutzte weg — das war nach Lauf 17 das Bildmodell (zuletzt 10:13:00) und nicht das Textmodell
(zuletzt 10:13:19). Ergebnis: **121 s Nachladen, die vor der Änderung nicht angefallen wären**,
weil der Warmlauf damals nach 4 s aufgab und gar nichts lud.

Die Änderung ist damit nicht falsch, aber unvollständig: sie macht einen Zweig funktionsfähig, für
den kein Platz reserviert ist.

**Zwei Auswege, gemessen zu entscheiden:**

1. `OLLAMA_MAX_LOADED_MODELS: "3"`. Die drei Modelle wiegen 9,2 + 5,1 + 1,2 = 15,5 GB bei
   25,44 GiB Gesamtspeicher. Der OOM vom 14.08.2026 trat bei 9,2 + 5,1 + 6,2 = 20,5 GB auf, also
   5 GB höher. Vor einer Umstellung gehört der tatsächliche Speicherbedarf bei drei geladenen
   Modellen gemessen — die Modellgröße ist nicht der Speicherbedarf, der Kontext kommt hinzu.
2. Sprach-Warmlauf streichen. Sein Nachladen kostet rund 13 s, das des Bildmodells 90–120 s.

---

## 6. Belege

| Datei | Inhalt |
|---|---|
| `fotos/run17_photo_01..03.jpg` | die drei gemeldeten Fotos |
| `pruefsummen.txt` | MD5, identisch mit Lauf 15 und 16 |
| `soll_befunde_nach_lauf17.json` | Cache-Inhalt nach dem Lauf |
| `logs/backend.log` | Kette, `article_retry`, Vorwärmen |
| `logs/ollama.log` | Modellaufrufe, Ladezeiten, Verdrängung |
| `logs/ollama_models.txt` | geladene Modelle mit Kontextgrößen |
| `logs/odoo.log` | Alert-Schreibvorgang |
| `logs/container_images.txt` | Image-Stände |
