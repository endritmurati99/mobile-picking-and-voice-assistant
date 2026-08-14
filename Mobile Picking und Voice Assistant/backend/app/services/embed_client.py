"""Artikelabgleich ueber Bildabstand statt ueber Worte.

**Warum es diesen zweiten Weg gibt.** Der bisherige Abgleich laesst ein
Bildmodell Meldefoto und Katalogbild EINZELN beschreiben und ein Textmodell die
zwei Beschreibungen vergleichen. Damit entscheidet die Wortwahl ueber die
Artikelidentitaet, und das geht reproduzierbar schief: am 2026-08-14 wurde
QA/0331 abgewiesen, obwohl beide Seiten woertlich "light blue" schrieben --
die eine Beschreibung zaehlte die Noppen ("four cylindrical studs"), die andere
nicht. Derselbe Unterschied ging bei QA/0333 durch. Es ist keine Regel, es ist
Zufall. Ebenso QA/0323: "blue" gegen "light blue" am selben Teil.

Hier wird nichts beschrieben. Das Foto wird eingebettet und gegen ALLE
bekannten Artikel gehalten; die Frage lautet nicht "sind diese zwei gleich"
(das braeuchte eine geratene Schwelle, und die Bereiche ueberlappen), sondern
"welcher bekannte Artikel ist das". Der Abstand zum Zweitplatzierten ist die
Konfidenz.

**Drei Urteile, nicht zwei.** `match`, `mismatch`, `unsicher`. Unsicher ist
keine Schwaeche, sondern der Zweck: ein Fall beim Menschen ist billiger als ein
falsches `mismatch`, das eine echte Schadensmeldung abweist.

Wie beim `VisionClient` gilt: jeder Fehler endet in `ok=False` mit leeren
Feldern. Ein halber Befund waere die Einladung, doch etwas daraus zu schliessen
-- und hier waere das besonders teuer, weil der Aufrufer bei `ok=False`
vollstaendig auf den alten Weg zurueckfaellt.
"""
from __future__ import annotations

import base64
import json
import logging
import time
from dataclasses import dataclass, field

import httpx

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class EmbedVerdict:
    ok: bool
    urteil: str | None = None
    grund: str | None = None
    # (kennung, wert), absteigend. Beim Widerspruch ist das die Beweislage,
    # die ein Mensch braucht, um dem Urteil zu widersprechen.
    rang: tuple[tuple[str, float], ...] = field(default_factory=tuple)
    abstand: float | None = None
    # HTTP 409: der Dienst laeuft, hat aber keinen Katalog. Eigener Wert, weil
    # der Aufrufer daraufhin den Katalog neu schiebt statt aufzugeben.
    kein_katalog: bool = False


