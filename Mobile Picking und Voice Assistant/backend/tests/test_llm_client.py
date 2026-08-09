import json

import httpx
import pytest

from app.services.llm_client import LlmClient, RECOMMENDED_ACTIONS


def _client_with(handler):
    return LlmClient(
        endpoint="http://ollama:11434",
        model="qwen2.5:7b",
        timeout_ms=5000,
        transport=httpx.MockTransport(handler),
    )


@pytest.mark.anyio
async def test_classify_disposition_parses_valid_json():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        captured["body"] = json.loads(request.content)
        content = json.dumps({"disposition": "scrap", "confidence": 0.91, "summary": "Totalschaden am Karton."})
        return httpx.Response(200, json={"message": {"role": "assistant", "content": content}})

    client = _client_with(handler)
    result = await client.classify_disposition(description="Karton komplett zerbrochen", priority="1", photo_count=2)

    assert captured["path"] == "/api/chat"
    assert captured["body"]["format"] == "json"
    assert captured["body"]["model"] == "qwen2.5:7b"
    assert result.ok is True
    assert result.disposition == "scrap"
    assert result.confidence == 0.91
    assert result.summary == "Totalschaden am Karton."
    assert result.recommended_action == RECOMMENDED_ACTIONS["scrap"]
    assert result.model == "qwen2.5:7b"


@pytest.mark.anyio
async def test_classify_disposition_clamps_confidence_and_defaults_summary():
    def handler(request: httpx.Request) -> httpx.Response:
        content = json.dumps({"disposition": "REWORK", "confidence": 1.7, "summary": "  "})
        return httpx.Response(200, json={"message": {"content": content}})

    result = await _client_with(handler).classify_disposition(description="Etikett schief")

    assert result.ok is True
    assert result.disposition == "rework"  # normalized lowercase
    assert result.confidence == 1.0  # clamped to [0,1]
    assert result.summary == "LLM-Einstufung: rework."


@pytest.mark.anyio
async def test_invalid_category_returns_not_ok():
    def handler(request: httpx.Request) -> httpx.Response:
        content = json.dumps({"disposition": "explode", "confidence": 0.5, "summary": "x"})
        return httpx.Response(200, json={"message": {"content": content}})

    result = await _client_with(handler).classify_disposition(description="foo")

    assert result.ok is False
    assert result.disposition is None
    assert result.model == "qwen2.5:7b"


@pytest.mark.anyio
async def test_non_json_content_returns_not_ok():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"message": {"content": "kein json"}})

    result = await _client_with(handler).classify_disposition(description="foo")
    assert result.ok is False


@pytest.mark.anyio
async def test_http_error_returns_not_ok():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    result = await _client_with(handler).classify_disposition(description="foo")
    assert result.ok is False


@pytest.mark.anyio
async def test_transport_exception_returns_not_ok():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("ollama down")

    result = await _client_with(handler).classify_disposition(description="foo")
    assert result.ok is False


# --- Artikelvergleich -------------------------------------------------------
# Er liegt beim TEXTmodell, seit gemessen wurde, dass das Bildmodell zwei
# aehnliche Bilder in einem Aufruf gleich beschreibt (siehe vision_client).


@pytest.mark.anyio
async def test_compare_articles_sends_both_descriptions_and_the_label():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        captured["body"] = json.loads(request.content)
        content = json.dumps({"same_article": False, "reason": "Andere Farbe."})
        return httpx.Response(200, json={"message": {"content": content}})

    result = await _client_with(handler).compare_articles(
        reference_text="toy building brick, yellow, 2x2 studs",
        candidate_text="toy building brick, light blue, 2x2 studs",
        product_label="[6023350] Brick 2x2x2 R=15 gelb",
    )

    assert captured["path"] == "/api/chat"
    assert captured["body"]["format"] == "json"
    gesendet = captured["body"]["messages"][1]["content"]
    assert "yellow, 2x2 studs" in gesendet
    assert "light blue, 2x2 studs" in gesendet
    assert "[6023350] Brick 2x2x2 R=15 gelb" in gesendet
    assert result.ok is True
    assert result.same_article is False
    assert result.reason == "Andere Farbe."


