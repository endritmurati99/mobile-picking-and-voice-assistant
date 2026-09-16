# Testlauf 16 — Kaltstart mit automatischem Vorwärmen

**Datum:** 16.09.2026
**Alert:** QA/0381 (id 382)
**Auftrag:** L1/OUT/00248, Position 4 von 5
**Artikel:** Brick 2x2 grün, SKU 4183780, Produkt 76, Regal C-02, 5 Stück
**Fotos:** 3 (201 KB), **MD5-identisch mit Lauf 15**
**Fotoobergrenze:** `QA_MAX_ASSESSMENT_PHOTOS=3` (Produktivwert)

---

## 1. Was dieser Lauf prüft

Eine Frage, eine Variable: **Trägt das neu eingebaute Vorwärmen, und was kostet ein Kaltstart,
wenn niemand von Hand nachhilft?**

Alles andere ist gegen Lauf 15 konstant gehalten — derselbe Auftrag, dieselbe Position, dieselben
drei Fotos (Prüfsummen in `pruefsummen.txt`), derselbe Beschreibungstext bis auf die Laufnummer.

### Die Ausgangslage war echt kalt

Der Rechner war über Nacht aus. Docker Desktop lief nicht, alle Container standen seit 16 Stunden
auf `Exited`. Nach dem Hochfahren des Stacks meldete `ollama ps` kein einziges Modell. Das ist
nicht nachgestellt, sondern der Zustand, den eine Vorführung am Morgen vorfindet.

### Warum die Frage überhaupt gestellt wurde

Bis zu diesem Lauf wärmte **nur das Sprachmodell** vor (`VOICE_LLM_WARMUP`). Text- und Bildmodell
wärmte ausschließlich `warmlaufen.py` — ein Testskript, das von Hand per `docker cp` in den
Container gelegt wird. In einer Vorführung ohne diesen Handgriff hätte die erste Meldung den
Kaltstart des Bildmodells aus ihrem eigenen 255-s-Budget bezahlt.

---

## 2. Eingangsdaten

```
Kategorie:    Artikel beschädigt
Priorität:    Normal
Beschreibung: Testlauf 16: Artikel beschaedigt: Brick 2x2 gruen (SKU 4183780), Regal C-02.
              Eine Ecke fehlt vollstaendig, Bruchflaeche glatt. Nicht versandfaehig.
              Drei Fotos angehaengt.
Fotos:        3  (201 KB gesamt)
```

Die Dateinamen lauten `run16_photo_01..03.jpg` statt `qa_photo_01..03.jpg`. Das ist Absicht: der
Idempotenzschlüssel enthält `Dateiname:Größe`, gleiche Namen hätten den Alert aus Lauf 15
zurückgeliefert, ohne n8n anzustoßen. Der Bildinhalt ist über die MD5-Summen nachweislich
derselbe.

---

## 3. Zeitlicher Ablauf

Alle Zeiten UTC, Quelle je Zeile benannt.

### 3.1 Vorwärmen (vor der Meldung, automatisch)

| Zeit | Dauer | Ereignis | Quelle |
|---|---|---|---|
| 08:56:17,2 | — | Backend neu erzeugt, `MODEL_WARMUP=true` | PowerShell |
| 08:56:28,4 | ~11 s | Sprachmodell scheitert: `voice_intent_llm_failed`, `error: ""` | backend.log |
| 08:57:44 | 1 min 11 s | Textmodell `qwen2.5:7b` warm, `POST /api/chat` | ollama.log |
| 08:59:28 | 1 min 36 s | Bildmodell `gemma4:12b` warm, `POST /api/generate` | ollama.log |

**Gesamt 3 min 11 s** vom Backend-Start bis zu zwei einsatzbereiten Modellen — ohne Zutun.

```
NAME          ID              SIZE      PROCESSOR    CONTEXT
gemma4:12b    4eb23ef187e2    9.2 GB    100% CPU     8192
qwen2.5:7b    845dbda0ea48    5.1 GB    100% CPU     4096
```

Die Kontextgrößen stimmen mit denen der Produktivaufrufe überein (Bild 8192, Text 4096). Damit
findet der erste echte Aufruf denselben Runner vor und lädt nicht nach — Stolperfalle 3 aus dem
Testlauf-Skill ist damit im Code ausgeschlossen, nicht mehr nur in der Anleitung.

### 3.2 Die Kette

| Zeit | seit Start | Dauer | Ereignis | Quelle |
|---|---|---|---|---|
| **08:59:40,3** | 0 s | — | **Meldung abgesendet** | Browser |
| 08:59:45,7 | 5,4 s | — | `POST /webhook/quality-assessment-v2` → 200 | backend.log |
| 09:00:18 | 38 s | 30,1 s | Textbewertung (Disposition) | ollama.log |
| 09:00:31,6 | 51 s | 0,23 s | `embed_abgleich`: `unsicher`, `zu_dicht` | backend.log |
| 09:01:07,1 | 87 s | 33,1 s | Bildbeschreibung Meldefoto (Rückfallweg Artikel) | backend.log |
| 09:01:36 | 116 s | 26,7 s | Artikelvergleich im Text | ollama.log |
| 09:02:12,7 | 152 s | 34,1 s | Schadensprüfung Foto 1 | backend.log |
| 09:02:56,4 | 196 s | 38,7 s | Schadensprüfung Foto 2 | backend.log |
| 09:03:34,0 | 234 s | 35,3 s | Schadensprüfung Foto 3 | backend.log |
| 09:03:56,1 | 256 s | 22,0 s | Katalogbild (Soll-Befund) | backend.log |
| 09:04:15,8 | 275 s | 17,3 s | `condition_compare` | backend.log |
| 09:04:15 | 275 s | — | `callbacks/status` → 200, Alert geschrieben | backend.log |

