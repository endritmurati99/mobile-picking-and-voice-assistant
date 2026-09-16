# Lauf 27 — Soll-Befund-Cache im Kettenbetrieb, und ein Messfehler in allen Wiederholungsläufen (QA/0389)

**Datum:** 16.09.2026
**Artikel:** Brick 2x2 gelb, SKU 343724 — wie Lauf 25 und 26
**Auftrag:** L1/OUT/00300, Position 4 von 7
**Fotos:** 3, **MD5-gleich mit Lauf 25**, nur unter anderen Dateinamen hochgeladen
**Endzustand:** `completed`, `sellable`, Konfidenz 0,90
**Laufzeit:** 15:31:36 bis 15:33:20 UTC = **1 min 44 s**

## Was der Lauf prüft

Lauf 25 erzeugte für diesen Artikel eine Soll-Beschreibung und bezahlte dafür einen
Katalogbildaufruf von 20,3 s. Lauf 26 konnte den Cache nicht nutzen, weil der Zustandsvergleich bei
sichtbarem Schaden übersprungen wird. Offener Punkt 4 gilt seit Lauf 18 als behoben — dort aber an
einem Artikel und über einen Neustart hinweg, nicht als Treffer im laufenden Betrieb.

Eine Variable: der Cache-Zustand. Alles andere gleich, bis auf die Dateinamen (nötig wegen des
Idempotenzschlüssels, Stolperfalle 6) und eine minimal veränderte Beschreibung.

| Datei | MD5 | identisch mit |
|---|---|---|
| `r27_foto_01.jpg` | `3a512f3c8966022ccc7067328dd4f48e` | Lauf 25, `qa_photo_01.jpg` |
| `r27_foto_02.jpg` | `34e4ed248932dd2f7fd72ff482c47fda` | Lauf 25, `qa_photo_02.jpg` |
| `r27_foto_03.jpg` | `c4db6918b055448a0275b1612855cd25` | Lauf 25, `qa_photo_03.jpg` |

Cache-Inhalt vor dem Lauf, aus `/var/cache/pwr/soll_befunde.json`: zwei Einträge, einer davon
`{"ok": true, "damaged": false, "anomalies": [], "description": "smooth and continuous everywhere"}`
— erzeugt in Lauf 25 für genau diesen Artikel.

## Befund 1: Der Cache greift, der Katalogbildaufruf entfällt vollständig

| | Lauf 25 (Cache leer) | **Lauf 27 (Cache warm)** |
|---|---|---|
| Bildaufrufe | **4** (3 Fotos + Katalogbild) | **3** (nur die Fotos) |
| Katalogbild | 20,3 s | **0 s, findet nicht statt** |
| Textvergleich Soll/Ist | 18,8 s | **4,7 s** |
| Zustandsvergleich gesamt | **39,1 s** | **8,2 s** |
| Laufzeit gesamt | 2 min 45 s | **1 min 44 s** |

Der Zustandsvergleich lief vollständig durch und lieferte dasselbe Ergebnis wie in Lauf 25:

```json
{"event_type": "condition_compare", "new_damage": false, "damage": "intact",
 "reason": "Die Beschreibungen stimmen überein und deuten auf den gleichen Zustand hin."}
```

**Damit ist offener Punkt 4 auch im Kettenbetrieb belegt:** ab der zweiten Meldung je Artikel
kostet der Zustandsvergleich einen Textaufruf statt Bild plus Text. Eine Logzeile
`soll_cache_geladen` erschien diesmal nicht — der Cache lag bereits im Prozessspeicher, die Datei
musste nicht gelesen werden. Das ist der erwartete zweite Pfad.

## Befund 2: Wiederholungsläufe messen einen warmen Prompt-Cache in ollama

Die drei Bildaufrufe waren auffällig schnell: **24,5 s, 12,1 s, 14,6 s** gegen 35,5 s, 36,6 s und
37,9 s in Lauf 25 — bei **identischen Bilddateien**. Die Ursache steht im ollama-Log:

| Lauf | Aufgabe | `prompt eval` | Dauer |
|---|---|---|---|
| 25 | Foto 1 bis 3 | **je 459 Token** | 26–39 s |
| 26 | Foto 1 bis 3 | **je 459 Token** | 31–45 s |
| **27** | Foto 1 bis 3 | **je 5 Token** | **1,5–13 s** |

