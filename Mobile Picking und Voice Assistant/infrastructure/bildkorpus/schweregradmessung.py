"""Schweregrad aus dem Meldetext: deckt der Wortlaut das Urteil?

Der Befund, der diese Messung ausgeloest hat: "Artikel beschaedigt" wurde zu
`scrap` mit Konfidenz 0,90. Der Satz sagt, dass etwas nicht stimmt -- er sagt
nicht, dass die Ware verloren ist. Aussondern ist die einzige irreversible der
vier Dispositionen; sie darf nicht aus einer Vermutung fallen.

Gemessen wird der PRODUKTIVE Aufruf: derselbe Endpunkt, dasselbe Modell,
`format: json`, `temperature: 0`, derselbe Benutzerprompt wie in
`LlmClient._build_user_prompt`. Getauscht wird ausschliesslich der
Systemprompt -- ALT ist der Wortlaut aus `llm_client._SYSTEM_PROMPT`, NEU der
Vorschlag. Beide laufen gegen denselben Korpus, damit der Unterschied nicht an
den Faellen haengt.

Zwei Achsen zaehlen getrennt:
  1. Trifft die Disposition?
  2. In welche RICHTUNG geht der Fehler? Ein zu hohes Urteil vernichtet Ware,
     ein zu niedriges schickt Schaden zum Kunden. Eine gemeinsame Trefferquote
     verdeckt genau diesen Unterschied.

Lauf (Repo ist im Backend-Container nicht gemountet):
    docker exec -i backend python - < schweregradmessung.py
"""
import asyncio
import json
import os
import time

import httpx

from app.config import settings

ENDPOINT = "http://ollama:11434"
# Ueber die Umgebung setzbar: ein zweiter Lauf hat sonst den ersten
# ueberschrieben, und die Rohwerte von Runde 1 waren weg.
ERGEBNIS = os.environ.get("ERGEBNIS", "/tmp/schweregradmessung.json")

# Rangfolge, um die Fehlerrichtung auszaehlen zu koennen.
RANG = {"sellable": 0, "rework": 1, "quarantine": 2, "scrap": 3}

# (Meldetext, Soll-Disposition, Soll-Grundlage, worum es in dem Fall geht)
#
# `grundlage` ist die eigentliche Frage: nennt die MELDUNG die Schwere, oder
# schliesst das Modell sie? Nur der erste Fall traegt ein `scrap`.
FAELLE = [
    # -- Schwere steht im Wortlaut, scrap ist gedeckt --------------------
    ("Gehaeuse zersplittert, Bruchstuecke liegen lose im Karton",
     "scrap", "wortlaut", "Zerstoerung benannt"),
    ("Artikel gebrochen, Bruch nicht reparierbar",
     "scrap", "wortlaut", "Irreparabilitaet benannt"),
    ("Totalschaden am Gehaeuse, komplett zerstoert",
     "scrap", "wortlaut", "Totalschaden benannt"),
    # -- Der Ausloeser: Schaden gemeldet, Schwere offen ------------------
    ("Artikel beschaedigt",
     "quarantine", "annahme", "der gemessene Fehlerfall"),
    ("Ware kaputt",
     "quarantine", "annahme", "umgangssprachlich, ohne Ausmass"),
    ("Teil defekt",
     "quarantine", "annahme", "Funktionsaussage ohne Ausmass"),
    ("Mit dem Artikel stimmt etwas nicht",
     "quarantine", "annahme", "reiner Verdacht"),
    ("Artikel sieht komisch aus, bitte anschauen",
     "quarantine", "annahme", "Bitte um Pruefung"),
    # -- Verdacht und Verunreinigung: sperren, nicht vernichten ----------
    ("Verpackung feucht, Inhalt moeglicherweise betroffen",
     "quarantine", "annahme", "Feuchtigkeit, Wirkung offen"),
    ("Fremdkoerper in der Verpackung gefunden",
     "quarantine", "wortlaut", "Verunreinigung"),
    ("Rost an der Unterseite sichtbar",
     "quarantine", "wortlaut", "Korrosion, Ausmass offen"),
    # -- Verpackung ist nicht die Ware -----------------------------------
    ("Karton aufgerissen, Ware unbeschaedigt",
     "rework", "wortlaut", "Verpackung gegen Ware"),
    ("Umverpackung eingedrueckt, Teil laut Sichtpruefung in Ordnung",
     "rework", "wortlaut", "Verpackung gegen Ware"),
    # -- Benannter, behebbarer Mangel ------------------------------------
    ("Etikett schief aufgeklebt, Nacharbeit noetig",
     "rework", "wortlaut", "Nacharbeit ausdruecklich"),
    ("Kleiner Kratzer auf der Verpackung",
     "rework", "wortlaut", "geringfuegig, benannt"),
    ("Leichte Delle am Deckel, Artikel unbeschaedigt",
     "rework", "wortlaut", "geringfuegig, benannt"),
    ("Beschriftung auf dem Etikett unleserlich",
     "rework", "wortlaut", "behebbar am Etikett"),
    ("Schraube fehlt, kann nachgesetzt werden",
     "rework", "wortlaut", "fehlendes Teil, behebbar"),
    # -- Kein relevanter Mangel ------------------------------------------
    ("Ware sieht gut aus, alles in Ordnung",
     "sellable", "wortlaut", "ausdruecklich in Ordnung"),
    ("Nur Staub auf der Verpackung, abgewischt",
     "sellable", "wortlaut", "erledigt"),
    ("Artikel einwandfrei, die Meldung war ein Versehen",
     "sellable", "wortlaut", "Fehlmeldung"),
]

