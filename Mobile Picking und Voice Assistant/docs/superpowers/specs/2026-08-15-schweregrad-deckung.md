# Schweregrad: deckt die Meldung das Urteil?

**Stand 2026-08-15, Branch `integration/foundation-remediation`.**

## Der Befund

`"Artikel beschaedigt"` wurde zu `scrap` mit Konfidenz 0,90 — Ware aussondern,
Schichtleitung informieren. Der Satz sagt, dass etwas nicht stimmt; er sagt
nicht, dass die Ware verloren ist.

Zwei Ursachen, beide im Code nachlesbar:

1. **Der Systemprompt hatte keine Abstufungsregel.** Er beschrieb die vier
   Dispositionen in je drei Worten, ohne Zweifelsfall, ohne Beispiel — während
   die beiden anderen Prompts derselben Datei (`_COMPARE_SYSTEM_PROMPT`,
   `_CONDITION_SYSTEM_PROMPT`) genau das haben, jeweils aus einer Messung
   heraus entstanden.
2. **`reconcile` kannte nur den String `scrap`.** Ob ein Mensch den
   Totalschaden gemeldet oder das Modell ihn geschlossen hatte, war an der
   Tabelle nicht zu unterscheiden. `scrap` ist die einzige der vier
   Dispositionen, die sich nicht zurückdrehen lässt.

## Was geändert wurde

**Prompt** (`llm_client._SYSTEM_PROMPT`): vier Werte vom schwersten zum
leichtesten, `scrap` nur bei ausgesprochener Zerstörung oder Unbrauchbarkeit,
Verpackung ≠ Ware, Zweifelsfall `quarantine`, vier Beispiele. Zusätzlich zwei
Felder **vor** dem Urteil — `belegstelle` (wörtliches Zitat) und `grundlage`
(`wortlaut` | `annahme`). Dieselbe Bauart wie `unterschied` im
Vergleichsprompt: Messgröße, keine Steuerung. Die Reihenfolge ist der
gemessene Punkt aus `vision_client.DESCRIBE_PROMPT` — wird zuerst nach dem
Urteil gefragt, antwortet das Modell aus dem Schema statt aus der Sache.

**Regel** (`assessment_reconciliation.reconcile`): `scrap` + `grundlage ==
"annahme"` + Foto zeigt den Schaden **nicht** (`intact` oder `unavailable`)
→ `contradiction=True`, die Meldung geht an einen Menschen; im Klartext steht,
dass die Einstufung geschlossen und nicht gemeldet ist, samt dem unwirksamen
Texturteil.

Die Bedingung ist bewusst eng:

- Nur `scrap`. `quarantine`, `rework` und `sellable` sind umkehrbar; sie zum
  Menschen zu schicken, wäre Handarbeit ohne Gegenwert.
- Nur bei ausdrücklichem `"annahme"`. `None` heißt „unbekannt" und wirkt
  nicht — sonst hätten ein älteres Modell, ein Tippfehler und eine echte
  Aussage dieselbe Folge.
- Bestätigt das Foto einen Schaden, bleibt das Urteil. Über die *Schwere* sagt
  das Bild nichts, aber der Anlass ist dann belegt.

Nebenbei geschlossen: `damage == "unavailable"` erzeugte bisher keinen
Hinweissatz, ein `scrap` ging dort ohne jeden Vermerk durch (offener Punkt 2
vom 2026-08-14).

## Messung

`infrastructure/bildkorpus/schweregradmessung.py`, 21 handbeschriftete
Meldetexte, `qwen2.5:7b`, produktiver Payload (`format: json`,
`temperature: 0`, derselbe Benutzerprompt). Rohwerte unter
`infrastructure/bildkorpus/messwerte/schweregrad/`.

| Prompt | richtig | zu hoch | zu niedrig | falsches `scrap` | Median |
|---|---|---|---|---|---|
| ALT | 11/21 | 3 | 7 | 3 | 10 s |
| NEU (Runde 1) | 19/21 | 1 | 1 | 1 | 25 s |
| NEU2 (übernommen) | 19/21 | 1 | 1 | 1 | 15 s |

Die Fehlerrichtung zählt getrennt, weil eine gemeinsame Trefferquote genau das
verdeckt, worum es geht: ein zu hohes Urteil vernichtet Ware, ein zu
niedriges schickt Schaden zum Kunden. Der alte Prompt war in **beide**
Richtungen daneben — er sonderte vage Meldungen aus und ließ zugleich fünf
benannte, behebbare Mängel als `sellable` durch.

**`grundlage` brauchte eine zweite Runde.** In Runde 1 hieß die Definition nur
„die Meldung nennt die Schwere" — und `"Artikel beschaedigt"` bekam
`wortlaut`, weil das Wort ja dasteht. Gefragt ist aber das *Ausmaß*, nicht der
Mangel. Mit der scharfen Fassung kippt genau dieser Fall auf `annahme`, die
Disposition bleibt bei 19/21, und der Median fällt von 25 s auf 15 s. Über
alle 21 Fälle gezählt sinkt die Übereinstimmung mit meiner Beschriftung von
16 auf 14 — die Verluste liegen ausschließlich bei `rework`-Fällen
(„Kleiner Kratzer", „Schraube fehlt"), wo `grundlage` nichts auslöst. Auf den
drei `scrap`-Fällen sagt es in beiden Fassungen `wortlaut`.

## Live nachgewiesen

- **QA/0347** (Alert 348, Produkt 85, foto_4): Texturteil `quarantine, 0,90` —
  vorher `scrap`. Ging trotzdem an den Menschen, weil der Bildabstand das Foto
  korrekt einem anderen Artikel zuordnete (4166960, 0,942); Wahl des Produkts
  war mein Fehler, nicht der der Kette.
- **QA/0348** (Alert 349, Produkt 73 = Brick 2x2 blau, foto_4): 60 s,
  `completed`, `quarantine` 0,80, „Ware sperren und manuelle Prüfung
  anfordern". Fotoanalyse: „Schaden: SICHTBAR — crack, broken piece. Zustand:
  Abgleich mit dem Katalogbild bestätigt den Befund." Derselbe vage Meldetext,
  der vorher Ware ausgesondert hätte.

1070 Backend-Tests grün, 9 neu. Die neue Regel fällt per Mutation
(`grundlage == "annahme"` → `False`) — der Test prüft sie wirklich.

## Was offen bleibt

1. **`"Ware kaputt"` urteilt weiter `scrap`, und zwar mit `wortlaut`** — läuft
   also auch an der neuen Regel vorbei. Der einzige verbliebene Fall im
   Korpus, in dem geschlossene Schwere Ware vernichtet. Weiter am Prompt zu
   drehen hieße, ihn an 21 Sätze anzupassen; die Alternative wäre die härtere
   Regel „kein `scrap` ohne Bildbeleg, unabhängig von `grundlage`".
2. `"Teil defekt"` → `rework` (zu niedrig). Harmlos in der Wirkung, aber
   dieselbe Wurzel.
3. Korpus ist selbst geschrieben, nicht aus dem Betrieb gezogen. 21 Sätze,
   eine Beschrifterin. Echte Meldetexte aus Odoo wären belastbarer.
4. Die Konfidenz bleibt unbenutzt und unkalibriert (0,90 für eine Vermutung).
   Bewusst: eine Schwelle darauf wäre Scheinsicherheit — dieselbe Überlegung
   wie in `assessment_reconciliation`.
