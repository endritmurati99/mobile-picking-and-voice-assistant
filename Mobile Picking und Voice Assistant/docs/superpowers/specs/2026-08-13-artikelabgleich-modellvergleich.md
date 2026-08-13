# Artikelabgleich: warum er scheitert, und was stattdessen misst

**2026-08-13.** Messwerte unter `infrastructure/bildkorpus/messwerte/`.
Werkzeuge: `modellvergleich.py`, `produkttest.py`, `paarmatrix.py`, Dienst unter `embed/`.

## Der Befund in einem Satz

Der Artikelabgleich weist ein beschädigtes **richtiges** Teil als Falschlieferung
ab, weil das Bildmodell den Schaden für ein Artikelmerkmal hält — und das
Sprachmodell zu fragen ist für diese Frage das falsche Werkzeug.

## Was der Lauf vom 2026-08-11 wirklich gemessen hat

`paarmatrix.py --fotos --koeder 1` lief 99 von 104 Paaren durch, dann kam der
Docker-Shutdown. Rohzahl 75,7 % (103 Urteile, 22 Fehler auf der Gleich-Achse).

Die Rohzahl ist unbrauchbar, aus drei Gründen:

1. **13 der 22 Fehler sind Beschriftungsfehler.** `soll=gleich` steht auf
   Hunde- und Essensfotos, weil die Meldung am richtigen Produkt hängt, das
   Foto aber ein Testbild ist. An Produkt 85 allein hängen 33 Anhänge;
   `fotopaare()` greift den falschen. Das Modell hat dort richtig geurteilt und
   wurde als Fehler gezählt. Ohne diese 13: 86,7 % gesamt, 76,3 % auf der
   Gleich-Achse.
2. **103 Urteile enthalten nur 66 verschiedene Bildpaare**, und die sitzen auf
   **vier Motiven**: gelber Bogenstein (sauber plus drei Aufnahmen derselben
   ausgerissenen Kerbe), blauer 2×2 mit Riss, gelber 2×3 stark beschädigt und
   verschmutzt, Hund am Strand.
3. **31 Läufe unter 15 s** sind Prompt-Cache-Treffer auf byteidentischen
   Montagen, keine unabhängigen Messwerte.

## Die zwölf Fälle, auf denen ab jetzt gemessen wird

Von Hand angesehen und beschriftet (`modellvergleich.FAELLE`), zwei Achsen,
ausgewogen 6/6:

- **Schadenstoleranz** — beschädigtes richtiges Teil muss `gleich` ergeben.
  Der teure Fehler: sonst wird die Schadensmeldung als Falschlieferung
  abgewiesen und der Befund geht verloren.
- **Artikelschärfe** — anderer Artikel muss `anders` ergeben, auch bei gleicher
  Farbe oder ähnlicher Form. Ohne diese Achse gewinnt jedes Modell, das immer
  `gleich` sagt.

Vier Motive, zwölf Fälle: eine Vorauswahl, kein Beweis. Wer hier durchfällt,
ist erledigt; wer besteht, muss danach gegen echte neue Aufnahmen.

## Bildsprachmodelle, alle über dieselbe Montage

| Modell | gesamt | Schaden | Artikel | s/Fall |
|---|---|---|---|---|
| `gemma4:12b` | **10/12** | **5/6** | 5/6 | **49 s** |
| `qwen2.5vl:7b` (im Einsatz) | 6/12 | 2/6 | 4/6 | 149 s |
| `qwen3-vl:8b` | siehe unten | | | 100–977 s |

`gemma4:12b` löst den Kernfall: blauer Stein gegen denselben Stein mit Riss →
`same_part: true`, „Both are the same type of Lego brick." Es benennt den
Schaden und lässt ihn nicht über die Artikelfrage entscheiden. Dabei dreimal
schneller. Reiner Modellwechsel, keine Umbauarbeit.

Seine zwei Fehler: **S4** (dritte Aufnahme desselben Schadens, gekippt) fällt
durch, obwohl S2 und S3 mit demselben Schaden bestehen — wackelig, nicht robust.
**A2** (gelber 2×2 gegen gelben 2×3) hält es für gleich; die Noppenzahl liest es
nicht. Denselben Fehler macht `qwen2.5vl:7b`.

`qwen2.5vl:7b` bekommt seine 4/6 auf der Artikelachse teils über die falsche
Regel: A2 und A5 begründet es mit *„The right part is visibly damaged and not
the same"* und *„Different colors and presence of cracks"*. Also **beschädigt ⇒
anderer Artikel** — genau die Regel, die die Schadensachse zerstört. Nimmt man
den Schaden aus den Testfällen, bricht seine Artikelschärfe zusammen.

### Messfehler, der eine ganze Reihe wertlos machte

Der erste `qwen3-vl:8b`-Lauf ergab „6/12, Schaden 0/6". **Das war die eigene
Auswertung, nicht das Modell.** Unter `format: json` liefert `qwen3-vl:8b` in
Ollama 0.31.1 zwölfmal ein leeres `{}`; `bool(ergebnis.get("same_part"))` macht
daraus `False`, und so entstanden zwölf protokollierte Urteile, die das Modell
nie gefällt hat. Behoben in `modellvergleich.geurteilt()`: ohne den Schlüssel
`same_part` gilt der Fall als **fehlgeschlagen** und wird nicht als `anders`
gebucht; zusätzlich ein zweiter Versuch ohne Formatzwang mit `aus_text()`.
Danach besteht `qwen3-vl:8b` S1 mit *„ignores cracks; both have 4 studs"* — es
hatte die Anweisung sehr wohl gelesen.