ALT = (
    "Du bist Qualitaetspruefer in einem Lager und klassifizierst eine gemeldete "
    "Qualitaetsstoerung in genau eine Disposition. "
    "scrap = Totalschaden/unbrauchbar, quarantine = sperren und pruefen, "
    "rework = Nacharbeit moeglich, sellable = verkaufsfaehig/kein relevanter Mangel. "
    "Nutze ausschliesslich die gegebene Beschreibung und den Kontext, erfinde keine Fakten. "
    "Antworte ausschliesslich mit JSON der Form "
    '{"disposition": <scrap|quarantine|rework|sellable>, '
    '"confidence": <Zahl 0..1>, "summary": <kurze deutsche Begruendung, max 200 Zeichen>}.'
)

NEU = (
    "Du bist Qualitaetspruefer in einem Lager und stufst eine gemeldete "
    "Qualitaetsstoerung in genau eine Disposition ein.\n"
    "Die vier Werte, vom schwersten zum leichtesten:\n"
    "- scrap: der Artikel ist unbrauchbar und nicht zu retten.\n"
    "- quarantine: es ist etwas nicht in Ordnung, aber wie schlimm, steht "
    "nicht fest. Auch Verdacht, Feuchtigkeit, Fremdkoerper, Korrosion.\n"
    "- rework: der Mangel ist benannt und mit einem Handgriff zu beheben --"
    " Etikett, Verpackung, Beschriftung, fehlende Kleinteile.\n"
    "- sellable: kein Mangel, der den Verkauf hindert.\n"
    "Regeln:\n"
    "- Stufe nur so hoch ein, wie die Meldung es HERGIBT. 'beschaedigt', "
    "'defekt', 'kaputt' ohne weitere Angabe sagt NICHT, dass der Artikel "
    "verloren ist. Das ist quarantine, nicht scrap.\n"
    "- scrap nur, wenn die Meldung die Zerstoerung oder die Unbrauchbarkeit "
    "ausspricht: zerbrochen, zersplittert, zerstoert, irreparabel, "
    "unbrauchbar.\n"
    "- Der Zustand der VERPACKUNG ist nicht der Zustand der Ware. Ein "
    "beschaedigter Karton bei heiler Ware ist rework.\n"
    "- Im Zweifel gilt quarantine. Eine Quarantaene kostet eine Pruefung; ein "
    "vorschnelles scrap vernichtet verkaeufliche Ware, ein vorschnelles "
    "sellable schickt Schaden zum Kunden.\n"
    "- Nutze ausschliesslich Beschreibung und Kontext, erfinde keine Fakten. "
    "Prioritaet und Anzahl der Fotos sagen nichts ueber die Schwere.\n"
    "Beispiele:\n"
    "  'Artikel beschaedigt' -> quarantine\n"
    "  'Gehaeuse zersplittert, Teile fehlen' -> scrap\n"
    "  'Karton aufgerissen, Ware unbeschaedigt' -> rework\n"
    "  'Ware in Ordnung' -> sellable\n"
    "Antworte ausschliesslich mit JSON mit diesen Schluesseln, in dieser "
    "Reihenfolge:\n"
    '  "belegstelle": die Woerter der Meldung, auf die du die Schwere '
    'stuetzt, woertlich zitiert -- "keine", wenn die Meldung die Schwere '
    "nicht benennt,\n"
    '  "grundlage": genau eines von "wortlaut" (die Meldung nennt die '
    'Schwere) oder "annahme" (du schliesst sie),\n'
    '  "disposition": <scrap|quarantine|rework|sellable>,\n'
    '  "confidence": <Zahl 0..1>,\n'
    '  "summary": <kurze deutsche Begruendung, max 200 Zeichen>'
)


# Runde 2. Die Dispositionsregeln bleiben WORTGLEICH -- geaendert ist allein
# die Definition von `grundlage`. Grund: in Runde 1 traf die Disposition 19/21,
# aber `grundlage` nur 16/21, und zwar systematisch in die falsche Richtung.
# "Artikel beschaedigt" bekam `wortlaut`, weil das Wort "beschaedigt" ja
# dasteht. Gefragt ist aber nicht, ob ein Mangel benannt ist, sondern ob sein
# AUSMASS benannt ist. Das ist eine Definitionsluecke, keine Korpusanpassung.
NEU2 = NEU.replace(
    '  "grundlage": genau eines von "wortlaut" (die Meldung nennt die '
    'Schwere) oder "annahme" (du schliesst sie),\n',
    '  "grundlage": genau eines von "wortlaut" oder "annahme". "wortlaut" '
    "nur, wenn die Meldung das AUSMASS selbst ausspricht: dass der Artikel "
    "zerstoert oder unbrauchbar ist, dass er in Ordnung ist, oder welcher "
    "Handgriff ihn behebt. Nennt sie bloss, DASS etwas ist, und du schliesst "
    'das Ausmass, dann "annahme". "beschaedigt", "defekt", "kaputt", "stimmt '
    'etwas nicht" allein sind immer "annahme",\n',
)
assert NEU2 != NEU, "Ersetzung in NEU2 hat nicht gegriffen"


