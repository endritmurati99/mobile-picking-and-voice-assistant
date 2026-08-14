"""Artikelabgleich ueber Bildabstand statt ueber Worte.

Geprueft wird nicht, ob der Dienst richtig liegt -- das entscheidet die Abnahme
mit echten Fotos --, sondern die vier Dinge, die im Code festliegen muessen:

* dass ein Urteil des Dienstes den Textvergleich ERSETZT und nicht ergaenzt,
* dass JEDER Ausfall auf den bisherigen Weg zurueckfaellt statt zu blockieren,
* dass `unsicher` weder zu `mismatch` noch zu `unavailable` wird,
* dass ohne Kennung im Katalog gar nicht erst gefragt wird.

Der letzte Punkt ist der teuerste: mit unbekanntem `erwartet` antwortet der
Dienst mit einem selbstsicheren `mismatch` (embed/server.py), und das waere
genau das falsche Abweisen, gegen das der ganze Weg gebaut ist.
"""
import base64
import io

import pytest
from PIL import Image

from app import config
from app.routers import n8n_v2
from app.services.embed_client import EmbedVerdict

MEDIA = {
    "product_code": "6023350",
    "product_label": "[6023350] Brick 2x2x2 R=15 gelb",
    "reference_description": "toy building brick, yellow, arch",
}


def _jpeg() -> bytes:
    puffer = io.BytesIO()
    Image.new("RGB", (32, 32), (255, 200, 0)).save(puffer, format="JPEG")
    return puffer.getvalue()


class FakeEmbed:
    def __init__(self, urteil: EmbedVerdict, zweites: EmbedVerdict | None = None):
        self._urteile = [urteil] + ([zweites] if zweites else [])
        self.calls: list[str | None] = []

    async def abgleich(self, image, erwartet):
        self.calls.append(erwartet)
        return self._urteile[min(len(self.calls) - 1, len(self._urteile) - 1)]


class FakeRuntime:
    def __init__(self, embed, kennungen=frozenset({"6023350"}), gueltig=True):
        self._embed = embed
        self._kennungen = kennungen
        self._gueltig = gueltig
        self.verworfen = 0

    def embed_client(self):
        return self._embed

    def katalog_gueltig(self, instanz):
        return self._gueltig

    @property
    def katalog_kennungen(self):
        return self._kennungen

    def katalog_verwerfen(self):
        self.verworfen += 1


class StummesTextmodell:
    async def compare_articles(self, **_):
        raise AssertionError("der Textvergleich darf hier nicht mehr laufen")


class StummeVision:
    async def describe(self, image):
        raise AssertionError("das Bildmodell darf hier nicht mehr laufen")


@pytest.fixture
def primaer(monkeypatch):
    monkeypatch.setattr(config.settings, "embed_mode", "primaer", raising=False)
    return config.settings


async def _abgleich(runtime, lines, deadline=1e9):
    import time

    return await n8n_v2._abgleich_ueber_einbettung(
        runtime, odoo=object(), instanz="o19-a", media=MEDIA,
        candidate=_jpeg(), lines=lines, deadline=time.monotonic() + 60,
    )


@pytest.mark.anyio
async def test_a_match_replaces_the_text_comparison(primaer):
    """Der Punkt der ganzen Uebung: kein Bildmodell, kein Textmodell, ein Abstand."""
    embed = FakeEmbed(EmbedVerdict(
        ok=True, urteil="match",
        grund="Stimmt mit dem Katalogbild ueberein (0.924, Abstand 0.226).",
        rang=(("6023350", 0.924), ("6167549", 0.698)), abstand=0.226,
    ))
    lines: list[str] = []

    ergebnis = await n8n_v2._check_article(
        StummeVision(), StummesTextmodell(), MEDIA, _jpeg(), lines, 1e9,
        runtime=FakeRuntime(embed), odoo=object(), instanz="o19-a",
    )

    assert ergebnis == "match"
    assert embed.calls == ["6023350"]
    # Uebereinstimmung ist der Normalfall und erzeugt KEINE Zeile im
    # Klartext -- sie kostet den Menschen nur Lesezeit. Die Beweislage steht
    # vollstaendig in der `article_compare`-Protokollzeile.
    assert lines == []


