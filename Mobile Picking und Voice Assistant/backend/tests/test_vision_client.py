"""Der Bild-Client.

Geprueft wird nicht, ob das Modell richtig liegt -- das entscheidet die
Abnahme mit echten Fotos --, sondern drei Dinge, die im Code festliegen
muessen:

* dass genau die zwei gemessenen Prompts abgehen. Ohne den Satz ueber
  "ragged, torn or gouged" erkannte das Modell null von vier Pruefbildern,
  mit ihm drei von vier ohne Fehlalarm. Der Wortlaut ist Spezifikation.
* dass je Aufruf genau EIN Bild abgeht. Zwei Bilder in einem Aufruf waren
  der gemessene Fehler: das Modell beschrieb aehnliche Bilder gleich und
  haette einen verwechselten Artikel durchgewinkt.
* dass jeder Fehler in einem LEEREN Befund endet. Ein halber Bildbefund waere
  die Einladung, doch etwas daraus zu schliessen.
"""
import base64
import json

import httpx
import pytest

from app.services.vision_client import DAMAGE_PROMPT, DESCRIBE_PROMPT, VisionClient

REFERENCE = b"\xff\xd8referenzbild"
CANDIDATE = b"\xff\xd8meldefoto"


def _client(handler):
    return VisionClient(
        endpoint="http://ollama:11434",
        model="qwen2.5vl:7b",
        timeout_ms=5000,
        transport=httpx.MockTransport(handler),
    )


def _responder(payload, captured):
    def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={"response": json.dumps(payload)})

    return handler


@pytest.mark.anyio
async def test_describe_sends_exactly_one_image():
    """Der Kern des Umbaus: EIN Bild je Aufruf. Mit beiden Bildern in einem
    Aufruf beschrieb das Modell einen hellblauen Stein als "yellow plastic
    corner guard", weil daneben ein gelber lag."""
    captured = {}
    handler = _responder(
        {
            "object_type": "dog",
            "colour": "light brown",
            "shape": "medium sized animal",
            "markings": "none",
            "is_a_product": False,
        },
        captured,
    )

    result = await _client(handler).describe(CANDIDATE)

    assert captured["path"] == "/api/generate"
    assert captured["body"]["images"] == [base64.b64encode(CANDIDATE).decode("ascii")]
    assert captured["body"]["prompt"] == DESCRIBE_PROMPT
    assert captured["body"]["format"] == "json"
    assert captured["body"]["options"]["temperature"] == 0
    assert result.ok is True
    assert result.is_a_product is False
    # Farbe und Form stehen in der Zeile, "none" bei den Markierungen nicht.
    assert result.text == "dog, light brown, medium sized animal"


@pytest.mark.anyio
async def test_describe_keeps_markings_when_there_are_any():
    captured = {}
    handler = _responder(
        {
            "object_type": "toy building brick",
            "colour": "light blue",
            "shape": "2x2 studs",
            "markings": "printed face of a person",
            "is_a_product": True,
        },
        captured,
    )

    result = await _client(handler).describe(CANDIDATE)

    assert "printed face of a person" in result.text


@pytest.mark.anyio
async def test_an_answer_without_any_content_is_no_finding():
    """Eine leere Beschreibung liesse sich im Textvergleich mit allem als
    "derselbe Artikel" lesen."""
    captured = {}
    handler = _responder({"object_type": "", "colour": " ", "markings": "none"}, captured)

    result = await _client(handler).describe(CANDIDATE)

    assert result.ok is False
    assert result.text is None


@pytest.mark.anyio
async def test_the_describe_prompt_forbids_comparing():
    """Der Prompt darf nicht zum Vergleichen einladen -- genau daran ist der
    alte Weg gescheitert."""
    assert "describe only what you see" in DESCRIBE_PROMPT
    assert "do not compare" in DESCRIBE_PROMPT.lower()
    assert DESCRIBE_PROMPT.index("object_type") < DESCRIBE_PROMPT.index("is_a_product")