@pytest.mark.anyio
async def test_the_compare_prompt_makes_colour_decisive():
    """Der gemessene Fehlerfall war ein hellblauer Stein, der als gelber
    durchging. Ohne diesen Satz entscheidet das Modell nach der Bauform."""
    from app.services.llm_client import _COMPARE_SYSTEM_PROMPT

    assert "Andere FARBE heisst anderer Artikel." in _COMPARE_SYSTEM_PROMPT
    # Und die Gegenrichtung, sonst faellt jede andere Formulierung durch:
    assert "Andere Wortwahl fuer dasselbe Teil heisst NICHT anderer Artikel." in _COMPARE_SYSTEM_PROMPT


@pytest.mark.anyio
async def test_compare_articles_without_a_label_still_asks():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        content = json.dumps({"same_article": True, "reason": "Gleiche Form und Farbe."})
        return httpx.Response(200, json={"message": {"content": content}})

    result = await _client_with(handler).compare_articles(
        reference_text="brick, yellow", candidate_text="brick, yellow"
    )

    assert "Artikelname laut Auftrag" not in captured["body"]["messages"][1]["content"]
    assert result.ok is True
    assert result.same_article is True


@pytest.mark.anyio
async def test_a_non_boolean_same_article_is_no_finding():
    """`"same_article": "maybe"` ist keine Antwort auf eine Ja/Nein-Frage."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"message": {"content": json.dumps({"same_article": "maybe"})}})

    result = await _client_with(handler).compare_articles(
        reference_text="a", candidate_text="b"
    )

    assert result.ok is False
    assert result.same_article is None


@pytest.mark.anyio
async def test_compare_articles_http_error_is_no_finding():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    result = await _client_with(handler).compare_articles(
        reference_text="a", candidate_text="b"
    )

    assert result.ok is False


# --- Zustandsvergleich -------------------------------------------------------
# Dasselbe Verfahren wie der Artikelvergleich, aus demselben gemessenen Grund.
# Andere Frage: nicht "welches Teil?", sondern "welcher Zustand?".


@pytest.mark.anyio
async def test_compare_condition_sends_soll_and_ist_and_the_label():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        captured["body"] = json.loads(request.content)
        content = json.dumps(
            {"new_damage": True, "reason": "Riss, den das Katalogbild nicht zeigt."}
        )
        return httpx.Response(200, json={"message": {"content": content}})

    result = await _client_with(handler).compare_condition(
        reference_text="smooth and continuous everywhere",
        candidate_text="a torn area across the curved top",
        product_label="Brick 2x2x2 R=15 gelb",
    )

    assert captured["path"] == "/api/chat"
    assert captured["body"]["format"] == "json"
    assert captured["body"]["options"]["temperature"] == 0
    gesendet = captured["body"]["messages"][1]["content"]
    assert "SOLL" in gesendet and "smooth and continuous everywhere" in gesendet
    assert "IST" in gesendet and "a torn area across the curved top" in gesendet
    assert "Brick 2x2x2 R=15 gelb" in gesendet
    assert result.ok is True
    assert result.new_damage is True
    assert result.reason == "Riss, den das Katalogbild nicht zeigt."


@pytest.mark.anyio
async def test_the_condition_prompt_names_both_directions():
    """Der Vergleich muss in beide Richtungen koennen, sonst ist er nur eine
    zweite Meinung: Merkmale entlasten (Noppen), fehlende Teile belasten (ein
    sauber abgebrochenes Eck hinterlaesst keine ausgefranste Stelle)."""
    from app.services.llm_client import _CONDITION_SYSTEM_PROMPT

    assert "Merkmal des Artikels" in _CONDITION_SYSTEM_PROMPT
    assert "Fehlt im IST ein Teil" in _CONDITION_SYSTEM_PROMPT
    # Und die Richtung im Zweifel, damit kein Schaden das Lager verlaesst:
    assert "Im Zweifel true." in _CONDITION_SYSTEM_PROMPT


@pytest.mark.anyio
async def test_a_non_boolean_new_damage_is_no_finding():
    """`ok=False` heisst "kein Befund", nicht "kein Schaden" -- der Aufrufer
    laesst den Befund der absoluten Pruefung dann stehen."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"message": {"content": json.dumps({"new_damage": "vielleicht"})}}
        )

    result = await _client_with(handler).compare_condition(
        reference_text="a", candidate_text="b"
    )

    assert result.ok is False
    assert result.new_damage is None


