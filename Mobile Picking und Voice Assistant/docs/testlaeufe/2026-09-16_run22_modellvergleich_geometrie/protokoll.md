# Lauf 22 — Modellvergleich bei fehlender Geometrie

**Datum:** 16.09.2026
**Art:** Messung ohne Kettenlauf (Abschnitt 6 des Skills)
**Offener Punkt:** 15 der Gesamtübersicht

## Was der Lauf prüft

Lauf 15 hat gezeigt, dass `gemma4:12b` ein sauber abgebrochenes Eck nicht sieht. Offen blieb,
ob das am Modell liegt oder an der Aufgabenstellung. Der einzige vorliegende Modellvergleich
(14.08., `gemma4:12b` 4/4 gegen `qwen2.5vl:7b` 2/4) lief über acht Bilder, die alle
Oberflächenschäden zeigten — für fehlende Geometrie gab es keine Zahl.

Eine Variable: das Bildmodell. Konstant: die drei Fotos aus Lauf 15 (identische Dateien,
`qa_photo_01..03.jpg`), die Produktiv-Prompts, `temperature: 0`, `num_ctx 8192`, `num_thread 8`.

## Korrektur am Messstand vor dem Lauf

`bench_vision_models.py` setzte **`num_thread` nicht**. Es maß damit mit 14 Threads, während die
Kette mit 8 arbeitet — gemessener Unterschied 1,21 tok/s gegen 7,40 tok/s (Abschnitt 2 der
Gesamtübersicht). Alle früher mit diesem Skript erzeugten Zahlen, auch der Vergleich vom 14.08.,
sind deshalb nicht mit Kettenläufen vergleichbar. Behoben: `NUM_THREAD = 8` mit Kommentar auf den
Messwert.

## Ergebnis: beide Modelle sehen die fehlende Ecke nicht

| Foto | Modell | `damaged` | `anomalies` | `surface_description` |
|---|---|---|---|---|
| 01 | `gemma4:12b` | **false** | `[]` | „The surface of the brick is smooth and continuous everywhere." |
| 01 | `qwen2.5vl:7b` | **false** | `[]` | „…smooth and continuous with no visible tears, splits, gouges, rags, or broken areas." |
| 02 | `gemma4:12b` | **false** | `[]` | „smooth and continuous everywhere" |
| 02 | `qwen2.5vl:7b` | **false** | `[]` | „…no visible tears, splits, gouges, or broken areas." |
| 03 | `gemma4:12b` | **false** | `[]` | „The surface is smooth and continuous everywhere." |
| 03 | `qwen2.5vl:7b` | **false** | `[]` | „…no visible tears, splits, gouges, or broken areas." |

**0 von 6 Aufrufen erkennen den Schaden.** Konfidenz dabei 0,95 bis 1,0 — beide Modelle sind sich
sicher, und beide irren sich.

## Laufzeiten

| Foto | Modell | Aufgabe | gesamt | laden | eval | Token |
|---|---|---|---|---|---|---|
| 01 | `gemma4:12b` | artikel | 49,8 s | 0,6 s | 13,9 s | 47 |
| 01 | `gemma4:12b` | schaden | 37,7 s | 0,5 s | 6,3 s | 29 |
| 01 | `qwen2.5vl:7b` | artikel | 134,1 s | 28,5 s | 6,0 s | 47 |
| 01 | `qwen2.5vl:7b` | schaden | 14,6 s | 0,2 s | 6,9 s | 57 |
| 02 | `gemma4:12b` | artikel | 75,2 s | 40,0 s | 6,9 s | 35 |
| 02 | `gemma4:12b` | schaden | 39,2 s | 0,3 s | 9,1 s | 33 |
| 02 | `qwen2.5vl:7b` | artikel | 110,3 s | 0,2 s | 6,0 s | 47 |
| 02 | `qwen2.5vl:7b` | schaden | 15,1 s | 0,1 s | 6,5 s | 54 |
| 03 | `gemma4:12b` | artikel | **ReadTimeout** | — | — | — |
| 03 | `gemma4:12b` | schaden | 37,0 s | 0,7 s | 5,0 s | 26 |
| 03 | `qwen2.5vl:7b` | artikel | 107,1 s | 0,1 s | 4,8 s | 47 |
| 03 | `qwen2.5vl:7b` | schaden | 12,5 s | 0,2 s | 5,7 s | 55 |

Zwei Nebenbefunde:

* **Die Ladezeiten von 28,5 s und 40,0 s sind Verdrängung, kein Kaltstart.** `OLLAMA_MAX_LOADED_MODELS`
  steht seit Lauf 19 auf 3, und die drei Plätze waren mit `qwen2.5:7b`, `qwen2.5:1.5b` und
  `gemma4:12b` belegt. `qwen2.5vl:7b` ist das vierte Modell — jeder Wechsel wirft eines heraus.
  Ein Modellvergleich mit einem Modell mehr als Plätzen misst also zusätzlich das Nachladen.
* **Die Schadensprüfung ist bei `qwen2.5vl:7b` rund dreimal schneller** (12,5–15,1 s gegen
  37,0–39,2 s). Für die Schadensachse allein wäre das ein Argument; in Lauf 20 lieferte
  `gemma4:12b` bei echtem Riss aber `scrap` mit 0,9, und diese Achse ist nicht Gegenstand
  dieses Laufs.

## Schlussfolgerung

**Es ist kein Modellproblem.** Beide Bildmodelle beantworten die gestellte Frage korrekt: Die
Oberfläche *ist* glatt und durchgehend. `surface_description` und die Entscheidungsregel im
`DAMAGE_PROMPT` fragen ausschließlich nach der Oberfläche; ein sauber fehlendes Eck bricht keine
Oberfläche, es entfernt Material.

Damit ist offener Punkt 15 geschlossen — mit einem anderen Ergebnis als erwartet: Der
Modellwechsel ist kein Weg. `bench_umriss.py` hat den nächstliegenden Prompt-Weg bereits
widerlegt (das Modell behauptet dann ausdrücklich Vollständigkeit, bei 46–55 s statt 8–41 s je
Aufruf). Wer fehlende Geometrie erkennen will, braucht einen Vergleich gegen die Sollform —
also Umriss gegen Katalogbild, nicht eine weitere Textbeschreibung.

**Für die Arbeit bleibt die Aussage aus Lauf 15 bestehen und ist jetzt breiter belegt:** Die Kette
erkennt Oberflächenschäden, keine fehlende Geometrie. Das ist eine Eigenschaft des Verfahrens.
Der Widerspruchszweig fängt den Fall auf (`review_required`), statt eine Halbwahrheit wirksam zu
machen.

## Belege

* `logs/bench_lauf15.jsonl` — Rohausgabe je Aufruf
* `logs/bench_roh.txt` — vollständiges Protokoll des Messlaufs
* Fotos: `docs/testlaeufe/2026-09-15_run15_sauberer_bruch/fotos/qa_photo_01..03.jpg` (unverändert)
