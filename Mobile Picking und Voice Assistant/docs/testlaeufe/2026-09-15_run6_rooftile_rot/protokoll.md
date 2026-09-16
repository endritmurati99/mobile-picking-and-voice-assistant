# Testlauf 6 — zwei Fotos, neues Produkt

**Datum:** 15.09.2026
**Auftrag:** L1/OUT/00295, Position 2 von 5
**Artikel:** Roof Tile 4x2 Deg. 45 W/O Knobs rot, SKU 6256703, Produkt 114, Regal A-02,
3 Stück, Zürich Modellbau AG
**Alert:** QA/0370 (Odoo-Datensatz-ID 371)
**Ergebnis:** `ai_evaluation_status = completed`, **2 min 42 s**

Erster Lauf mit zwei Fotos. Zeitangaben aus den Container-Logs, UTC.

## 1. Was dieser Lauf prüft

Zwei Fragen: Sprengt ein zweites Foto das Zeitbudget? Und trägt die Artikelachse auch bei einem
Teil, dessen Form im Katalog eindeutig ist — nachdem Lauf 5 an zwei formgleichen Artikeln
hängenblieb?

## 2. Eingangsdaten

Vorlage: Katalogbild aus Odoo (`default_code = 6256703`, `image_1920`, 2 100 Byte PNG). ChatGPT
erzeugte daraus zwei Ansichten desselben beschädigten Steins, beide freigestellt auf weiß:
Schrägansicht und Nahaufnahme der beschädigten Seite. Schaden: abgeplatzte Ecke an der
Schrägfläche, Riss quer über die Schräge.

```
Kategorie:    Artikel beschädigt
Priorität:    Normal
Beschreibung: Artikel beschaedigt: Roof Tile 4x2 Deg. 45 W/O Knobs rot (SKU 6256703),
              Regal A-02. Ecke an der Schraegflaeche abgeplatzt, Riss quer ueber
              die Schraege. Nicht versandfaehig. Zwei Fotos angehaengt.
Fotos:        2  (fotos/qa_photo_01.jpg, fotos/qa_photo_02.jpg, je 1 024 px JPEG)
```

## 3. Zeitlicher Ablauf

| Zeit (UTC) | Δ zum Start | Ereignis | Dauer |
|---|---|---|---|
| 07:44:56,984 | 0 s | `POST /api/quality-alerts` → 200 OK | — |
| 07:44:57,844 | 0,9 s | `POST /api/internal/n8n/v2/events/accept` → 200 OK | — |
| 07:44:57,847 | 0,9 s | `POST http://n8n:5678/webhook/quality-assessment-v2` → 200 OK | — |
| 07:45:21,822 | 24,8 s | Textbewertung `qwen2.5:7b` (`/api/chat`) fertig | **23,95 s** |
| 07:45:22,692 | 25,7 s | `embed_abgleich`: Urteil **`match`** | **0,741 s** |
| 07:45:22,692 | 25,7 s | `article_compare`: `same_article = true`, **kein Bildaufruf nötig** | — |
| 07:46:05,985 | 69,0 s | `vision_probe` Foto 1 (Bilddekodierung 12,30 s), `ok: true` | **43,295 s** |
| 07:46:58,732 | 121,7 s | `vision_probe` Foto 2 (Bilddekodierung 18,36 s), `ok: true` | **52,749 s** |
| 07:47:31,952 | 155,0 s | `vision_probe` Katalogbild für den Soll-Vergleich (6,18 s), `ok: true` | **33,219 s** |
| 07:47:38,292 | 161,3 s | Abschließender Textabgleich `qwen2.5:7b` | **6,06 s** |
| 07:47:38,295 | 161,3 s | `POST /api/internal/n8n/v2/assessments/quality` → 200 OK | — |
| 07:47:38,387 | 161,4 s | `POST /api/internal/n8n/v2/callbacks/status` → 200 OK | — |
| 07:47:38 | 162 s | `ai_last_analyzed_at` in Odoo gesetzt | — |

**Gesamtlaufzeit: 2 min 42 s.** Keine Exception, kein Timeout, kein `signal: killed`.

## 4. Ergebnis der Systembewertung

```
ai_evaluation_status:  completed
ai_disposition:        scrap
ai_confidence:         0.95
ai_summary:            Abplatzer und nicht versandfahige Beschädigung sprechen
                       von Unbrauchbarkeit.
ai_recommended_action: Ware sperren, aussondern und Schichtleitung informieren.
ai_photo_analysis:
  Schaden: SICHTBAR -- crack, broken edge, crack, split.
  Zustand: Abgleich mit dem Katalogbild bestätigt den Befund
           (Es gibt eine Kerbe, die im SOLL nicht vorkommt.)
```

Die Artikelzeile fehlt — der Einbettungsabgleich hat mit `match` entschieden, damit entfällt jede
Erklärung zur Artikelachse im Klartext.

## 5. Die Artikelachse trägt zum ersten Mal

```json
{"event_type": "embed_abgleich", "urteil": "match", "grund_art": "treffer",
 "erwartet": "6256703",
 "rang": [["6256703", 0.846], ["343721", 0.606], ["301121", 0.594]],
 "abstand": 0.2396}
```

Abstand zum Zweiten: **0,2396**. In Lauf 5 waren es 0,0027 zwischen zwei Artikeln derselben
Formfamilie. Der Dachstein hat eine Silhouette, die im Katalog kein zweites Mal vorkommt — genau
dort, wo DINOv2 formdominant ist, trägt das Verfahren.

Das ist der vierte Datenpunkt und rundet das Bild:

| Foto | Urteil | Platz 1 | Abstand |
|---|---|---|---|
| Lagerfoto, Brick 1x2x2 weiß (Läufe 2, 3) | `mismatch` | falscher Artikel | — |
| freigestellt, Brick 1x2x2 weiß (Lauf 4) | `match` | richtig, 0,8723 | 0,0694 |
| freigestellt, Brick 2x4 Bows gelb (Lauf 5) | `unsicher` | richtig, 0,9318 | 0,0000 |
| **freigestellt, Roof Tile 4x2 rot (Lauf 6)** | **`match`** | **richtig, 0,846** | **0,2396** |

Der Hintergrund entscheidet, ob der richtige Artikel überhaupt vorne landet. Die Formvielfalt des
Katalogs entscheidet, ob der Abstand für ein Urteil reicht.

## 6. Was das zweite Foto kostet

Drei Bildaufrufe, 129,3 s zusammen:

| Aufruf | Zweck | Dauer |
|---|---|---|
| 1 | Schadensprüfung Foto 1 | 43,30 s |
| 2 | **Schadensprüfung Foto 2** | **52,75 s** |
| 3 | Katalogbild für den Soll-Vergleich | 33,22 s |

`_check_article` sieht nur das erste Foto (`n8n_v2.py:321`), `_check_damage` geht über alle
(`n8n_v2.py:689`), der Zustandsvergleich läuft einmal je Meldung. **Das zweite Foto kostet also
genau einen zusätzlichen Bildaufruf: 52,75 s.**

Hochgerechnet: Jedes weitere Foto kostet 40–55 s. Bei vier Fotos wären es rund 110 s reine
Schadensprüfung plus Zustandsvergleich — das Budget `vision_budget_ms = 240000` hätte dann noch
20–30 s Reserve. Der Code zählt ungeprüfte Fotos bereits (`n8n_v2.py:727-730`); eine harte
Obergrenze von drei geprüften Fotos je Meldung würde das Budget absichern, bevor es eng wird.

## 7. Reserven zu den Grenzwerten

| Grenze | Wert | verbraucht | Auslastung |
|---|---|---|---|
| n8n-Knoten `PWR Signed Assessment` | 270 s | 160,4 s | 59 % |
| `vision_budget_ms` (alle Bildaufrufe) | 240 s | 129,3 s | 54 % |
| `vision_timeout_ms` (größter Einzelaufruf) | 200 s | 52,7 s | 26 % |
| `LLM_TIMEOUT_MS` (größter Textaufruf) | 90 s | 24,0 s | 27 % |

Das zweite Foto hat das Budget **nicht** gesprengt. Es blieben 109 s Reserve zum Knotenlimit.

## 8. Vergleich mit Lauf 5

| | Lauf 5 (1 Foto, gelb) | Lauf 6 (2 Fotos, rot) |
|---|---|---|
| Artikelachse | `unsicher`, Abstand 0,0027 | **`match`**, Abstand 0,2396 |
| Bildaufrufe | 3 | 3 |
| davon ohne Beitrag zum Urteil | **44,4 s** | 0 s |
| Textaufrufe | 2 (47,7 s + 21,6 s) | 2 (24,0 s + 6,1 s) |
| Gesamtlaufzeit | 3 min 15 s | **2 min 42 s** |

Der Lauf mit **zwei** Fotos war 33 s **schneller** als der mit einem. Grund: In Lauf 5 stand der
Einbettungsabgleich auf `unsicher` und löste den bildgestützten Artikelvergleich aus — zwei
Bildaufrufe und ein Textvergleich, von denen einer nichts lieferte. In Lauf 6 entschied die
Einbettung in 0,741 s, und dieser ganze Zweig entfiel.

**Die Fotoanzahl ist nicht der Kostentreiber. Der Kostentreiber ist, ob die Artikelachse über die
Einbettung entschieden werden kann.**

## 9. Was sich daraus für die Kette ergibt

1. **Soll-Befund vorwärmen.** Der Zustandsvergleich kostete 33,2 s, weil der Katalogbild-Befund
   für Artikel 6256703 noch nicht im Prozess-Cache `_SOLL_BEFUNDE` lag (`n8n_v2.py:812`). Der
   Cache überlebt keinen Backend-Neustart. Ein Warmlauf über die aktiven Artikel nach dem Start
   spart diese 33,2 s bei der jeweils ersten Meldung je Artikel.
2. **Der Einbettungsdienst ist der Hebel, nicht die Modelle.** 0,741 s gegen 44–165 s für den
   Text-Fallback. Fällt `embed` aus, reaktiviert das den teuersten Pfad. Verfügbarkeit dieses
   Dienstes ist damit wichtiger als jede Modellwahl.
3. **Fotoanzahl deckeln.** Drei geprüfte Fotos je Meldung halten das Bildbudget sicher; die
   Zählung der übersprungenen Fotos steht bereits im Code.

## 10. Belege im Ordner

| Datei | Inhalt |
|---|---|
| `run6_rooftile_rot_p114.png` | Katalogbild aus Odoo, Vorlage |
| `fotos_original/run6_damage_01.png`, `_02.png` | von ChatGPT erzeugte Schadensbilder |
| `fotos/qa_photo_01.jpg`, `qa_photo_02.jpg` | auf 1 024 px skalierte Fassungen, Eingabe der Meldung |
| `kontaktabzug.jpg` | beide Ansichten nebeneinander |
| `pruefsummen.txt` | MD5-Summen |
| `logs/` | backend, ollama, n8n, odoo, Containerstände |
