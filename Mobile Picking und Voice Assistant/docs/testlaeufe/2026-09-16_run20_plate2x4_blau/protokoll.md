# Testlauf 20 — Abschlusslauf mit sichtbarem Schaden

**Datum:** 16.09.2026
**Alert:** QA/0384 (id 385)
**Auftrag:** L1/OUT/00303, Position 3 von 6
**Artikel:** Plate 2x4 blau, SKU 4216758, Regal B-01, 1 Stück, Meyer Spielwaren KG
**Fotos:** 3 (260 KB), **MD5-identisch mit Lauf 8** vom 15.09.
**Fotoobergrenze:** `QA_MAX_ASSESSMENT_PHOTOS=3` (Produktivwert)

---

## 1. Was dieser Lauf prüft

Der Abschlusslauf der Reihe. Alle Änderungen vom 16.09. zusammen, auf **Material, das sie nie
gesehen haben**, und mit einem Schaden, den das Bildmodell auch erkennt:

- Vorwärmen beim Start (Lauf 16)
- Artikelsuche über mehrere Fotos (Lauf 17)
- Soll-Befund-Cache über Neustarts (Lauf 18)
- Drei Modellplätze (Lauf 19)

Andere Formfamilie als die Läufe 15 bis 19 (Plate statt Brick), andere Farbe, und vor allem ein
**ausgefranster Riss** statt des sauberen Bruchs, der dort an der Wahrnehmungsgrenze des Modells
lag.

### Einschränkung, die dieser Lauf hat

**Es sind keine neuen Fotos.** ChatGPT antwortete auf zwei Versuche mit
`You've hit your rate limit.`, sodass für den vorgesehenen Artikel `Brick Round 2x2x2 weiß`
(SKU 6096680) keine Schadensfotos erzeugt werden konnten. Die benutzten Fotos stammen aus Lauf 8.

Der Artikel ist damit **neu gegenüber der Serie 15 bis 19**, aber nicht neu für die Messreihe
insgesamt. Der runde Stein bleibt offen; Katalogbild und Auftrag liegen unter
`2026-09-16_run20_brickround_weiss/` bereit.

---

## 2. Eingangsdaten

```
Kategorie:    Artikel beschädigt
Priorität:    Normal
Beschreibung: Testlauf 20: Artikel beschaedigt: Plate 2x4 blau (SKU 4216758), Regal B-01.
              Riss quer durch die Platte, Kante ausgefranst. Nicht versandfaehig.
              Drei Fotos angehaengt.
Fotos:        3  (260 KB gesamt)
```

Dateinamen `run20_photo_01..03.jpg` statt `qa_photo_01..03.jpg` — der Idempotenzschlüssel enthält
`Dateiname:Größe`, gleiche Namen hätten den Alert aus Lauf 8 zurückgeliefert.

---

## 3. Zeitlicher Ablauf

| Zeit | seit Start | Dauer | Ereignis | Quelle |
|---|---|---|---|---|
| **11:56:49,0** | 0 s | — | **Meldung abgesendet** | Browser |
| 11:57:10 | 21 s | 17,1 s | Textbewertung (Disposition) | ollama.log |
| 11:57:21,8 | 33 s | 0,24 s | `embed_abgleich` Foto 1: **`match`**, Abstand 0,0793 | backend.log |
| 11:58:00,8 | 72 s | 36,8 s | Schadensprüfung Foto 1 | backend.log |
| 11:58:45,4 | 116 s | 40,4 s | Schadensprüfung Foto 2 | backend.log |
| 11:59:20,8 | 152 s | 33,3 s | Schadensprüfung Foto 3 | backend.log |
| 11:59:20,8 | 152 s | — | `condition_compare_skipped`, `schaden_bereits_sichtbar` | backend.log |
| 11:59:20 | 151 s | — | Alert geschrieben | Odoo |

**Gesamtdauer 2 min 31 s** — der schnellste vollständige Lauf der Reihe.

Vier Modellaufrufe insgesamt: eine Textbewertung und drei Schadensprüfungen. Keine
Bildbeschreibung für den Artikelvergleich, kein Katalogbildaufruf, kein Zustandsvergleich.

---

## 4. Ergebnis