### Native Mehrbild-Eingabe gibt es nicht

Die Montage (zwei Teile in ein Bild, schwarzer Balken dazwischen) ist ein
Notbehelf gegen Ollamas Beschränkung. Geprüft am 2026-08-13, ob ein anderes
Modell sie ablöst — `gemma4:12b` mit zwei Bildern und der Bitte, beide zu
beschreiben:

    I can see only one image.

**Ollama 0.31.1 reicht auch `gemma4` nur das erste Bild durch**, nicht nur
`qwen-vl`. Der Umweg bleibt; `gemma4` erreicht seine 10/12 damit, nicht trotz.

### Kein Tempohebel auf dieser Maschine

Ollama läuft zu 100 % auf der CPU. `qwen2.5vl:3b` ist **nicht** schneller als
`7b` (53–61 s gegen 55–73 s) und macht dieselben Fehler — beide halten einen
grünen und einen blauen Stein für denselben Artikel. Kantenlänge 224 statt 448
bringt 56 s statt 69 s, nicht mehr. (Eine frühere Messung von 6,8 s war ein
Prompt-Cache-Treffer der eigenen Aufwärmrunde.)

## Der Gegenentwurf: Abstand statt Urteil

`embed/` — eigener Dienst nach dem Muster von `piper`/`whisper`, Gewichte ins
Bild gebacken, weil `automation-net` per `internal: true` keinen Weg nach
draußen hat.

**Abruf statt Vergleich.** „Sind diese zwei gleich" braucht eine geratene
Schwelle, und die ist nicht sauber ziehbar: gemessen reichen gleiche Paare ab
0,82 aufwärts, verschiedene bis 0,92 hinauf — die Bereiche überlappen bei
DINOv2 **und** bei SigLIP2. „Welcher der bekannten Artikel ist das" braucht
keine Schwelle und liefert den Abstand zum Zweitplatzierten als Konfidenz.

**Zwei Kanäle.** DINOv2 ist formdominant (grüner gegen blauen 2×2: 0,9157).
Über alle 44 bebilderten Artikel, jeder gegen ein gedrehtes und verkleinertes
Abbild seiner selbst:

| Verfahren | Platz 1 richtig | mittlerer Abstand zum Zweiten |
|---|---|---|
| nur Form | 33/44 | 0,051 |
| Form + 25 % Farbe | **41/44** | 0,101 |
| Form + 40 % Farbe | 41/44 | 0,110 |

Ungelöst bleiben `173057→518295`, `4648231→6294939`, `6167549→6171865` — mögliche
echte Beinahe-Dubletten im Sortiment, die anzusehen sind.

**Drei Urteile statt zwei.** `match`, `mismatch`, `unsicher`. Unsicher greift,
wenn nichts über der Fremdschwelle liegt oder Platz 1 und 2 zu dicht sind. Ein
Fall beim Menschen ist billiger als ein falsches `mismatch`, das eine echte
Schadensmeldung abweist.

### Live gegen die echten Meldefotos

    foto_4    match     0.45s   blauer Stein MIT RISS  -> 4166960 0.940, Abstand 0.11
    foto_3    match     1.78s   blauer Stein sauber    -> 4166960 0.998, Abstand 0.14
    foto_11   match     0.43s   Bogenstein MIT KERBE   -> 6023350 0.848, Abstand 0.17
    foto_213  match     0.36s   Bogenstein MIT KERBE   -> 6023350 0.870, Abstand 0.17
    foto_10   match     0.45s   Bogenstein MIT KERBE   -> 6023350 0.773, Abstand 0.13
    foto_13   match     0.41s   Bogenstein sauber      -> 6023350 0.924, Abstand 0.20
    foto_14   unsicher  0.50s   Hund -> beste Uebereinstimmung 0.204 unter Schwelle 0.45

**7/7.** Der Schaden verschiebt den Wert von 0,924 auf 0,773–0,870 und lässt den
richtigen Artikel trotzdem klar auf Platz 1. Der Hund fällt nicht knapp durch,
sondern um eine Größenordnung.

Katalog einbetten: 29,8 s für 44 Artikel (0,68 s je Bild), einmalig. Danach
kostet eine Meldung **eine** Einbettung plus 44 Skalarprodukte.

## Offen

- Der Dienst ist **noch nicht** in `_check_article` verdrahtet und steht in
  keiner `docker-compose.yml`. Er ist eigenständig gemessen, nicht in der Kette.
- Beleg steht auf 6 echten Fotos an 2 Artikeln plus 44 abgeleiteten Bildern.
  Die abgeleiteten zeigen, dass das Werkzeug Artikel trennen kann — nicht, dass
  es das auf echten Lagerfotos in der Breite tut.
- `produkttest.py --produkte` (94 Tests über alle Artikel) wurde bei 20/94
  abgebrochen, um RAM für den Modellvergleich frei zu machen. Zwischenstand
  liegt unter `messwerte/produkttest/`.
- `paarmatrix.fotopaare()` greift weiterhin den falschen Anhang je Meldung.
  Vor jeder Wiederholung dieses Laufs zu reparieren.