def benutzerprompt(text: str) -> str:
    """Wortgleich mit `LlmClient._build_user_prompt` fuer den Messfall.

    Prioritaet 0 und ein Foto: der haeufigste Fall aus der PWA. Beides bleibt
    ueber alle Faelle gleich, damit der Unterschied am Text haengt.
    """
    return "\n".join([
        f"Beschreibung: {text}",
        "Prioritaet: 0",
        "Fotos vorhanden: ja (1)",
    ])


async def frage(client: httpx.AsyncClient, modell: str, system: str, text: str) -> dict:
    resp = await client.post(f"{ENDPOINT}/api/chat", json={
        "model": modell,
        "stream": False,
        "format": "json",
        "options": {"temperature": 0},
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": benutzerprompt(text)},
        ],
    })
    resp.raise_for_status()
    return json.loads(resp.json().get("message", {}).get("content") or "{}")


async def lauf(modell: str, name: str, system: str) -> dict:
    treffer = zu_hoch = zu_niedrig = ausgefallen = 0
    falsches_scrap = 0        # scrap, wo keins hingehoert -- der teure Fehler
    grundlage_treffer = 0
    zeiten: list[float] = []
    zeilen = []
    timeout = httpx.Timeout(connect=5.0, read=180.0, write=10.0, pool=5.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        for text, soll, soll_grund, worum in FAELLE:
            s = time.monotonic()
            try:
                parsed = await frage(client, modell, system, text)
            except Exception as exc:  # noqa: BLE001 - ein Fall darf die Reihe nicht toeten
                parsed = {"fehler": f"{type(exc).__name__}: {exc}"}
            dt = time.monotonic() - s
            zeiten.append(dt)
            ist = str(parsed.get("disposition", "")).strip().lower()
            grund = str(parsed.get("grundlage", "")).strip().lower()
            if ist not in RANG:
                ausgefallen += 1
                marke = "AUSFALL"
            elif ist == soll:
                treffer += 1
                marke = "richtig"
            elif RANG[ist] > RANG[soll]:
                zu_hoch += 1
                marke = "ZU HOCH"
            else:
                zu_niedrig += 1
                marke = "ZU NIEDRIG"
            if ist == "scrap" and soll != "scrap":
                falsches_scrap += 1
            if grund and grund == soll_grund:
                grundlage_treffer += 1
            print(f"  {text[:44]:46} soll={soll:10} ist={ist or '-':10} "
                  f"grund={grund or '-':8} {dt:4.0f}s {marke}", flush=True)
            zeilen.append({
                "text": text, "soll": soll, "ist": ist or None,
                "soll_grundlage": soll_grund, "grundlage": grund or None,
                "konfidenz": parsed.get("confidence"),
                "belegstelle": parsed.get("belegstelle"),
                "summary": parsed.get("summary"),
                "fehler": parsed.get("fehler"),
                "sekunden": round(dt, 1), "worum": worum,
            })
    print(f"  => {name}: richtig {treffer}/{len(FAELLE)}, zu hoch {zu_hoch}, "
          f"zu niedrig {zu_niedrig}, falsches scrap {falsches_scrap}, "
          f"Ausfaelle {ausgefallen}, Grundlage richtig {grundlage_treffer}, "
          f"Median {sorted(zeiten)[len(zeiten) // 2]:.0f}s", flush=True)
    return {"prompt": name, "modell": modell, "treffer": treffer,
            "von": len(FAELLE), "zu_hoch": zu_hoch, "zu_niedrig": zu_niedrig,
            "falsches_scrap": falsches_scrap, "ausfaelle": ausgefallen,
            "grundlage_treffer": grundlage_treffer,
            "median_s": round(sorted(zeiten)[len(zeiten) // 2], 1),
            "faelle": zeilen}


async def main():
    modell = settings.llm_model
    alle = []
    nur = os.environ.get("NUR", "").split(",") if os.environ.get("NUR") else None
    varianten = [("ALT", ALT), ("NEU", NEU), ("NEU2", NEU2)]
    for name, system in [v for v in varianten if not nur or v[0] in nur]:
        print(f"\n=== {name} ({modell})", flush=True)
        alle.append(await lauf(modell, name, system))
        json.dump(alle, open(ERGEBNIS, "w"), ensure_ascii=False, indent=1)
    print("\nFERTIG")


asyncio.run(main())