```
name:                   QA/0384
ai_evaluation_status:   completed
ai_disposition:         scrap
ai_confidence:          0.9
ai_summary:             Riss quer durch die Platte: unbrauchbar.
ai_photo_analysis:      Schaden: SICHTBAR -- Riss, gebrochene Kante, fehlende Noppe,
                        gebrochene Stelle.
ai_recommended_action:  Ware sperren, aussondern und Schichtleitung informieren.
ai_provider:            ollama-local
ai_model:               qwen2.5:7b
ai_last_analyzed_at:    2026-09-16 11:59:20
```

---

## 5. Befunde

### 5.1 Die Schadensachse trägt — zum ersten Mal in dieser Serie

Die Läufe 15 bis 19 endeten alle in `review_required` über den Widerspruchszweig, weil das
Bildmodell das sauber fehlende Eck nicht sah. Hier findet es den Schaden auf Anhieb, und Text- und
Bildurteil stimmen überein: `scrap` aus der Meldung, `SICHTBAR` aus den Fotos. Kein Widerspruch,
also `completed` statt `review_required`.

Das bestätigt die in Lauf 15 gezogene Grenze von der anderen Seite: **die Kette erkennt
Oberflächenschäden zuverlässig, fehlende Geometrie nicht.** Ein Riss mit ausgefranster Kante ist
ein Oberflächenschaden.

### 5.2 Der Glossar-Zweig arbeitet

`Riss, gebrochene Kante, fehlende Noppe, gebrochene Stelle` — vier englische Modellbegriffe aus
drei Fotos, entdoppelt und übersetzt. Die zusammengesetzte Übersetzung aus Lauf 14 greift auch auf
Begriffen, die vorher nicht vorkamen.

### 5.3 Die Artikelsuche verhält sich richtig, indem sie nichts tut

`match` auf Foto 1 bei einem Abstand von 0,0793 — **kein `article_retry`**. Das ist die richtige
Gegenprobe zu Lauf 17: der Zweig löst nur bei `zu_dicht` aus und kostet sonst nichts.

### 5.4 Der Zustandsvergleich wird übersprungen, und das ist richtig

```json
{"event_type": "condition_compare_skipped", "grund": "schaden_bereits_sichtbar"}
```

Die Entscheidung aus Lauf 14: Wer den Schaden schon sieht, braucht den Soll-Ist-Vergleich nicht.
Das spart hier den Katalogbildaufruf (22 s in Lauf 17) **und** den Textvergleich (17 s) — zusammen
rund 39 s, die in einem Fall ohne sichtbaren Schaden angefallen wären.

### 5.5 Vergleich mit Lauf 8 — dieselben Fotos, 39 s schneller

| | Lauf 8 (15.09.) | Lauf 20 (16.09.) |
|---|---|---|
| Gesamt | 3 min 10 s | **2 min 31 s** |
| Fotos hochgeladen | 4 | 3 |
| Fotos geprüft | 3 | 3 |
| Artikelachse | `match` | `match` |
| Endzustand | `completed` | `completed` |
| Disposition | `scrap` | `scrap` |

Gleiches Urteil auf gleichen Bildern, über einen Tag und vier Codeänderungen hinweg.

---

## 6. Die Reihe auf einen Blick

| Lauf | Fotos | Bildaufrufe | Dauer | Endzustand |
|---|---|---|---|---|
| 8 | 3 geprüft | 4 | 3 min 10 s | `completed` |
| 16 | 3 | 5 | 4 min 35 s | `review_required` |
| 17 | 3 | 4 | 4 min 4 s | `review_required` |
| 18 | 3 | 3 | 2 min 52 s | `review_required` |
| **20** | 3 | **3** | **2 min 31 s** | `completed` |

Die Bildaufrufe sind der Preis, und sie sind von fünf auf drei gefallen. Die Schadensprüfung selbst
ist unverändert teuer — 33 bis 40 s je Foto, wie am ersten Tag.

---

## 7. Vorbelastung

Odoo protokolliert weiterhin alle 13–15 Sekunden
`RuntimeError: Couldn't bind the websocket. Is the connection opened on the evented port (8072)?`
mit `"GET /websocket" 500`. Unabhängig von der Meldungskette.

---

## 8. Belege

| Datei | Inhalt |
|---|---|
| `fotos/run20_photo_01..03.jpg` | die drei gemeldeten Fotos |
| `pruefsummen.txt` | MD5, identisch mit Lauf 8 |
| `logs/backend.log` | Kette, `condition_compare_skipped`, Zeitstempel |
| `logs/ollama.log` | vier Modellaufrufe |
| `logs/odoo.log` | Alert-Schreibvorgang |
| `logs/container_images.txt` | Image-Stände |