@pytest.mark.anyio
async def test_inspect_damage_sends_one_image_and_the_decisive_rule():
    captured = {}
    handler = _responder(
        {
            "surface_description": "eine aufgerissene Zone an der Seitenflaeche",
            "anomalies": ["torn", " "],
            "damaged": True,
            "confidence": 0.95,
        },
        captured,
    )

    result = await _client(handler).inspect_damage(CANDIDATE)

    assert captured["body"]["images"] == [base64.b64encode(CANDIDATE).decode("ascii")]
    assert captured["body"]["prompt"] == DAMAGE_PROMPT
    assert result.ok is True
    assert result.damaged is True
    # Leere Eintraege fliegen raus, sonst steht spaeter ", ," im Klartext.
    assert result.anomalies == ("torn",)
    assert "aufgerissene" in result.description


@pytest.mark.anyio
async def test_the_damage_prompt_carries_the_decisive_rule():
    """Ohne diesen Satz: null von vier Pruefbildern richtig. Mit ihm: drei von
    vier, ohne Fehlalarm. Er ist Spezifikation, keine Formulierungsfrage."""
    assert "never decoration or a design feature" in DAMAGE_PROMPT
    assert "Printed logos" in DAMAGE_PROMPT
    assert DAMAGE_PROMPT.index("surface_description") < DAMAGE_PROMPT.index('"damaged"')


@pytest.mark.anyio
async def test_intact_item_yields_an_empty_anomaly_list():
    captured = {}
    handler = _responder(
        {
            "surface_description": "smooth and continuous everywhere",
            "anomalies": [],
            "damaged": False,
            "confidence": 0.95,
        },
        captured,
    )

    result = await _client(handler).inspect_damage(CANDIDATE)

    assert result.ok is True
    assert result.damaged is False
    assert result.anomalies == ()


@pytest.mark.anyio
async def test_http_error_yields_an_empty_finding_not_a_guess():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="kaputt")

    result = await _client(handler).inspect_damage(CANDIDATE)

    assert result.ok is False
    assert result.damaged is None
    assert result.anomalies == ()
    assert result.description is None


@pytest.mark.anyio
async def test_unparsable_answer_yields_an_empty_finding():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"response": "kein JSON"})

    result = await _client(handler).describe(CANDIDATE)

    assert result.ok is False
    assert result.text is None


@pytest.mark.anyio
async def test_a_missing_verdict_key_is_not_half_a_finding():
    """Das Modell antwortet JSON, laesst aber `damaged` weg. Ein Befund mit
    Beschreibung und ohne Urteil waere schlimmer als keiner."""
    captured = {}
    handler = _responder({"surface_description": "irgendwas", "anomalies": []}, captured)

    result = await _client(handler).inspect_damage(CANDIDATE)

    assert result.ok is False
    assert result.damaged is None


@pytest.mark.anyio
async def test_a_non_boolean_is_a_product_costs_only_that_flag():
    """`is_a_product: "maybe"` macht die Beschreibung nicht wertlos -- der
    Vergleich laeuft ueber den Text, nicht ueber diese Marke."""
    captured = {}
    handler = _responder(
        {"object_type": "brick", "colour": "yellow", "is_a_product": "maybe"}, captured
    )

    result = await _client(handler).describe(CANDIDATE)

    assert result.ok is True
    assert result.is_a_product is None


@pytest.mark.anyio
async def test_timeout_yields_an_empty_finding():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("zu langsam", request=request)

    result = await _client(handler).describe(CANDIDATE)

    assert result.ok is False
    assert result.text is None


def test_the_model_choice_is_pinned_by_measurement():
    """Beide Modellzuordnungen sind gemessen, nicht geraten:

    * qwen2.5vl:7b stufte "Verpackung defekt" als scrap ein, wo qwen2.5:7b
      korrekt sellable sagt -- es taugt fuers Bild, nicht fuer den Text.
    * qwen2.5vl:3b antwortete auf alle vier Pruefbilder "smooth and continuous
      everywhere", auch auf den offensichtlichen Bruch.

    Wer den Standard aendert, soll an diesem Test vorbei muessen.
    """
    from app.config import Settings

    settings = Settings(_env_file=None)
    assert settings.vision_model == "qwen2.5vl:7b"
    assert settings.llm_model == "qwen2.5:7b"
    assert settings.vision_model != settings.llm_model
