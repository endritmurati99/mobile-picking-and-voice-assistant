# Testlauf 11 — neuer Artikel, fünf Fotos, und ein Bildaufruf von 82,9 s

**Datum:** 15.09.2026
**Auftrag:** L1/OUT/00248, Position 3 von 5
**Artikel:** Plate 2x4 grün, SKU 4185178, Produkt 109, Regal B-02, 3 Stück,
Alpin Spielwaren GmbH
**Alert:** QA/0376 (Odoo-Datensatz-ID 377)
**Ergebnis:** `completed` / `scrap`, Konfidenz 1,0 — **Antwort nach 247,9 s, kein Abbruch**

Zeitangaben aus den Container-Logs, UTC.

## 1. Was dieser Lauf prüft

Erster Lauf mit einem Artikel, der in keinem Vorlauf vorkam, und der erste Lauf, in dem die
Budgetbremse **nicht** nach Plan greift, sondern an einem unerwartet teuren Bildaufruf zeigt, was
sie wert ist.

Zwei Fragen:

1. Trägt die Artikelachse bei einem neuen Artikel (grüne Platte statt der bisherigen Steine)?
2. Hält die neue Anruferfrist auch dann, wenn die Aufrufe länger dauern als der Schätzwert?

## 2. Eingangsdaten

Vorlage: Katalogbild aus Odoo (`default_code = 4185178`, 2 048 Byte PNG). ChatGPT erzeugte daraus
fünf Ansichten desselben beschädigten Teils, alle freigestellt auf weiß: schräg von oben wie die
Vorlage, strenge Draufsicht auf die Noppen, Nahaufnahme der Bruchstelle von der Seite, Ansicht von
hinten, Ansicht von unten. Schaden: abgebrochene Noppe, Riss quer über die Platte, abgeplatzte
Ecke.

```
Kategorie:    Artikel beschädigt
Priorität:    Normal
Beschreibung: Testlauf 11: Artikel beschaedigt: Plate 2x4 gruen (SKU 4185178), Regal B-02.
              Noppe abgebrochen, Riss quer ueber die Platte, Ecke abgeplatzt.
              Nicht versandfaehig. Fuenf Fotos angehaengt.
Fotos:        5  (fotos/qa_photo_01.jpg bis _05.jpg, je 1 024 px JPEG, 416 KB gesamt)
```

`QA_MAX_ASSESSMENT_PHOTOS = 5` für diese Messung, danach auf 3 zurückgesetzt.

## 3. Zeitlicher Ablauf

| Zeit (UTC) | Δ zum Start | Ereignis | Dauer |
|---|---|---|---|
| 12:53:31,8 | 0 s | Absenden in der PWA, `POST /api/quality-alerts` → 200 OK | — |
| ≈12:53:34 | ≈2 s | `POST .../webhook/quality-assessment-v2` → 200 OK | — |
| ≈12:53:37 | ≈5 s | Anfrage `assessments/quality` im Backend, Anruferfrist läuft (Ende ≈12:57:52) | — |
| 12:54:54,8 | 83,0 s | Textbewertung `qwen2.5:7b` fertig (950 Token) | **74,94 s** |
| 12:55:09,4 | 97,6 s | `embed_katalog`: 47 Artikel neu eingebettet — Cache nach dem Odoo-Neustart leer | **13,91 s** |
| 12:55:09,7 | 97,9 s | `embed_abgleich`: **`match`**, 4185178 auf **0,8829**, Abstand 0,0654 | 237 ms |
| 12:56:37,4 | 185,6 s | `vision_probe` Foto 1, `ok: true` | **82,88 s** |
| 12:57:39,7 | 247,9 s | `vision_probe` Foto 2, `ok: true` | **59,11 s** |
| **12:57:39,7** | **247,9 s** | **Antwort an n8n → 200 OK**, `callbacks/status` → 200 OK | — |

Nur **zwei** der fünf Fotos wurden geprüft. Nach Foto 2 blieben rund 13 s bis zur Anruferfrist —
weit unter den veranschlagten 60 s, also kein dritter Aufruf und kein Katalogbildvergleich. Im
ollama-Log steht **kein** `cancel task`.

## 4. Der teure Bildaufruf — und warum er den Lauf nicht gerissen hat

**Foto 1 brauchte 82,88 s.** Das bisherige Band lag bei 42–60 s (Läufe 7 bis 10); der Schätzwert
`vision_call_estimate_ms` von 60 s ist daran gemessen. Dieser Aufruf sprengt ihn um 38 %.

| Aufruf | Modell | ollama | Backend | Token |
|---|---|---|---|---|
| Textbewertung (`task 4`) | qwen2.5:7b | 74,94 s | — | 950 |
| Foto 1 (`task 6`) | gemma4:12b | 81,67 s | **82,88 s** | 519 |
| Foto 2 (`task 69`) | gemma4:12b | 55,97 s | 59,11 s | 513 |

Die Tokenzahlen sind nahezu gleich (519 gegen 513), die Laufzeit unterscheidet sich um 26 s. Das
bestätigt Stolperfalle 9 auf der Zeitachse: **das Bildmodell ist auch in der Dauer nicht stabil**,
nicht nur im Wortlaut.

Entscheidend ist, was daraus folgte: Foto 2 startete um 12:56:37 mit rund 75 s Restzeit, also über
dem Schätzwert — und brauchte 59,11 s. Es passte mit 13 s Reserve. Hätte es wie Foto 1 gedauert,
hätte `_in_restzeit` es bei 75 s gekappt, und der **fertige Befund von Foto 1 wäre trotzdem in
Odoo gelandet**. Genau dieser Fall hat in Lauf 9 noch alles gekostet.

