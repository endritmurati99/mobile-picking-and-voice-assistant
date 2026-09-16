# Testlauf 18 — Soll-Befund aus dem Cache

**Datum:** 16.09.2026
**Alert:** QA/0383
**Auftrag:** L1/OUT/00248, Position 4 von 5
**Artikel:** Brick 2x2 grün, SKU 4183780, Regal C-02
**Fotos:** 3 (201 KB), **MD5-identisch mit den Läufen 15, 16 und 17**

---

## 1. Was dieser Lauf prüft

Eine Frage: **Überlebt der Zustandsbefund des Katalogbilds einen Backend-Neustart?**

Lauf 17 hat den Cache erstmals gefüllt. Danach wurde das Backend um 10:13:59 neu gestartet —
derselbe Vorgang, der den Speicher bisher leerte. ollama blieb dabei warm, damit der Kaltstart die
Messung nicht überlagert.

Alles andere ist gegen Lauf 17 konstant: Auftrag, Position, Fotos, Text bis auf die Laufnummer.

---

## 2. Zeitlicher Ablauf

| Zeit | seit Start | Dauer | Ereignis |
|---|---|---|---|
| **10:18:42,9** | 0 s | — | **Meldung abgesendet** |
| 10:18:45,6 | 2,7 s | — | `POST /webhook/quality-assessment-v2` → 200 |
| 10:19:27,63 | 45 s | 0,23 s | `embed_abgleich` Foto 1: `unsicher`, `zu_dicht`, 0,0155 |
| 10:19:27,63 | 45 s | — | `article_retry`, `foto: 1, von: 3` |
| 10:19:27,86 | 45 s | 0,23 s | `embed_abgleich` Foto 2: **`match`**, 0,0362 |
| 10:20:12,1 | 89 s | 41,8 s | Schadensprüfung Foto 1 |
| 10:20:53,7 | 131 s | 36,6 s | Schadensprüfung Foto 2 |
| 10:21:32,75 | 170 s | 36,6 s | Schadensprüfung Foto 3 |
| 10:21:32,76 | 170 s | **0,006 s** | **`soll_cache_geladen`, `eintraege: 1`** |
| 10:21:36,69 | 174 s | 3,9 s | `condition_compare` |
| 10:21:36 | 174 s | — | Alert geschrieben |

**Gesamtdauer 2 min 52 s.**

---

## 3. Befund: (c) trägt

```json
{"event_type": "soll_cache_geladen", "eintraege": 1,
 "pfad": "/var/cache/pwr/soll_befunde.json"}
```

**Es gibt keinen vierten Bildaufruf.** In Lauf 17 stand an dieser Stelle:

```json
{"event_type": "vision_probe", "model": "gemma4:12b", "images": 1, "duration_ms": 22214}
```

Der Zustandsvergleich brauchte hier **3,9 s statt 22,2 s**, weil nur noch der Textvergleich der
beiden Beschreibungen zu leisten war. Der Soll-Befund lag fertig auf der Platte.

Damit ist der offene Punkt 4 der Gesamtübersicht erledigt — allerdings anders als dort
vorgeschlagen: nicht durch einen Warmlauf über alle Artikel beim Start (44 Artikel mal rund 22 s
wären gut 16 Minuten Startzeit), sondern durch eine Datei neben dem Speicher. Der Befund wird
weiterhin genau einmal je Artikel bezahlt — aber nur noch einmal überhaupt, nicht einmal je
Neustart.

---

## 4. Die drei Läufe nebeneinander

Gleiche Fotos, gleicher Auftrag, gleicher Text.

| | Lauf 16 | Lauf 17 | Lauf 18 |
|---|---|---|---|
| Gesamt | 4 min 35 s | 4 min 4 s | **2 min 52 s** |
| Bildaufrufe nach Absenden | 5 | 4 | **3** |
| Artikelachse | 59,8 s (`unsicher`) | 0,25 s (`match`) | 0,46 s (`match`) |
| Katalogbild | 22,0 s | 22,2 s | **aus dem Cache** |
| Zustandsvergleich | 17,3 s | 17,0 s | 3,9 s |
| Fotos geprüft | 3 von 3 | 3 von 3 | 3 von 3 |
| Endzustand | `review_required` | `review_required` | `review_required` |

**103 s schneller als Lauf 16, ein Minus von 37 %** — bei gleichem Ergebnis.

Die Schadensprüfung selbst ist unverändert teuer (115,0 s für drei Fotos gegen 108,1 s in Lauf 16,
innerhalb der bekannten Streuung). Der gesamte Gewinn stammt aus zwei Stufen, die gar nicht mehr
stattfinden: die Bildbeschreibung für den Artikelvergleich und der Katalogbildaufruf.

**Vierte Wiederholung, vierte identische Entscheidung.** Die Kette ist an dieser Stelle
reproduzierbar, obwohl das Bildmodell im Wortlaut schwankt.

---

## 5. Was offen bleibt

Die in Lauf 17 gefundene Verdrängung ist **nicht** behoben: ein funktionsfähiger Sprach-Warmlauf
wirft bei `OLLAMA_MAX_LOADED_MODELS = 2` das Bildmodell aus dem Speicher und kostet 121 s
Nachladen. In diesem Lauf fiel das nicht ins Gewicht, weil zwischen Neustart und Meldung genug
Zeit lag. Bei einer Vorführung, in der sofort gemeldet wird, fiele es an.

Zu entscheiden ist das mit einer Speichermessung bei drei geladenen Modellen, nicht mit den
Modellgrößen auf dem Papier.

---

## 6. Belege

| Datei | Inhalt |
|---|---|
| `fotos/run18_photo_01..03.jpg` | die drei gemeldeten Fotos |
| `pruefsummen.txt` | MD5, identisch mit den Läufen 15 bis 17 |
| `logs/backend.log` | `soll_cache_geladen`, `article_retry`, Zeitstempel |
| `logs/ollama.log` | Modellaufrufe — drei statt fünf |
| `logs/odoo.log` | Alert-Schreibvorgang |
| `logs/container_images.txt` | Image-Stände |