@pytest.mark.anyio
async def test_a_mismatch_carries_the_ranking_for_a_human_to_overrule(primaer):
    embed = FakeEmbed(EmbedVerdict(
        ok=True, urteil="mismatch",
        grund="Foto passt zu 4166960 (0.940), nicht zum bestellten Artikel 6023350.",
        rang=(("4166960", 0.94), ("301124", 0.83), ("343724", 0.71)), abstand=0.11,
    ))
    lines: list[str] = []

    ergebnis, hinweis, fremd = await _abgleich(FakeRuntime(embed), lines)

    assert ergebnis == "mismatch"
    assert hinweis is None and fremd is False
    # Die Rangfolge IST die Beweislage. Ohne sie kann niemand widersprechen.
    assert any("4166960 0.940" in zeile for zeile in lines)


@pytest.mark.anyio
async def test_unsicher_falls_back_and_never_becomes_a_verdict(primaer):
    """`unsicher` trifft das Hundefoto (0,204) genauso wie ein schlecht
    belichtetes Teil. Als `mismatch` waere es das falsche Abweisen, gegen das
    dieser Weg gebaut ist; als `unavailable` ginge der Hundefall verloren, den
    der bisherige Weg zuverlaessig trifft."""
    embed = FakeEmbed(EmbedVerdict(
        ok=True, urteil="unsicher",
        grund="Kein bekannter Artikel: beste Uebereinstimmung 0.204 unter 0.45.",
    ))
    lines: list[str] = []

    ergebnis, hinweis, _ = await _abgleich(FakeRuntime(embed), lines)

    assert ergebnis is None
    # Der Hinweis reist mit, damit der Befund nicht lautlos verschwindet, wenn
    # auch der Rueckfallweg ausfaellt.
    assert hinweis is not None and "0.204" in hinweis
    assert lines == []


@pytest.mark.anyio
async def test_a_dead_service_falls_back_instead_of_blocking(primaer):
    embed = FakeEmbed(EmbedVerdict(ok=False))
    lines: list[str] = []

    assert await _abgleich(FakeRuntime(embed), lines) == (None, None, False)
    assert lines == []


@pytest.mark.anyio
async def test_an_unknown_article_is_never_asked_about(primaer):
    """23 von 70 Artikeln haben kein Katalogbild. Mit unbekanntem `erwartet`
    antwortet der Dienst mit einem selbstsicheren `mismatch` -- also gar nicht
    erst fragen."""
    embed = FakeEmbed(EmbedVerdict(ok=True, urteil="mismatch", grund="erfunden"))
    lines: list[str] = []

    ergebnis, _, _ = await _abgleich(FakeRuntime(embed, kennungen=frozenset()), lines)

    assert ergebnis is None
    assert embed.calls == []


@pytest.mark.anyio
async def test_a_restarted_service_gets_its_catalogue_pushed_again(primaer):
    """409 heisst: der Dienst laeuft, haelt aber nichts mehr. Einmal neu
    aufbauen und ein zweites Mal fragen -- danach nicht weiter."""
    embed = FakeEmbed(
        EmbedVerdict(ok=False, kein_katalog=True),
        EmbedVerdict(ok=True, urteil="match", grund="Stimmt ueberein (0.92).",
                     rang=(("6023350", 0.92),), abstand=0.2),
    )
    runtime = FakeRuntime(embed)
    lines: list[str] = []

    ergebnis, _, _ = await _abgleich(runtime, lines)

    assert runtime.verworfen == 1
    assert embed.calls == ["6023350", "6023350"]
    assert ergebnis == "match"