@pytest.mark.anyio
async def test_compare_condition_http_error_is_no_finding():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    result = await _client_with(handler).compare_condition(
        reference_text="a", candidate_text="b"
    )

    assert result.ok is False


@pytest.mark.anyio
async def test_the_compare_prompt_asks_for_the_shape_before_the_verdict():
    """Gemessen an QA/0315 (2026-08-09): SOLL "square base with a rounded
    arched top", IST "half-cylinder on top of square base" -- derselbe Stein,
    andere Worte, und das Modell antwortete "Andere Bauform".

    Der Prompt fragte direkt nach dem Urteil. `vision_client` haelt fuer die
    Bildaufrufe fest, warum das schiefgeht: wird zuerst nach dem Urteil
    gefragt, antwortet das Modell aus dem Schema statt aus der Sache. Fuer den
    Textvergleich galt derselbe Satz noch nicht. Jetzt muss es die beiden
    Formen erst in eigenen Worten benennen.
    """
    from app.services.llm_client import _COMPARE_SYSTEM_PROMPT

    schluessel = _COMPARE_SYSTEM_PROMPT.index('"formvergleich"')
    urteil = _COMPARE_SYSTEM_PROMPT.index('"same_article"')
    assert schluessel < urteil


@pytest.mark.anyio
async def test_the_compare_prompt_resolves_the_wording_conflict():
    """Vorher standen zwei Regeln nebeneinander -- "andere Bauform heisst
    anderer Artikel" und "andere Wortwahl heisst NICHT anderer Artikel" -- ohne
    zu sagen, welche im Zweifel gilt. Das Modell entschied auf mismatch."""
    from app.services.llm_client import _COMPARE_SYSTEM_PROMPT

    assert "Im Zweifel gilt: dasselbe Teil." in _COMPARE_SYSTEM_PROMPT
    assert "Andere FARBE heisst anderer Artikel." in _COMPARE_SYSTEM_PROMPT


@pytest.mark.anyio
async def test_compare_articles_reports_which_attribute_differed():
    """Ohne dieses Feld laesst sich spaeter nicht auszaehlen, ob Fehlurteile an
    der Farbe, der Bauform oder der Artikelart haengen -- und genau danach
    richtet sich, welche Regel man anfassen muss."""
    def handler(request: httpx.Request) -> httpx.Response:
        content = json.dumps({
            "formvergleich": "beide beschreiben ein gewoelbtes Dach",
            "unterschied": "bauform",
            "same_article": False,
            "reason": "Andere Bauform.",
        })
        return httpx.Response(200, json={"message": {"content": content}})

    result = await _client_with(handler).compare_articles(
        reference_text="a", candidate_text="b"
    )

    assert result.ok is True
    assert result.differs == "bauform"


@pytest.mark.anyio
async def test_an_unknown_attribute_is_not_invented():
    """Ein Wert ausserhalb der Liste ist keine Auskunft. Er darf nicht als
    Auskunft gezaehlt werden -- sonst stehen in der Auswertung Kategorien, die
    niemand definiert hat."""
    def handler(request: httpx.Request) -> httpx.Response:
        content = json.dumps({
            "unterschied": "vibes", "same_article": True, "reason": "passt"
        })
        return httpx.Response(200, json={"message": {"content": content}})

    result = await _client_with(handler).compare_articles(
        reference_text="a", candidate_text="b"
    )

    assert result.ok is True
    assert result.same_article is True
    assert result.differs is None
