# Lauf 23 — Untere Schranke auf den Spitzenwert des Artikelabgleichs

**Datum:** 16.09.2026
**Art:** Messung ohne Kettenlauf (Abschnitt 6 des Skills)
**Offener Punkt:** 13 der Gesamtübersicht

## Was der Lauf prüft

Lauf 21 setzte den erwarteten Artikel auf Platz 6, bei Spitzenwert 0,6087 und Abstand 0,0546 —
über der Knappheitsschwelle, also **kein** `unsicher`, sondern eine falsche Gewissheit. Der
Befund lautete: Was fehlt, ist keine engere Abstandsschwelle, sondern eine untere Schranke auf
den Spitzenwert. Die Auflage lautete, das vor dem Einbau über alle archivierten Fotos zu messen.

## Datengrundlage

Alle Meldefotos aus den Laufordnern, **nach MD5 entdoppelt**: 72 Dateien, davon 30 Wiederholungen
(Lauf 14 = Lauf 13, Läufe 16/17/18 = Lauf 15). Bleiben **42 eindeutige Fotos**: 34 freigestellt,
6 im Lager, 2 ohne Katalogvorlage erzeugt. Liste: `liste.txt`, Herkunft je Datei: `quellen.txt`.

Vorher nötig: `fuelle_katalog.py`. Der Einbettungsdienst hält den Katalog nur im Speicher und
antwortet nach einem Neustart mit `HTTP 409 Conflict`; im Betrieb schiebt das Backend ihn beim
ersten Abgleich nach, eine Messung ohne Kettenlauf löst das nie aus. 47 Artikel in 13,1 s.

## Ergebnis

| Auswahl | n | Platz 1 richtig | Spitzenwert richtig | Spitzenwert falsch |
|---|---|---|---|---|
| alle Fotos | 42 | 30 | 0,6640 – 0,9301 | 0,4263 – 0,8187 |
| **nur erste Fotos** | **13** | **10** | **0,8467 – 0,9301** | **0,4973 – 0,7655** |
| nur freigestellt | 34 | 29 | 0,6640 – 0,9301 | 0,6391 – 0,8187 |

**Nur das erste Foto zählt.** `_check_article` sieht ausschließlich das erste hochgeladene Foto
(`n8n_v2.py:322`). Auf genau dieser Menge trennen die beiden Gruppen sauber: der schlechteste
richtige Spitzenwert liegt bei **0,8467**, der beste falsche bei **0,7655**. Dazwischen liegt eine
Lücke von 0,0812, in der keine einzige Messung liegt.

| Schranke | fängt falsche | verwirft richtige |
|---|---|---|
| 0,60 | 1 von 3 | 0 von 10 |
| 0,65 | 2 von 3 | 0 von 10 |
| 0,75 | 2 von 3 | 0 von 10 |
| **0,80** | **3 von 3** | **0 von 10** |

Über alle 42 Fotos betrachtet überlappen die Gruppen dagegen deutlich (richtig ab 0,6640, falsch
bis 0,8187) — dort ist keine Schranke ohne Verlust möglich. Der Unterschied erklärt sich aus der
Ansicht: Unter- und Rückansichten liefern niedrige Werte, gehen aber nie in den Artikelabgleich.

## Schlussfolgerung

Eine untere Schranke auf den Spitzenwert ist **auf der produktiv wirksamen Menge sauber
trennbar**. 0,80 fängt alle drei Fehlurteile — den Lagerlauf 3 (0,4973), Lauf 1 (0,7655) und
Lauf 21 ohne Katalogvorlage (0,6096) — und verwirft keines der zehn richtigen.

**Was die Zahl nicht trägt:** n = 13 mit nur drei Gegenbeispielen. Die Lücke ist breit, die
Stichprobe ist klein. Die Schranke gehört als `unsicher` behandelt, nicht als `mismatch` — ein zu
niedriger Spitzenwert heißt „ich erkenne das Teil nicht wieder", nicht „das ist das falsche Teil".
Damit greift der bestehende Textweg, der in Lauf 15 den Lauf gerettet hat.

Nicht eingebaut. Die Zahl liegt vor, der Einbau ist eine Entscheidung.

## Belege

* `logs/probe_schwellen.txt` — Ausgabe je Foto
* `liste.txt`, `quellen.txt` — Eingabemenge und Herkunft
* `.claude/skills/qa-testlauf/scripts/fuelle_katalog.py` — neu, füllt den Katalog ohne Kettenlauf