**Gegenrechnung ohne den Fix:** Die Bildstufe begann um ≈12:55:10, das alte Bildbudget von 240 s
hätte also bis ≈12:59:10 gereicht. Nach Foto 2 (12:57:39) waren davon erst 149 s verbraucht — die
alte Prüfung „ist das Budget erschöpft" hätte Foto 3 gestartet. Der n8n-Knoten hätte um ≈12:58:07
abgebrochen, mitten im Aufruf, und **beide fertigen Bildbefunde wären verloren gewesen**. Lauf 11
wäre ohne den Fix mit hoher Wahrscheinlichkeit ein zweiter Lauf 9 geworden.

## 5. Ergebnis der Systembewertung

```
ai_evaluation_status:  completed
ai_disposition:        scrap
ai_confidence:         1.0
ai_summary:            Abgebrochene Noppe und Riss machen den Artikel unbrauchbar.
ai_photo_analysis:     Schaden: SICHTBAR -- Riss, abgebrochene Noppe.
                       Zustand: nicht verglichen (Zeitbudget erschöpft).
                       Fotos: 3 weitere ungeprüft.
ai_recommended_action: Ware sperren, aussondern und Schichtleitung informieren.
ai_model:              qwen2.5:7b
ai_last_analyzed_at:   2026-09-15 12:57:39
```

Die Befunde bleiben kurz („Riss, abgebrochene Noppe"), die Wortgrenze hält. Die drei
ungeprüften Fotos stehen im Klartext.

## 6. Artikelachse: erster Lauf mit einer Platte in Grün

| Rang | Artikel | Wert |
|---|---|---|
| 1 | **4185178 (erwartet)** | **0,8829** |
| 2 | 6004979 | 0,8175 |
| 3 | 4183780 (Brick 2x2 grün, derselbe Auftrag) | 0,8083 |

Abstand 0,0654 — vergleichbar mit Lauf 4 (0,0694) und deutlich über dem Grenzfall aus Lauf 5
(0,0000, Urteil `unsicher`). Bemerkenswert: Auf Platz 3 steht ein Teil **derselben Farbe** aus
demselben Auftrag. Die Farbe zieht die Kandidaten zusammen, die Form trennt sie wieder.

## 7. Vergleich mit den Vorläufen

| | Lauf 9 | Lauf 10 | Lauf 11 |
|---|---|---|---|
| Artikel | Brick Bow 2x3x1 hellblau | derselbe | **Plate 2x4 grün (neu)** |
| Fotos angenommen | 5 | 5 | 5 |
| Fotos geprüft | 3 | 3 | **2** |
| Textbewertung | 51,14 s | 54,16 s | **74,94 s** |
| teuerster Bildaufruf | 59,8 s | 47,1 s | **82,9 s** |
| Laufzeit bis Antwort | **Abbruch 270,1 s** | 210,9 s | **247,9 s** |
| Auslastung Knotenlimit | 100 % (gerissen) | 78 % | 92 % |
| Ergebnis | `assessment unavailable` | `completed` | `completed` |

Lauf 11 lief 37 s länger als Lauf 10 bei **weniger** geprüften Fotos. Ursache sind die beiden
teuren Stufen: Textbewertung +20,8 s und Foto 1 +35,8 s gegenüber Lauf 10.

## 8. Abweichungen und bekannte Vorbelastung

* `embed_katalog` musste erneut 47 Artikel einbetten (13,91 s), weil der Odoo-Neustart für die
  Fotoobergrenze den Cache geleert hat. Ohne diesen Posten läge die Antwort bei rund 234 s.
* Odoo protokolliert weiterhin alle 13–15 s
  `RuntimeError: Couldn't bind the websocket ... (evented port 8072)`. Unabhängig von der Kette.
* Vor dem Lauf war Odoo für die PWA nicht erreichbar, weil ein früherer
  `docker compose up -d odoo` **ohne** `docker-compose.dev.yml` lief und der Container dadurch
  Portfreigabe und `edge-net` verloren hatte. Behoben vor dem Lauf, siehe Stolperfalle 11 im
  Skill. Auf die Messung hat es keinen Einfluss — die Kette läuft über `core-net`.

## 9. Belege

* `fotos/` — die fünf hochgeladenen JPEGs, `fotos_original/` die PNGs von ChatGPT
* `kontaktabzug.jpg`, `pruefsummen.txt`
* `run11_plate2x4_gruen.png` — das Katalogbild aus Odoo
* `logs/backend.log`, `logs/ollama.log`, `logs/odoo.log`

## 10. Was dieser Lauf für den Schätzwert bedeutet

`vision_call_estimate_ms` steht auf 60 s und war damit für Foto 1 dieses Laufs **zu niedrig**. Das
Band ist nach elf Läufen 42–83 s. Zwei Folgerungen:

1. Ein fester Schätzwert kann nicht beides: 60 s lässt Aufrufe starten, die 83 s brauchen, und
   83 s würde in ruhigen Läufen Fotos liegen lassen, die gepasst hätten. **Ein gleitender
   Mittelwert der letzten Aufrufe je Modell wäre die ehrlichere Grenze.**
2. Dass der Lauf trotzdem durchkam, liegt an der zweiten Schranke: `_in_restzeit` kappt einen
   Aufruf, der die Frist reißt, und rettet die bereits fertigen Befunde. Der Schätzwert verhindert
   verlorene Rechenzeit, die Kappung verhindert verlorene Ergebnisse. Erst beide zusammen tragen.