class EmbedClient:
    PROVIDER = "einbettung-dinov2"

    def __init__(
        self,
        *,
        endpoint: str,
        timeout_ms: int = 15000,
        katalog_timeout_ms: int = 180000,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._endpoint = endpoint.rstrip("/")
        # Zwei Grenzen, weil es zwei sehr verschiedene Aufrufe sind: ein
        # Abgleich ist gemessen 0,36-1,78 s, der Katalogaufbau 26,5 s fuer 47
        # Bilder -- und beim allerersten Mal laedt er zusaetzlich das Modell.
        self._timeout = httpx.Timeout(connect=5.0, read=max(1.0, timeout_ms / 1000.0),
                                      write=30.0, pool=5.0)
        self._katalog_timeout = httpx.Timeout(
            connect=5.0, read=max(1.0, katalog_timeout_ms / 1000.0), write=120.0, pool=5.0
        )
        self._transport = transport

    async def katalog_setzen(self, artikel: list[tuple[str, str]]) -> int | None:
        """Katalog einbetten und halten. `None` heisst: nicht zustande gekommen.

        Der Dienst haelt den Katalog nur im Speicher (bewusst: er ist aus Odoo
        jederzeit neu herstellbar und soll nach einem Neustart nicht veraltet
        weiterleben). Der Aufrufer muss also damit rechnen, ihn erneut schieben
        zu muessen -- deshalb meldet `abgleich` ein 409 gesondert.
        """
        if not artikel:
            return None
        begonnen = time.monotonic()
        nutzlast = {"artikel": [{"kennung": k, "bild_b64": b} for k, b in artikel]}
        try:
            async with httpx.AsyncClient(
                timeout=self._katalog_timeout, transport=self._transport
            ) as client:
                antwort = await client.post(f"{self._endpoint}/katalog", json=nutzlast)
            antwort.raise_for_status()
            daten = antwort.json()
        except Exception as exc:  # noqa: BLE001 - jeder Fehler heisst: kein Katalog
            logger.warning(json.dumps({
                "event_type": "embed_katalog_failed",
                "error_type": type(exc).__name__,
                "error": str(exc),
                "artikel": len(artikel),
                "duration_ms": int((time.monotonic() - begonnen) * 1000),
            }, ensure_ascii=False))
            return None
        gezaehlt = daten.get("artikel") if isinstance(daten, dict) else None
        logger.info(json.dumps({
            "event_type": "embed_katalog",
            "artikel": gezaehlt,
            "duration_ms": int((time.monotonic() - begonnen) * 1000),
        }, ensure_ascii=False))
        return gezaehlt if isinstance(gezaehlt, int) else None

    async def abgleich(self, image: bytes, erwartet: str | None) -> EmbedVerdict:
        """Welcher bekannte Artikel ist auf dem Bild?

        `erwartet` MUSS gesetzt sein, wenn ein Urteil ueber die Meldung fallen
        soll: ohne die Vorgabe antwortet der Dienst mit `match` auf den
        naechstbesten Artikel, und das waere hier eine Aussage ueber nichts.
        Der Aufrufer prueft deshalb vorher, dass die Kennung im Katalog steht.
        """
        begonnen = time.monotonic()
        nutzlast: dict = {"bild_b64": base64.b64encode(image).decode("ascii")}
        if erwartet:
            nutzlast["erwartet"] = erwartet
        try:
            async with httpx.AsyncClient(
                timeout=self._timeout, transport=self._transport
            ) as client:
                antwort = await client.post(f"{self._endpoint}/abgleich", json=nutzlast)
            if antwort.status_code == 409:
                logger.warning(json.dumps({
                    "event_type": "embed_abgleich_failed",
                    "error_type": "KeinKatalog",
                    "error": "Dienst haelt keinen Katalog.",
                    "duration_ms": int((time.monotonic() - begonnen) * 1000),
                }, ensure_ascii=False))
                return EmbedVerdict(ok=False, kein_katalog=True)
            antwort.raise_for_status()
            daten = antwort.json()
        except Exception as exc:  # noqa: BLE001 - jeder Fehler heisst: kein Befund
            logger.warning(json.dumps({
                "event_type": "embed_abgleich_failed",
                "error_type": type(exc).__name__,
                "error": str(exc),
                "duration_ms": int((time.monotonic() - begonnen) * 1000),
            }, ensure_ascii=False))
            return EmbedVerdict(ok=False)

        urteil = daten.get("urteil") if isinstance(daten, dict) else None
        if urteil not in ("match", "mismatch", "unsicher"):
            # Eine Antwort ohne bekanntes Urteil ist keine Antwort. Sie hier
            # durchzulassen hiesse, ein Feld zu erfinden, das der Dienst nicht
            # gesetzt hat -- derselbe Fehler, der am 2026-08-13 eine ganze
            # Messreihe wertlos gemacht hat (`format: json` lieferte `{}`, und
            # `bool(ergebnis.get(...))` machte daraus zwoelf Urteile).
            logger.warning(json.dumps({
                "event_type": "embed_abgleich_failed",
                "error_type": "UnbekanntesUrteil",
                "error": str(daten)[:200],
                "duration_ms": int((time.monotonic() - begonnen) * 1000),
            }, ensure_ascii=False))
            return EmbedVerdict(ok=False)

        rang: list[tuple[str, float]] = []
        for eintrag in (daten.get("rang") or []):
            if isinstance(eintrag, dict) and "kennung" in eintrag:
                try:
                    rang.append((str(eintrag["kennung"]), float(eintrag.get("wert", 0.0))))
                except (TypeError, ValueError):
                    continue
        abstand = daten.get("abstand")
        logger.info(json.dumps({
            "event_type": "embed_abgleich",
            "urteil": urteil,
            "erwartet": erwartet,
            "rang": rang[:3],
            "abstand": abstand,
            "duration_ms": int((time.monotonic() - begonnen) * 1000),
        }, ensure_ascii=False))
        return EmbedVerdict(
            ok=True,
            urteil=urteil,
            grund=(str(daten.get("grund")).strip() or None) if daten.get("grund") else None,
            rang=tuple(rang),
            abstand=float(abstand) if isinstance(abstand, (int, float)) else None,
        )