@pytest.mark.anyio
async def test_shadow_mode_measures_without_deciding(monkeypatch):
    """Fuer eine Messreihe im Betrieb: der Dienst laeuft mit und protokolliert,
    entscheidet aber nichts."""
    monkeypatch.setattr(config.settings, "embed_mode", "schatten", raising=False)
    embed = FakeEmbed(EmbedVerdict(ok=True, urteil="mismatch", grund="egal"))
    lines: list[str] = []

    assert await _abgleich(FakeRuntime(embed), lines) == (None, None, False)
    assert embed.calls == ["6023350"]
    assert lines == []


@pytest.mark.anyio
async def test_without_a_runtime_nothing_changes(primaer):
    """Der bisherige Weg muss ohne den neuen aufrufbar bleiben -- sonst haengt
    jeder Aufrufer, der die Runtime nicht kennt, in der Luft."""
    assert await n8n_v2._abgleich_ueber_einbettung(
        None, None, "", MEDIA, _jpeg(), [], 1e9
    ) == (None, None, False)


def test_the_default_is_primaer_and_measured():
    """Der Standard steht auf `primaer`, weil der Textvergleich am 2026-08-14
    ueber zehn Meldungen drei richtige Teile abgewiesen hat -- QA/0323 auf
    "blue" gegen "light blue", QA/0331 auf "studs" gegen "four cylindrical
    studs" bei zweimal woertlich "light blue", QA/0329 auf "arch-shaped" gegen
    "rounded top" -- und denselben Wortunterschied bei QA/0333 durchliess.
    Wer das umstellt, soll an diesem Test vorbei muessen."""
    from app.config import Settings

    frisch = Settings(_env_file=None)
    assert frisch.embed_mode == "primaer"
    assert frisch.embed_url == "http://embed:8000"
    # Der Abgleich muss weit innerhalb des Bildbudgets liegen, sonst bleibt
    # fuer den Rueckfallweg keine Zeit mehr.
    assert frisch.embed_timeout_ms * 4 < frisch.vision_budget_ms


@pytest.mark.anyio
async def test_an_uncertain_embedding_survives_a_dead_fallback(primaer):
    """Der Hundefall, live eingefangen (QA/0340 und QA/0341, 2026-08-14).

    Die Einbettung fiel korrekt auf `unsicher` -- bester Treffer 0,203 gegen
    die Schwelle 0,45, echte Teile liegen bei 0,82 bis 0,999 -- und danach
    starb der Rueckfallweg an einem Ollama-500 (`gemma4:12b` passte nach dem
    Hinzukommen des Einbettungsdienstes nicht mehr in den Speicher). Uebrig
    blieb "Artikelabgleich nicht moeglich", und eine Meldung mit Hundefoto lief
    als `completed` durch. Genau der Fall, fuer den die Bildpruefung gebaut
    wurde -- der Hinweis muss ihn auffangen.
    """
    embed = FakeEmbed(EmbedVerdict(
        ok=True, urteil="unsicher",
        grund="Kein bekannter Artikel: beste Uebereinstimmung 0.203 unter der Schwelle 0.45.",
        grund_art="kein_treffer",
    ))

    class ToteVision:
        async def describe(self, image):
            from app.services.vision_client import ArticleDescription
            return ArticleDescription(ok=False)

    lines: list[str] = []
    ergebnis = await n8n_v2._check_article(
        ToteVision(), StummesTextmodell(), MEDIA, _jpeg(), lines, 1e9,
        runtime=FakeRuntime(embed), odoo=object(), instanz="o19-a",
    )

    # `mismatch` heisst hier NICHT "falsches Teil", sondern "das kann niemand
    # mehr beurteilen": es setzt den Widerspruch und damit `review_required`,
    # es sondert nichts aus.
    assert ergebnis == "mismatch"
    assert any("0.203" in zeile for zeile in lines)
    assert any("nicht beurteilbar" in zeile for zeile in lines)


