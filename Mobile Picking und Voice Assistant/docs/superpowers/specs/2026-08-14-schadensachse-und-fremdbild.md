# Artikelabgleich, Schadensachse, Fremdbild — was am 2026-08-14 gemessen wurde

Messwerte unter `infrastructure/bildkorpus/messwerte/schadensachse/`.
Werkzeuge: `infrastructure/bildkorpus/schadensmessung.py`.
Commits: `18a7872`, `524fba7`, `20c8eea`.

## Der Ausgangspunkt

Der Artikelabgleich lief seit dem 2026-08-14 morgens auf einem eigenen Bildmodell
(`gemma4:12b` statt `qwen2.5vl:7b`), weil dieses in der Messung vom 2026-08-13 auf zwölf
handgeprüften Fällen 10/12 gegen 6/12 erreicht hatte. Der Wechsel hat **nicht** getragen.

Die Messung vom 13. war über eine **Montage** entstanden — beide Teile in einem Bild, ein
Aufruf urteilt `same_part`. Der Produktivpfad beschreibt beide Bilder **einzeln** und lässt
ein Textmodell die zwei Beschreibungen vergleichen. Damit entscheidet die Wortwahl über die
Artikelidentität, und das Modell hat darauf keinen Einfluss.

**Zehn Meldungen durch die echte Kette, sechs verschiedene Bricks:**

| Meldung | Foto | Urteil | woran |
|---|---|---|---|
| QA/0323 | hellblauer Bogenstein | abgewiesen | `blue` gegen `light blue` |
| QA/0329 | Bogenstein mit Kerbe | abgewiesen | `arch-shaped` gegen `rounded top` |
| QA/0331 | hellblauer 2x2 | abgewiesen | beide Seiten wörtlich `light blue`, Unterschied nur `studs` gegen `four cylindrical studs` |
| QA/0333 | weißer 2x2 | durchgelassen | **derselbe** Wortunterschied wie QA/0331 |

Alle drei abgewiesenen Fälle zeigten das richtige Teil. Es ist keine Regel, es ist Zufall:
dasselbe Foto ergab zweimal hintereinander `blue` und `light blue` — und damit match und
mismatch — bei `temperature 0`.

## Was daraus folgte: Bildabstand statt Worte

`embed/` verdrahtet (`embed_mode=primaer`). Der Dienst beschreibt nichts, sondern hält das
Foto gegen alle bekannten Artikel; der Abstand zum Zweitplatzierten ist die Konfidenz.

* Katalog 47 Artikel in 11 s, danach ein Abgleich in **0,19–0,23 s** gegen 45–165 s.
* Die zwei Fehlurteile sind weg: Bogenstein 0,847 match, hellblauer 2x2 0,885 match.
* Falschlieferung: 0,999 auf den tatsächlich abgebildeten Artikel, bestellter auf Platz 34.
* Kette gesamt 30–120 s statt 128–377 s, kein „assessment unavailable" mehr.

`unsicher` fällt auf den alten Weg zurück und wird nie zu `mismatch` — der Wert trifft das
Hundefoto (0,203) genauso wie ein schlecht belichtetes Teil.

## Das Zeitbudget band nicht während des Aufrufs

QA/0323 hat es vorgeführt: die Schadensprüfung startete mit 69 s Restbudget — die Prüfung
davor war also korrekt — und lief dann 125 s. Das Budget riss mit dem Aufruf in der Luft, n8n
schnitt nach 270 s die Verbindung, und der **bereits fertige** Artikelbefund ging mit unter.
`_in_restzeit` fesselt jetzt die drei nicht garantierten Bildaufrufe an die Restzeit. Der
garantierte erste Aufruf bleibt frei: ein Budget, das gar keinen Bildaufruf zulässt, wäre eine
abgeschaltete Bildprüfung unter anderem Namen.

## Die Schadensachse, gemessen

Nach dem Umbau war die Schadenserkennung die schwache Stelle. `qwen2.5vl:7b` nannte den gelben
Bogenstein „smooth and continuous everywhere" — auf einem Foto, auf dem die ausgerissene Kerbe
rund ein Fünftel der sichtbaren Fläche einnimmt. Kein Auflösungsproblem: die Vorlage ist
512 px und der Schaden füllt einen großen Teil davon.

Acht von Hand beschriftete Bilder (vier beschädigt, vier heil), gemessen über den
**produktiven** Aufruf `inspect_damage` bei `DAMAGE_MAX_EDGE` — kein Sonderpfad, keine
Montage. Das ist die Lehre aus dem 13.:

| Modell | Schaden gefunden | Fehlalarme | Median |
|---|---|---|---|
| `qwen2.5vl:7b` | 2/4 | 0/4 | 82 s |
| `gemma4:12b` | **4/4** | 0/4 | 58 s |
| `minicpm-v4.5:8b` | **4/4** | 0/4 | 49 s |

