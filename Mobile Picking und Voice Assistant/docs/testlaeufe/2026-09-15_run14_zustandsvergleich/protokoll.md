# Testlauf 14 — der Zustandsvergleich läuft nicht mehr umsonst

**Datum:** 15.09.2026
**Auftrag:** L1/OUT/00248, Position 5 von 5
**Artikel:** Brick 2x2 hellblau, SKU 6294237, Produkt 77, Regal D-01
**Alert:** QA/0379 (Odoo-Datensatz-ID 380)
**Ergebnis:** `completed` / `scrap`, Konfidenz 0,95 — Antwort nach 244,2 s

Zeitangaben aus den Container-Logs, UTC.

## 1. Was dieser Lauf prüft

Gegenprobe zu Lauf 13 mit **denselben fünf Bilddateien** (MD5 identisch, nur unter neuem Namen
hochgeladen). Verändert wurde allein der Code, und zwar an zwei Stellen:

1. **Der Zustandsvergleich läuft nur noch bei `intact`.** Er darf ausschließlich eskalieren; steht
   `damaged` fest, kann er am Urteil nichts mehr ändern. Bis dahin kostete er trotzdem einen
   vollen Bildaufruf am Ende der Kette und kam deshalb in den Läufen 9 bis 13 **kein einziges Mal**
   mehr an die Reihe.
2. **Das Glossar setzt Zweiwortbefunde zusammen.** In Lauf 13 stand `gouged stud` englisch im
   Odoo-Formular.

## 2. Zeitlicher Ablauf

| Zeit (UTC) | Δ zum Start | Ereignis | Dauer |
|---|---|---|---|
| 14:11:57,4 | 0 s | Absenden in der PWA | — |
| 14:12:47,3 | 49,9 s | `embed_abgleich`: **`match`**, 6294237 auf **0,9139**, Abstand 0,0372 | 220 ms |
| 14:13:34,6 | 97,1 s | `vision_probe` Foto 1 | 43,92 s |
| 14:14:18,8 | 141,4 s | `vision_probe` Foto 2 | 42,53 s |
| 14:15:06,8 | 189,4 s | `vision_probe` Foto 3 | 44,60 s |
| 14:16:01,7 | 244,2 s | `vision_probe` Foto 4, danach Antwort und `callbacks/status` | 51,44 s |

Am Ende zwei Logzeilen, beide neu:

```json
{"event_type": "vision_budget_stop", "stelle": "schadenspruefung", "restzeit_s": 25.9, "schaetzung_s": 51.4, "offene_fotos": 1}
{"event_type": "condition_compare_skipped", "grund": "schaden_bereits_sichtbar"}
```

## 3. Ergebnis der Systembewertung

```
ai_evaluation_status:  completed
ai_disposition:        scrap
ai_confidence:         0.95
ai_summary:            Noppe abgebrochen und eingespannt, nicht mehr versandfähig.
ai_photo_analysis:     Schaden: SICHTBAR -- Riss, gebrochene Kante, abgeplatzte Kante,
                       ausgekerbte Noppe.
                       Fotos: 1 weitere ungeprüft.
ai_recommended_action: Ware sperren, aussondern und Schichtleitung informieren.
```

**Zwei Unterschiede zum Formular aus Lauf 13:**

* `gouged stud` heißt jetzt **`ausgekerbte Noppe`**. Die Zusammensetzung aus Zustandswort und
  Bauteil greift.
* Die Zeile `Zustand: nicht verglichen (Zeitbudget erschöpft).` **fehlt**. Sie fehlt nicht, weil
  sie unterdrückt wird, sondern weil der Vergleich gar nicht mehr angefordert wurde. Dass die
  Kette ihn nicht brauchte, ist eine Aussage über die Kette und gehört ins Log, nicht in ein
  Formular, das ein Mensch im Lager liest.

## 4. Vergleich mit Lauf 13

| | Lauf 13 | Lauf 14 |
|---|---|---|
| Eingabe | 5 Fotos | **dieselben** 5 Fotos (MD5 gleich) |
| Artikelabgleich | `match`, 0,9139, Abstand 0,0372 | **identisch auf vier Nachkommastellen** |
| Fotos geprüft | 5 von 5 | 4 von 5 |
| Bildaufrufe | 45,8 / 37,5 / 39,6 / 42,3 / 40,6 s | 43,9 / 42,5 / 44,6 / **51,4** s |
| Laufzeit bis Antwort | 248,3 s | 244,2 s |
| Zustandsvergleich | „Zeitbudget erschöpft" | **nicht nötig, übersprungen** |
| englische Befunde | `gouged stud` | keine |

**Das vierte statt fünfte Foto liegt nicht an den Änderungen.** Vor dem Lauf wurde das Backend für
den neuen Code neu gestartet, die Messreihe war also leer: die ersten drei Aufrufe rechneten gegen
die Vorgabe von 60 s, und Foto 4 brauchte mit 51,44 s länger als jeder Aufruf in Lauf 13. Danach
blieben 25,9 s gegen eine Schätzung von 51,4 s.

Damit ist auch der dritte offene Punkt aus Lauf 13 vermessen statt nur behauptet: **eine leere
Messreihe kostet genau ein Foto in der ersten Meldung nach einem Neustart.**

Dass der Artikelabgleich auf vier Nachkommastellen denselben Wert liefert, bestätigt erneut: die
Einbettung ist reproduzierbar, das Bildmodell nicht (37,5 bis 51,4 s für dasselbe Foto in zwei
Läufen).

## 5. Was der Lauf nicht zeigt

**Den Zustandsvergleich in Aktion.** Er läuft jetzt nur noch, wenn alle geprüften Fotos `intact`
melden — dieser Lauf zeigt fünf beschädigte Fotos, also den Fall, in dem er zu Recht entfällt.
Für den anderen Fall braucht es Fotos eines **heilen** Teils mit einem sauber abgebrochenen Eck;
das ist der nächste sinnvolle Lauf.

## 6. Belege

* `fotos/` — die fünf JPEGs, inhaltsgleich mit `2026-09-15_run13_brick2x2_hellblau/fotos/`
* `logs/backend.log` mit `vision_budget_stop` und `condition_compare_skipped`
* `logs/ollama.log`, `logs/odoo.log`
* Selbstprüfung: `.claude/skills/qa-testlauf/scripts/pruef_budget.py`, Fälle 9 und 10