Ollama hat den Prompt samt Bild aus dem Vorlauf im Zwischenspeicher gehalten und nur die letzten
fünf Token neu ausgewertet. **Gemessen wurde also nicht dieselbe Inferenz noch einmal, sondern eine
zu großen Teilen zwischengespeicherte.**

Das betrifft nicht nur diesen Lauf. **Jeder bisherige Wiederholungslauf mit identischen Bilddateien
steht unter demselben Vorbehalt:** Lauf 10 (dieselben Fotos wie 9), Lauf 14 (wie 13), die Läufe 16,
17 und 18 (wie 15) und Lauf 20 (wie 8). In allen Fällen lagen die Bildzeiten unter denen des
Erstlaufs, und in allen Fällen wurde die Verbesserung einer Codeänderung zugeschrieben.

**Was davon unberührt bleibt:** Die Befunde dieser Läufe sind Aussagen über *Verhalten* — ob ein
Foto geprüft wird, ob ein Zweig läuft, welches Urteil herauskommt. Der Vergleich Lauf 9 gegen 10
etwa zeigt, dass die Budgetbremse ein Foto zurückstellt statt es zu verlieren; das hängt nicht an
der Dauer einzelner Aufrufe. **Was unter Vorbehalt steht,** sind die *Zeitgewinne*, die aus solchen
Paaren abgelesen wurden — insbesondere der gleitende Schätzwert der Läufe 11 bis 13, dessen
Eingangsgrößen aus wiederholten Bildern stammen.

Für künftige Messungen gilt deshalb: **Eine Zeitmessung gehört auf frische Bilddateien.** Eine
Wiederholung mit identischen Dateien ist für Verhaltensfragen richtig und für Zeitfragen
irreführend. Der Idempotenzschlüssel zwingt nur zu neuen *Namen*, nicht zu neuen *Inhalten* — genau
diese Lücke hat den Effekt so lange verdeckt.

## Zeitlicher Ablauf

| Zeit (UTC) | Komponente | Ereignis | Dauer |
|---|---|---|---|
| 15:31:36 | PWA | Meldung abgesendet, QA/0389 | — |
| 15:31:41,8 | Backend | Webhook an n8n | 5,5 s |
| 15:31:42–15:32:13 | ollama `qwen2.5:7b` | Textbewertung (task 359, 82 Prompt-Token) | **31,6 s** |
| 15:32:18,0 | `embed` | Artikelabgleich `match`, 0,9534 | < 1 s |
| 15:32:45,2 | ollama | Foto 1 | **24,5 s** |
| 15:32:57,3 | ollama | Foto 2 | **12,1 s** |
| 15:33:11,9 | ollama | Foto 3 | **14,6 s** |
| 15:33:20,1 | ollama + Backend | Zustandsvergleich, **nur Text** (task 423) | **8,2 s** |
| 15:33:20 | Odoo | `completed` | — |

**39 % des Knotenlimits** — die niedrigste Auslastung aller Läufe mit drei Fotos.

## Ergebnis der Systembewertung

```
ai_disposition:    sellable
ai_confidence:     0.90
ai_summary:        Kein Mangel erkennbar, Produkt wirkt unbeschaedigt.
ai_photo_analysis: Schaden: keine Auffälligkeit sichtbar.
```

Dasselbe Urteil wie in Lauf 25, die Konfidenz liegt mit 0,90 statt 1,0 etwas niedriger. Die
Beschreibung war leicht verändert („Wiederholte Kontrollmeldung…"), die Textbewertung ist also nicht
wortgleich reproduzierbar — bekannt aus Stolperfalle 9, hier auf der Textachse.

Artikelachse: `match`, **0,9534**, exakt der Wert aus Lauf 25. Die Einbettung ist deterministisch,
das Sprachmodell nicht.

## Belege

* `fotos/` — die drei Dateien, `pruefsummen.txt` mit dem MD5-Vergleich gegen Lauf 25
* `logs/` — Backend- und ollama-Auszüge; die `prompt eval`-Zeilen mit 5 gegen 459 Token