@pytest.mark.anyio
async def test_a_working_fallback_keeps_the_last_word(primaer):
    """Sagt der alte Weg etwas, hat er das letzte Wort. Zwei sich
    widersprechende Zeilen im Odoo-Formular waeren schlimmer als eine
    fehlende."""
    from app.services.llm_client import ArticleComparison
    from app.services.vision_client import ArticleDescription

    embed = FakeEmbed(EmbedVerdict(ok=True, urteil="unsicher", grund="unsicher 0.203"))

    class GuteVision:
        async def describe(self, image):
            return ArticleDescription(ok=True, text="toy brick, yellow", is_a_product=True)

    class GutesTextmodell:
        async def compare_articles(self, **_):
            return ArticleComparison(ok=True, same_article=True, reason="passt",
                                     differs="kein_artikel")

    lines: list[str] = []
    ergebnis = await n8n_v2._check_article(
        GuteVision(), GutesTextmodell(), MEDIA, _jpeg(), lines, 1e9,
        runtime=FakeRuntime(embed), odoo=object(), instanz="o19-a",
    )

    assert ergebnis == "match"
    assert not any("0.203" in zeile for zeile in lines)


@pytest.mark.anyio
async def test_two_articles_too_close_never_becomes_a_verdict(primaer):
    """`zu_dicht` ist das Gegenteil von `kein_treffer`: da WEISS der Dienst
    nichts, weil zwei Artikel im Sortiment sich am Bild nicht trennen lassen
    (`6167549` gegen `6171865`). Daraus darf auch dann kein Urteil werden, wenn
    der Rueckfallweg ebenfalls schweigt -- sonst waere jede Beinahe-Dublette im
    Sortiment ein Widerspruch."""
    from app.services.vision_client import ArticleDescription

    embed = FakeEmbed(EmbedVerdict(
        ok=True, urteil="unsicher", grund_art="zu_dicht",
        grund="6167549 und 6171865 liegen zu dicht beieinander (0.0041).",
    ))

    class ToteVision:
        async def describe(self, image):
            return ArticleDescription(ok=False)

    lines: list[str] = []
    ergebnis = await n8n_v2._check_article(
        ToteVision(), StummesTextmodell(), MEDIA, _jpeg(), lines, 1e9,
        runtime=FakeRuntime(embed), odoo=object(), instanz="o19-a",
    )

    assert ergebnis == "unavailable"
    assert any("zu dicht" in zeile for zeile in lines)
    assert not any("nicht beurteilbar" in zeile for zeile in lines)


@pytest.mark.anyio
async def test_a_working_fallback_beats_the_foreign_signal(primaer):
    """Auch beim Fremdbild hat der alte Weg das letzte Wort, solange er eines
    hat. Er trifft den Hundefall zuverlaessig ("dog" gegen "building block") --
    die Eskalation greift NUR in der Luecke, in der niemand mehr etwas sagt."""
    from app.services.llm_client import ArticleComparison
    from app.services.vision_client import ArticleDescription

    embed = FakeEmbed(EmbedVerdict(
        ok=True, urteil="unsicher", grund_art="kein_treffer", grund="nichts nahe (0.203)",
    ))

    class SiehtHund:
        async def describe(self, image):
            return ArticleDescription(ok=True, text="dog, cream-colored", is_a_product=False)

    class ErkenntUnterschied:
        async def compare_articles(self, **_):
            return ArticleComparison(ok=True, same_article=False,
                                     reason="Tier gegen Bauteil", differs="kein_artikel")

    lines: list[str] = []
    ergebnis = await n8n_v2._check_article(
        SiehtHund(), ErkenntUnterschied(), MEDIA, _jpeg(), lines, 1e9,
        runtime=FakeRuntime(embed), odoo=object(), instanz="o19-a",
    )

    assert ergebnis == "mismatch"
    assert any("FALSCHES TEIL" in zeile for zeile in lines)
    assert not any("nicht beurteilbar" in zeile for zeile in lines)