**Gesamtdauer 4 min 35 s.**

Die Zuordnung der Bildaufrufe stützt sich auf die Token-Zahlen im ollama-Log: Meldefotos gehen mit
455 Prompt-Token hinein, das 192-px-Katalogbild mit 248 — der Aufruf um 09:03:56 ist damit
zweifelsfrei das Katalogbild und kein viertes Foto.

---

## 4. Ergebnis der Systembewertung

```
name:                  QA/0381
ai_evaluation_status:  review_required
ai_failure_reason:     Foto widerspricht der Meldung, siehe Fotoanalyse.
ai_photo_analysis:     Schaden: keine Auffälligkeit sichtbar.
                       Hinweis: Die Einstufung lautet „Aussondern", aber kein Foto belegt einen
                       Schaden. Aussondern lässt sich nicht zurücknehmen — bitte manuell
                       entscheiden.
                       Texturteil der Meldung (nicht wirksam): scrap, Konfidenz 0.95.
                       Eck fehlt, nicht mehr versandfähig.
ai_last_analyzed_at:   2026-09-16 09:04:15
```

`condition_compare`: `new_damage: false`, `damage: "intact"`,
Begründung „Die Beschreibungen stimmen überein und deuten auf den gleichen Zustand hin."

---

## 5. Befunde

### 5.1 Das Vorwärmen trägt — und es trennt den Kaltstart vom Zeitbudget

Alle drei Fotos wurden geprüft **und** der Zustandsvergleich lief, obwohl der Rechner acht Minuten
zuvor noch kalt war. Der Kaltstart kostete 3 min 11 s Startzeit statt Fotos.

Zum Vergleich, was ohne den Einbau passiert wäre: Das Bildmodell lud im Vorwärmaufruf 1 min 36 s.
Dieselben 96 s hätten sonst im ersten Schadensaufruf gesteckt. Bei 240 s Bildbudget wären danach
144 s übrig gewesen — bei 34–39 s je Foto reicht das für drei Fotos rechnerisch noch, aber nicht
mehr für Katalogbild und Zustandsvergleich. **Der Zustandsvergleich wäre ausgefallen**, und damit
die Stufe, die den Widerspruch überhaupt erst sauber belegt.

### 5.2 Das Ergebnis ist reproduzierbar, der Wortlaut nicht

Lauf 15 und Lauf 16 kommen mit denselben Fotos zum selben Endzustand `review_required` über
denselben Widerspruchszweig — über einen vollständigen Neustart von Docker, ollama und Backend
hinweg. Die Begründung des Zustandsvergleichs weicht im Wortlaut ab („auf einen Neuzustand" gegen
„auf den gleichen Zustand"), das Urteil nicht.

Das ist die saubere Trennung, die Stolperfalle 9 verlangt: das Modell schwankt in der Formulierung,
die Kette nicht in der Entscheidung.

### 5.3 Das Sprach-Vorwärmen scheitert auf kaltem ollama grundsätzlich

`{"event_type": "voice_intent_llm_failed", "error": ""}` nach rund 11 s. Ursache ist
`llm_voice_timeout_ms = 4000`: vier Sekunden reichen nicht, um ein Modell von der Platte zu laden.
Best-effort, blockiert nichts, wärmt aber auch nichts. Kein Fehler im neuen Code — der Zweig ist
älter —, gehört aber als offener Punkt festgehalten.

### 5.4 Laufzeitvergleich mit Lauf 15

| | Lauf 15 (warm) | Lauf 16 (kalt + Vorwärmen) |
|---|---|---|
| Gesamt | 4 min 11 s | 4 min 35 s |
| Bildaufrufe nach Absenden | 5 | 5 |
| Summe der Bildaufrufe | 162,6 s | 163,1 s |
| Fotos geprüft | 3 von 3 | 3 von 3 |
| Zustandsvergleich | gelaufen | gelaufen |

Die Bildstufe ist mit 0,5 s Unterschied praktisch deckungsgleich. Die 24 s Mehrlaufzeit liegen auf
der Textseite und in der Übergabe — nicht am Kaltstart, der zu diesem Zeitpunkt längst bezahlt war.

### 5.5 Der Artikelabgleich bleibt bei `unsicher`

`rang: [["4183780", 0.8799], ["343724", 0.8644], ["301124", 0.857]]`, Abstand **0,0155** — Wert für
Wert identisch mit Lauf 15. Der 2x2-Würfel in Grün hat im Katalog zu viele Geschwister, und der
Einbettungsabgleich ist an dieser Stelle deterministisch. Der Textweg übernahm wie dort und kostete
59,8 s (Bildbeschreibung 33,1 s plus Textvergleich 26,7 s), also 22 % der Laufzeit.

---

## 6. Vorbelastung

Odoo protokolliert weiterhin alle 13–15 Sekunden
`RuntimeError: Couldn't bind the websocket. Is the connection opened on the evented port (8072)?`
mit `"GET /websocket" 500`. Unabhängig von der Meldungskette.

---

## 7. Belege

| Datei | Inhalt |
|---|---|
| `fotos/run16_photo_01..03.jpg` | die drei gemeldeten Fotos |
| `pruefsummen.txt` | MD5, identisch mit Lauf 15 |
| `logs/backend.log` | Kette, Vorwärmen, Zeitstempel |
| `logs/ollama.log` | Modellaufrufe, Token-Zahlen, Ladezeiten |
| `logs/ollama_models.txt` | geladene Modelle mit Kontextgrößen |
| `logs/odoo.log` | Alert-Schreibvorgang und Vorbelastung |
| `logs/container_images.txt` | Image-Stände aller Container |