gemma4 und minicpm sind bei n=8 nicht auseinanderzuhalten. Den Ausschlag gab der Betrieb:
gemma4 trägt bereits den Rückfall des Artikelabgleichs, also braucht die Kette mit ihm **ein**
Bildmodell statt zwei — und `OLLAMA_MAX_LOADED_MODELS=2` geht mit Text- und Bildmodell genau
auf, ohne dass während einer Bewertung ein Modell verdrängt und neu geladen wird (80–145 s je
Ladevorgang).

Live: QA/0343 „jagged tear in the front face" auf genau dem Foto, das zweimal durchgerutscht
war; QA/0344 „crack, broken edge"; QA/0345 heiles Teil ohne Fehlalarm.

## Der Fund, den die Bilanz sichtbar gemacht hat

Über die letzten zwanzig Meldungen (QA/0326–0345, Rohdaten im Messwerteordner):

| Frage | Bilanz |
|---|---|
| Richtiges Teil als richtig erkannt | Textvergleich 6/8 · **Bildabstand 6/6** |
| Falscher Artikel erkannt | **2/2** |
| Fremdbild (Hund) erkannt | **1 von 4** |
| Schaden gefunden | `qwen2.5vl:7b` **0/3** · `gemma4:12b` **2/2** |
| Fehlalarm auf heilem Teil | **0/6** |

**QA/0340, QA/0341, QA/0342: dasselbe Hundefoto lief drei Mal als „Totalschaden,
abgeschlossen" durch.** Nicht falsch gerechnet — gar nichts gesagt. Der Bildabstand urteilte
korrekt `unsicher` (0,203 gegen die Schwelle 0,45; echte Teile liegen bei 0,82–0,999), der
Rückfallweg starb an einem Ollama-OOM (`llama-server process has terminated: signal: killed`,
drei Modelle gleichzeitig resident), und übrig blieb `article="unavailable"`. Damit greift in
`reconcile` **keine** Artikelregel mehr, `contradiction` bleibt False, und n8n nimmt den
Erfolgszweig. Das Texturteil stand unwidersprochen über einem Hundefoto.

Der Dienst unterscheidet seitdem die zwei Arten von `unsicher`:

* `kein_treffer` — nichts im Katalog kommt dem Bild nahe. Das **ist** eine Aussage.
* `zu_dicht` — zwei Artikel lassen sich am Bild nicht trennen (`6167549` gegen `6171865`).
  Das ist **keine** Aussage und darf niemals eine werden.

Nur `kein_treffer` eskaliert, und auch das erst, wenn zusätzlich der Rückfallweg schweigt.
`mismatch` heißt in dieser Lücke nicht „wir wissen, es ist das falsche Teil", sondern „das kann
niemand mehr beurteilen": es setzt `contradiction` und damit `review_required`, es sondert
nichts aus. Live nachgefahren: QA/0346, `review_required`.

## Woher die Einstufung kommt — und was daran offen ist

Die Einstufung kommt vom **Textmodell** und nur von ihm. `qwen2.5:7b` sieht das Foto nie; es
bekommt den Freitext des Kommissionierers, die Priorität und die *Anzahl* der Fotos. Das Bild
ist der Prüfer, nicht der Entscheider, und die Prüfregel ist bewusst asymmetrisch: Foto sieht
Schaden gegen Meldung „verkaufsfähig" → Mensch; Foto sieht nichts gegen Meldung „Schaden" →
Texturteil bleibt stehen, Hinweis daneben.

**Offen und nicht gedeckt:** der Sprung von „Artikel beschädigt" auf `scrap` (Totalschaden).
Der Systemprompt beschreibt die vier Werte in je drei Worten — keine Abstufungsregel, kein
Zweifelsfall-Default, keine Beispiele. Die beiden anderen Prompts derselben Datei haben genau
das („Im Zweifel gilt: dasselbe Teil."). Und `reconcile` kennt nur den String `scrap` und kann
nicht unterscheiden, ob der Schweregrad vom Menschen stammt oder vom Modell erfunden wurde:
der Mensch sagte „beschädigt", nicht „Totalschaden".

## Weitere offene Punkte

1. Der Textvergleich bleibt als Rückfall drin und bleibt nicht reproduzierbar.
2. Beleglage schmal: 8 Bilder auf der Schadensachse, 4 Motive. Der Prüfstand für frische
   Aufnahmen steht (`infrastructure/bildkorpus/neuetest/`).
3. `damage == "unavailable"` erzeugt keinen Hinweissatz — ist das Foto unlesbar oder das
   Bildmodell stumm, geht `scrap` ohne Vermerk durch. Weniger scharf als das Fremdbild, weil
   „Schaden: nicht geprüft (…)" im Klartext steht, aber ungeprüft.
4. Die empfohlene Aktion ist starr an die Einstufung gekettet. „Aussondern" ist irreversibel;
   wer die Aktionszeile liest und die Fotoanalyse nicht, vernichtet heile Ware.
