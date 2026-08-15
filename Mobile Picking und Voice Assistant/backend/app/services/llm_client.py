"""Lokaler LLM-Client (Ollama) fuer die Qualitaetsbewertung aus dem TEXT.

Laeuft offline auf dem Lab-PC gegen einen Ollama-Container. Erzwingt
JSON-Output (`format: "json"`) und liefert bei jedem Fehler `ok=False` -- der
Workflow meldet dann `review_required` statt eines Ersatzurteils. Eine
Heuristik als Rueckfallebene gibt es seit dem v2-Umbau nicht mehr; sie stand
in den geloeschten v1-Workflows.

Den Bildbefund liefert `vision_client` getrennt. Dieses Modell bekommt ihn
bewusst NICHT: nur so laesst sich sein Urteil anschliessend dagegen pruefen.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass

import httpx

logger = logging.getLogger(__name__)

# Die vier Dispositionen der Kette. Sie stehen auch in `quality_alert.py`
# als Auswahlwerte -- wer hier etwas hinzufuegt, muss dort nachziehen.
VALID_DISPOSITIONS = ("scrap", "quarantine", "rework", "sellable")

# Deterministische Handlungsempfehlung je Disposition. Bewusst NICHT vom
# Modell formuliert: was ein Lager tun soll, ist eine Festlegung des
# Betriebs und keine Frage an ein Sprachmodell.
RECOMMENDED_ACTIONS = {
    "scrap": "Ware sperren, aussondern und Schichtleitung informieren.",
    "quarantine": "Ware sperren und manuelle Prüfung anfordern.",
    "rework": "Nacharbeit prüfen und Verpackung korrigieren.",
    "sellable": "Sichtprüfung durch Qualitätsteam.",
}

# **Der Schweregrad war durch nichts gedeckt.** Bis zum 2026-08-15 beschrieb
# dieser Prompt die vier Werte in je drei Worten -- ohne Abstufungsregel, ohne
# Zweifelsfall, ohne Beispiel, waehrend die beiden anderen Prompts derselben
# Datei genau das haben. Gemessen: "Artikel beschaedigt" wurde `scrap` mit
# Konfidenz 0,90. Der Satz sagt, dass etwas nicht stimmt; er sagt nicht, dass
# die Ware verloren ist.
#
# `scrap` ist die einzige der vier Dispositionen, die sich nicht
# zurueckdrehen laesst -- ausgesonderte Ware kommt nicht wieder. Der
# Zweifelsfall gilt darum quarantine: eine Quarantaene kostet eine Pruefung.
#
# **`belegstelle` und `grundlage` sind Messgeraet, nicht Steuerung** -- derselbe
# Gedanke wie `unterschied` im Vergleichsprompt. `grundlage` trennt, ob die
# MELDUNG die Schwere ausspricht oder ob das Modell sie schliesst; erst damit
# kann `reconcile` ein ungedecktes Totalschaden-Urteil erkennen, statt nur den
# String `scrap` zu sehen. `belegstelle` steht davor, weil das Zitat vor dem
# Urteil kommen muss: wird zuerst nach dem Urteil gefragt, antwortet das Modell
# aus dem Schema statt aus der Sache (gemessen am 2026-08-05 in
# `vision_client.DESCRIBE_PROMPT`, wiederholt am 2026-08-09 im Textvergleich).
#
# **Gemessen** (`infrastructure/bildkorpus/schweregradmessung.py`, 21
# beschriftete Meldetexte, `qwen2.5:7b`): alter Prompt 11/21 richtig mit 3
# falschen `scrap`, dieser hier 19/21 mit 1. Median 10 s -> 15 s.
#
# **`grundlage` brauchte eine zweite Runde.** In der ersten Fassung hiess es
# nur "die Meldung nennt die Schwere" -- und "Artikel beschaedigt" bekam
# `wortlaut`, weil das Wort ja dasteht. Gefragt ist aber das AUSMASS, nicht der
# Mangel. Mit der scharfen Fassung kippt genau dieser Fall auf `annahme`, die
# Disposition bleibt bei 19/21. Was offen bleibt: "Ware kaputt" urteilt
# weiterhin `scrap` mit `wortlaut` und laeuft damit an der Regel in
# `reconcile` vorbei -- der einzige verbliebene Fall im Korpus, in dem
# geschlossene Schwere Ware vernichtet.
_SYSTEM_PROMPT = (
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
    '  "grundlage": genau eines von "wortlaut" oder "annahme". "wortlaut" '
    "nur, wenn die Meldung das AUSMASS selbst ausspricht: dass der Artikel "
    "zerstoert oder unbrauchbar ist, dass er in Ordnung ist, oder welcher "
    "Handgriff ihn behebt. Nennt sie bloss, DASS etwas ist, und du schliesst "
    'das Ausmass, dann "annahme". "beschaedigt", "defekt", "kaputt", "stimmt '
    'etwas nicht" allein sind immer "annahme",\n'
    '  "disposition": <scrap|quarantine|rework|sellable>,\n'
    '  "confidence": <Zahl 0..1>,\n'
    '  "summary": <kurze deutsche Begruendung, max 200 Zeichen>'
)

# Geschlossene Liste, wie `_UNTERSCHIEDE`. Ein Wert ausserhalb ist keine
# Auskunft: `grundlage=None` heisst "unbekannt" und loest nichts aus. Nur ein
# ausdrueckliches "annahme" kann ein `scrap` zum Menschen schicken -- ein
# missverstandenes Wort darf nicht dieselbe Wirkung haben wie eine Aussage.
_GRUNDLAGEN = frozenset({"wortlaut", "annahme"})


# **Erst die Formen benennen, dann urteilen.** Derselbe Grundsatz wie in
# `vision_client.DESCRIBE_PROMPT`, dort am 2026-08-05 gemessen: wird zuerst
# nach dem Urteil gefragt, antwortet das Modell aus dem Schema statt aus der
# Sache. Fuer den Textvergleich galt der Satz bis 2026-08-09 noch nicht -- und
# genau dort fiel er auf. QA/0315: SOLL "square base with a rounded arched
# top", IST "half-cylinder on top of square base", Antwort "Andere Bauform".
# Derselbe Stein, zweimal anders erzaehlt.
#
# **Die beiden Regeln widersprachen sich.** "Andere Bauform heisst anderer
# Artikel" und "andere Wortwahl heisst NICHT anderer Artikel" standen
# nebeneinander, ohne zu sagen, welche im Zweifel gilt; das Modell entschied
# auf mismatch. Der Zweifel wird jetzt ausdruecklich aufgeloest -- und zwar
# zugunsten von "dasselbe Teil", weil die Farbe die Verwechslungen abfaengt,
# die im Lager wirklich vorkommen, und ein falsches mismatch eine korrekte
# Bewertung verwirft (QA/0227, Ausfuehrung 46: `sellable`, Konfidenz 1.0).
#
# **`unterschied` ist Messgeraet, nicht Steuerung.** Es entscheidet nichts; es
# schreibt auf, WORAN das Modell den Unterschied festmacht. Ohne dieses Feld
# laesst sich nicht auszaehlen, ob Fehlurteile an Farbe, Bauform oder
# Artikelart haengen -- und ohne diese Zahl waere jede weitere Prompt-Aenderung
# wieder geraten.
_COMPARE_SYSTEM_PROMPT = (
    "Du vergleichst zwei Beschreibungen von Gegenstaenden und entscheidest, ob "
    "es sich um denselben Artikel handelt. "
    "Beschreibung A stammt vom Katalogbild des bestellten Artikels, "
    "Beschreibung B vom Foto, das ein Kommissionierer gerade gemacht hat. "
    "Beide Beschreibungen stammen von einem Bildmodell und sind unterschiedlich "
    "formuliert, auch wenn dasselbe Teil gemeint ist. Sie sehen den Gegenstand "
    "ausserdem aus verschiedenen Blickwinkeln: dieselbe Woelbung heisst einmal "
    "'rounded top' und einmal 'half-cylinder'.\n"
    "Regeln:\n"
    "- Andere FARBE heisst anderer Artikel.\n"
    "- Eine andere Bauform heisst nur dann anderer Artikel, wenn die beiden "
    "Formen sich WIDERSPRECHEN und nicht bloss anders benannt sind.\n"
    "- Andere Wortwahl fuer dasselbe Teil heisst NICHT anderer Artikel. "
    "Im Zweifel gilt: dasselbe Teil.\n"
    "- Schaeden, Schmutz, Lichtverhaeltnisse und Blickwinkel aendern den Artikel "
    "nicht.\n"
    "- Ist B ueberhaupt kein Artikel (Tier, Person, Raum), dann false.\n"
    "Antworte ausschliesslich mit JSON mit diesen Schluesseln, in dieser "
    "Reihenfolge:\n"
    '  "formvergleich": beschreibe in einem Satz, welche Form A und welche '
    "Form B nennt und ob dieselbe Gestalt gemeint sein kann,\n"
    '  "unterschied": woran der Unterschied haengt -- genau eines von '
    '"farbe", "bauform", "artikelart", "aufdruck", "kein_artikel", "keins",\n'
    '  "same_article": true oder false,\n'
    '  "reason": ein kurzer deutscher Satz.'
)

# Die Liste ist geschlossen. Ein Wert ausserhalb ist keine Auskunft und wird
# auch nicht als eine gezaehlt -- sonst stehen in der Auswertung Kategorien,
# die niemand definiert hat.
_UNTERSCHIEDE = frozenset(
    {"farbe", "bauform", "artikelart", "aufdruck", "kein_artikel", "keins"}
)


_CONDITION_SYSTEM_PROMPT = (
    "Du vergleichst den SOLL-Zustand eines Artikels mit seinem IST-Zustand und "
    "entscheidest, ob das Foto einen Schaden zeigt, den der Neuzustand nicht hat. "
    "Beschreibung SOLL stammt vom Katalogbild des Artikels im Neuzustand, "
    "Beschreibung IST vom Foto, das ein Kommissionierer gerade gemacht hat. "
    "Beide stammen von einem Bildmodell und sind unterschiedlich formuliert, "
    "auch wenn derselbe Zustand gemeint ist.\n"
    "Regeln:\n"
    "- Eine Auffaelligkeit, die SOLL genauso zeigt, ist ein Merkmal des Artikels "
    "und KEIN Schaden. Noppen, Kanten, Naehte und Aufdrucke gehoeren dazu.\n"
    "- Fehlt im IST ein Teil, das SOLL hat, ist das ein Schaden -- auch dann, "
    "wenn keine gerissene Kante beschrieben ist.\n"
    "- Riss, Bruch, Kerbe oder eine ausgefranste Stelle, die SOLL nicht nennt, "
    "ist ein Schaden.\n"
    "- Licht, Blickwinkel, Schatten, Hintergrund und Bildschaerfe sind KEIN "
    "Schaden.\n"
    "- Im Zweifel true. Ein gemeldeter Schaden, der keiner ist, kostet eine "
    "Sichtpruefung; ein uebersehener Schaden verlaesst das Lager.\n"
    "Antworte ausschliesslich mit JSON der Form "
    '{"new_damage": <true|false>, "reason": <ein kurzer deutscher Satz>}.'
)


@dataclass(frozen=True)
class ArticleComparison:
    """`ok=False` heisst: kein Befund. Nicht "kein Treffer"."""

    ok: bool
    same_article: bool | None = None
    reason: str | None = None
    # Woran das Modell den Unterschied festmacht -- Messgroesse, keine
    # Steuerung. `None` heisst: nicht benannt oder ausserhalb der Liste.
    differs: str | None = None


@dataclass(frozen=True)
class ConditionComparison:
    """`ok=False` heisst: kein Befund. Nicht "kein Schaden"."""

    ok: bool
    new_damage: bool | None = None
    reason: str | None = None


@dataclass(frozen=True)
class LlmDispositionResult:
    ok: bool
    model: str
    disposition: str | None = None
    confidence: float | None = None
    summary: str | None = None
    recommended_action: str | None = None
    # Woher die Schwere kommt: "wortlaut" (die Meldung nennt sie) oder
    # "annahme" (das Modell schliesst sie). `None` heisst nicht benannt oder
    # ausserhalb der Liste -- und wirkt wie "unbekannt", nicht wie "annahme".
    grundlage: str | None = None
    # Das Zitat, auf das sich die Schwere stuetzt. Reine Nachlese fuer die
    # Auswertung; es entscheidet nichts.
    belegstelle: str | None = None


class LlmClient:
    PROVIDER = "ollama-local"

    def __init__(
        self,
        *,
        endpoint: str,
        model: str,
        timeout_ms: int = 30000,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._endpoint = endpoint.rstrip("/")
        self._model = model
        seconds = max(1.0, timeout_ms / 1000.0)
        self._timeout = httpx.Timeout(connect=5.0, read=seconds, write=10.0, pool=5.0)
        self._transport = transport

    def _build_user_prompt(
        self,
        *,
        description: str,
        priority: str,
        photo_count: int,
        product_id: int | None,
        location_id: int | None,
    ) -> str:
        lines = [
            f"Beschreibung: {description.strip() or '<leer>'}",
            f"Prioritaet: {priority}",
            f"Fotos vorhanden: {'ja (' + str(photo_count) + ')' if photo_count > 0 else 'nein'}",
        ]
        if product_id:
            lines.append(f"Produkt-ID: {product_id}")
        if location_id:
            lines.append(f"Lagerort-ID: {location_id}")
        # Hier stand: "Wichtig: Es stehen keine Bildinhalte zur Verfuegung,
        # nur der Text." Der Satz war ab Task 10 wahr und ist es nicht mehr --
        # die Bilder werden jetzt geprueft, nur eben nicht von DIESEM Modell.
        # Er richtete zusaetzlich Schaden an: bei QA/0011 begruendete das
        # Modell sein Urteil mit "keine Bilder verfuegbar, daher als
        # Totalschaden eingestuft" und rechnete das fehlende Bild als
        # erschwerenden Umstand.
        #
        # Der Bildbefund kommt hier bewusst NICHT hinein. Diese Bewertung
        # bleibt eine reine Textbewertung -- genau deshalb laesst sie sich
        # anschliessend gegen den Bildbefund pruefen. Ein Modell, das beide
        # Quellen saehe, koennte einen Widerspruch wegerklaeren.
        return "\n".join(lines)

    async def classify_disposition(
        self,
        *,
        description: str,
        priority: str = "0",
        photo_count: int = 0,
        product_id: int | None = None,
        location_id: int | None = None,
    ) -> LlmDispositionResult:
        payload = {
            "model": self._model,
            "stream": False,
            "format": "json",
            "options": {"temperature": 0},
            "messages": [
                {"role": "system", "content": _SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": self._build_user_prompt(
                        description=description,
                        priority=priority,
                        photo_count=photo_count,
                        product_id=product_id,
                        location_id=location_id,
                    ),
                },
            ],
        }
        try:
            async with httpx.AsyncClient(timeout=self._timeout, transport=self._transport) as client:
                resp = await client.post(f"{self._endpoint}/api/chat", json=payload)
            resp.raise_for_status()
            content = resp.json().get("message", {}).get("content")
            return self._parse(content)
        except Exception as exc:  # noqa: BLE001 - jeder Fehler => kein Urteil
            logger.warning(json.dumps({
                "event_type": "llm_quality_disposition_failed",
                "model": self._model,
                "error": str(exc),
            }))
            return LlmDispositionResult(ok=False, model=self._model)

    async def compare_articles(
        self,
        *,
        reference_text: str,
        candidate_text: str,
        product_label: str = "",
    ) -> ArticleComparison:
        """Entscheidet aus ZWEI Beschreibungen, ob es derselbe Artikel ist.

        Das Bildmodell sieht hier nichts mehr; es hat vorher jedes Bild einzeln
        beschrieben. Der Grund steht in `vision_client.DESCRIBE_PROMPT`: mit
        beiden Bildern in einem Aufruf beschrieb es aehnliche Bilder gleich und
        haette einen verwechselten Artikel durchgewinkt.

        `product_label` ist der Artikelname aus Odoo. Er reist als Kontext mit,
        aber die Entscheidung faellt auf den Beschreibungen: der Name beschreibt,
        was bestellt wurde, und nicht, was auf dem Foto liegt.
        """
        lines = [f"Beschreibung A (Katalogbild): {reference_text.strip()}"]
        if product_label.strip():
            lines.append(f"Artikelname laut Auftrag: {product_label.strip()}")
        lines.append(f"Beschreibung B (Meldefoto): {candidate_text.strip()}")
        payload = {
            "model": self._model,
            "stream": False,
            "format": "json",
            "options": {"temperature": 0},
            "messages": [
                {"role": "system", "content": _COMPARE_SYSTEM_PROMPT},
                {"role": "user", "content": "\n".join(lines)},
            ],
        }
        try:
            async with httpx.AsyncClient(
                timeout=self._timeout, transport=self._transport
            ) as client:
                resp = await client.post(f"{self._endpoint}/api/chat", json=payload)
            resp.raise_for_status()
            parsed = json.loads(resp.json().get("message", {}).get("content") or "")
        except Exception as exc:  # noqa: BLE001 - jeder Fehler => kein Befund
            logger.warning(json.dumps({
                "event_type": "llm_article_compare_failed",
                "model": self._model,
                "error_type": type(exc).__name__,
                "error": str(exc),
            }))
            return ArticleComparison(ok=False)
        if not isinstance(parsed, dict) or not isinstance(
            parsed.get("same_article"), bool
        ):
            return ArticleComparison(ok=False)
        reason = str(parsed.get("reason", "")).strip() or None
        unterschied = str(parsed.get("unterschied", "")).strip().lower()
        return ArticleComparison(
            ok=True,
            same_article=parsed["same_article"],
            reason=reason,
            differs=unterschied if unterschied in _UNTERSCHIEDE else None,
        )

    async def compare_condition(
        self,
        *,
        reference_text: str,
        candidate_text: str,
        product_label: str = "",
    ) -> ConditionComparison:
        """Entscheidet aus ZWEI Zustandsbefunden, ob das Foto NEUEN Schaden zeigt.

        Dieselbe Trennung wie beim Artikelabgleich, aus demselben gemessenen
        Grund: das Bildmodell hat beide Bilder in EINEM Aufruf angeglichen und
        einen sichtbaren Bruch als "decorative element" abgetan. Also sieht es
        jedes Bild einzeln, und der Vergleich faellt hier im Text.

        Der Unterschied zum Artikelabgleich ist die Frage, nicht das Verfahren.
        Dort: ist es dasselbe Teil? Hier: ist es dasselbe Teil in schlechterem
        Zustand? Ein sauber abgebrochenes Eck beantwortet beide Fragen
        verschieden -- der Artikel bleibt derselbe, der Zustand nicht -- und
        genau dieser Fall faellt ohne den Vergleich durch: eine glatte
        Bruchflaeche ist keine ausgefranste Stelle, `DAMAGE_PROMPT` allein
        sieht sie nicht.
        """
        lines = [f"Beschreibung SOLL (Katalogbild, Neuzustand): {reference_text.strip()}"]
        if product_label.strip():
            lines.append(f"Artikelname laut Auftrag: {product_label.strip()}")
        lines.append(f"Beschreibung IST (Meldefoto): {candidate_text.strip()}")
        payload = {
            "model": self._model,
            "stream": False,
            "format": "json",
            "options": {"temperature": 0},
            "messages": [
                {"role": "system", "content": _CONDITION_SYSTEM_PROMPT},
                {"role": "user", "content": "\n".join(lines)},
            ],
        }
        try:
            async with httpx.AsyncClient(
                timeout=self._timeout, transport=self._transport
            ) as client:
                resp = await client.post(f"{self._endpoint}/api/chat", json=payload)
            resp.raise_for_status()
            parsed = json.loads(resp.json().get("message", {}).get("content") or "")
        except Exception as exc:  # noqa: BLE001 - jeder Fehler => kein Befund
            logger.warning(json.dumps({
                "event_type": "llm_condition_compare_failed",
                "model": self._model,
                "error_type": type(exc).__name__,
                "error": str(exc),
            }))
            return ConditionComparison(ok=False)
        if not isinstance(parsed, dict) or not isinstance(
            parsed.get("new_damage"), bool
        ):
            return ConditionComparison(ok=False)
        reason = str(parsed.get("reason", "")).strip() or None
        return ConditionComparison(
            ok=True, new_damage=parsed["new_damage"], reason=reason
        )

    def _parse(self, content: str | None) -> LlmDispositionResult:
        if not content or not isinstance(content, str):
            return LlmDispositionResult(ok=False, model=self._model)
        try:
            parsed = json.loads(content)
        except (TypeError, ValueError):
            return LlmDispositionResult(ok=False, model=self._model)
        if not isinstance(parsed, dict):
            return LlmDispositionResult(ok=False, model=self._model)

        disposition = str(parsed.get("disposition", "")).strip().lower()
        if disposition not in VALID_DISPOSITIONS:
            return LlmDispositionResult(ok=False, model=self._model)

        try:
            confidence = float(parsed.get("confidence"))
        except (TypeError, ValueError):
            return LlmDispositionResult(ok=False, model=self._model)
        confidence = max(0.0, min(1.0, round(confidence, 2)))

        summary = str(parsed.get("summary", "")).strip()
        if not summary:
            summary = f"LLM-Einstufung: {disposition}."
        summary = summary[:200]

        # Fehlende oder unbekannte Zusatzfelder machen das Urteil NICHT
        # ungueltig. Sie sind Nachlese; ein Modell, das nur die drei alten
        # Schluessel liefert, bleibt brauchbar.
        grundlage = str(parsed.get("grundlage", "")).strip().lower()
        belegstelle = str(parsed.get("belegstelle", "")).strip()

        return LlmDispositionResult(
            ok=True,
            model=self._model,
            disposition=disposition,
            confidence=confidence,
            summary=summary,
            recommended_action=RECOMMENDED_ACTIONS[disposition],
            grundlage=grundlage if grundlage in _GRUNDLAGEN else None,
            belegstelle=belegstelle[:200] or None,
        )
