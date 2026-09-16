# Testlauf 19 — Drei Modellplätze statt zwei

**Datum:** 16.09.2026
**Art:** Messung ohne Kettenlauf (Abschnitt 6 des Testlauf-Skills)

---

## 1. Was dieser Lauf prüft

Lauf 17 hat eine Verschlechterung aufgedeckt, die durch das Reparieren des Sprach-Warmlaufs
entstanden ist: Seit der Warmlauf eine eigene Frist hat, **lädt** er das Sprachmodell wirklich —
und bei `OLLAMA_MAX_LOADED_MODELS = 2` fliegt dafür das am längsten ungenutzte Modell heraus.

Am 16.09. um 10:14:13 war das `gemma4:12b`. Nachladen: **121 s**.

Die Frage: Passen drei Modelle in den Speicher, oder muss der Sprach-Warmlauf wieder weg?

**Ohne Kettenlauf.** Die Frage ist eine Speicherfrage, keine Kettenfrage. Eine Meldung durch die
Kette zu schicken hätte sie nicht beantwortet und rund vier Minuten gekostet.

### Warum die Modellgrößen allein nicht reichen

`ollama ps` meldet die Modellgröße, nicht den Speicherbedarf — der Kontext kommt hinzu, und der
unterscheidet sich je Modell (Bild 8192, Text und Sprache je 4096). Deshalb wurde gemessen und
nicht addiert.

---

## 2. Messung: Speicher bei drei geladenen Modellen

Jedes Modell einzeln mit seiner **Produktiv-Kontextgröße** geladen, nach jedem Schritt der
Speicherstand des ollama-Containers abgelesen.

| Rolle | Modell | `num_ctx` | Ladezeit | geladen danach | Container-Speicher |
|---|---|---|---|---|---|
| Sprache | `qwen2.5:1.5b` | 4096 | 9,3 s | 1 Modell, 1,2 GB | 5,07 GiB |
| Text | `qwen2.5:7b` | 4096 | 26,0 s | 2 Modelle, 6,2 GB | 8,02 GiB |
| Bild | `gemma4:12b` | 8192 | 91,6 s | 3 Modelle, 15,4 GB | **15,62 GiB** |

**15,62 GiB von 25,44 GiB — 61 %.** Knapp 10 GiB bleiben frei.

```
NAME            ID              SIZE      PROCESSOR    CONTEXT
gemma4:12b      4eb23ef187e2    9.2 GB    100% CPU     8192
qwen2.5:7b      845dbda0ea48    5.1 GB    100% CPU     4096
qwen2.5:1.5b    65ec06548149    1.2 GB    100% CPU     4096
```

### Einordnung gegen den OOM vom 14.08.2026

Der Absturz mit `llama-server process has terminated: signal: killed` trat bei **20,5 GB**
Modellgewicht auf: `gemma4:12b` (9,2) plus `qwen2.5:7b` (5,1) plus `qwen2.5vl:7b` (6,2). Das
dritte Modell wog damals 6,2 GB.

Hier wiegt das dritte Modell **1,2 GB** — ein Fünftel davon. Die Summe liegt mit 15,4 GB gut
5 GB unter dem Wert, bei dem es damals riss.

---

## 3. Gegenprobe am laufenden System

`OLLAMA_MAX_LOADED_MODELS` auf 3 gesetzt, Backend neu gestartet (10:48:08,9 UTC), Vorwärmen
beobachtet:

| Zeit | Aufruf | Dauer |
|---|---|---|
| 10:48:20 | `POST /api/chat` (Sprache) | 5,6 s |
| 10:49:07 | `POST /api/chat` (Text) | 42,0 s |
| 10:49:15 | `POST /api/generate` (Bild) | **7,76 s** |

`ollama ps` danach: alle drei Modelle weiterhin geladen, **nichts verdrängt**.

### Der Vergleich, auf den es ankommt

| | Lauf 17 (2 Plätze) | Lauf 19 (3 Plätze) |
|---|---|---|
| Bild-Warmlauf nach Backend-Neustart | **88,8 s** (Modell war verdrängt) | **7,76 s** |
| Modelle nach dem Vorwärmen | 2, Sprache verdrängt | 3, alle |

**81 s gespart**, und zwar bei jedem Backend-Neustart mit warmem ollama.

---

## 4. Entscheidung

`OLLAMA_MAX_LOADED_MODELS` steht jetzt auf **3** (`docker-compose.yml`, über
`${OLLAMA_MAX_LOADED_MODELS:-3}` umstellbar).

Damit ist die in Lauf 17 gefundene Verschlechterung behoben — nicht durch Zurücknehmen des
Sprach-Warmlaufs, sondern durch den Platz, den er braucht.

**Was beim nächsten Modellwechsel zu tun ist:** Wer ein weiteres 7B-Modell aufnimmt, misst
vorher neu. Die Zahl 3 ist an genau diese drei Modelle gebunden, nicht an die Zahl der Rollen.

---

## 5. Belege

| Datei | Inhalt |
|---|---|
| `mess_speicher.py` | das benutzte Messskript |
| `messung.txt` | Rohausgabe der Ladereihe und des Speicherverlaufs |
