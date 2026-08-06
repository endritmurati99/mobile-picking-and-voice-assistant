"""Die v2-signierte Bewertungsroute.

Sie existiert, weil der signierte n8n-Knoten keinen frei gesetzten Header
tragen kann (`PwrSignedHttpRequest` kennt nur `pwrOutboundHmac`), die abgeloeste
Route `/api/internal/llm/quality-disposition` aber genau auf
`X-N8N-Callback-Secret` bestand. Eine Auth-Art fuer die ganze v2-Kette statt
zwei nebeneinander -- die alte Route ist inzwischen geloescht.
"""
import base64
import io
import json

import pytest
from PIL import Image
from fastapi.testclient import TestClient

from app import config, dependencies
from app.main import app
from app.services.llm_client import LlmDispositionResult
from app.services.vision_client import ArticleMatch, DamageCheck

# `signed_env` bringt fixierte Uhr, fixierten Keyring und Fake-Odoo je Instanz.
from tests.test_n8n_v2_routes import signed_env, signed_headers  # noqa: F401

ASSESS_TARGET = "/api/internal/n8n/v2/assessments/quality"

ASSESS = {
    "schema_version": "v2",
    "event_id": "a4ff5ca2-4546-4ea4-8e6c-b75bc003ca32",
    "job_id": "4ddb2442-e58a-47fe-9a6f-1ec1d779ef88",
    "odoo_instance": "o19-a",
    "delivery_generation": 1,
    "processing_lease_token": "lease-" + ("x" * 40),
    "description": "Karton zerdrueckt, Ware nass",
    "priority": "1",
    "photo_count": 2,
    "product_id": 42,
    "location_id": 8,
}


def assess_body(overrides=None):
    payload = dict(ASSESS)
    payload.update(overrides or {})
    return json.dumps(payload, separators=(",", ":")).encode()


class FakeLlm:
    def __init__(self, result):
        self.result = result
        self.calls = []

    async def classify_disposition(self, **kwargs):
        self.calls.append(kwargs)
        return self.result


def install_llm(result):
    fake = FakeLlm(result)
    app.dependency_overrides[dependencies.get_llm_client] = lambda: fake
    return fake


@pytest.fixture
def llm_ok(signed_env):
    fake = install_llm(
        LlmDispositionResult(
            ok=True,
            model="qwen2.5:7b",
            disposition="scrap",
            confidence=0.95,
            summary="Ware unbrauchbar.",
            recommended_action="Artikel sperren.",
        )
    )
    yield fake
    app.dependency_overrides.pop(dependencies.get_llm_client, None)


@pytest.fixture
def llm_down(signed_env):
    fake = install_llm(LlmDispositionResult(ok=False, model="qwen2.5:7b"))
    yield fake
    app.dependency_overrides.pop(dependencies.get_llm_client, None)


def post(body, **header_kwargs):
    headers = signed_headers(
        body,
        ASSESS_TARGET,
        idempotency_key=header_kwargs.pop("idempotency_key", ASSESS["event_id"]),
        **header_kwargs,
    )
    with TestClient(app) as client:
        return client.post(ASSESS_TARGET, content=body, headers=headers)


def test_signed_assessment_returns_the_verdict(llm_ok):
    response = post(assess_body())
    assert response.status_code == 200
    data = response.json()
    assert data["llm_ok"] is True
    assert data["disposition"] == "scrap"
    assert data["confidence"] == 0.95
    assert data["provider"] == "ollama-local"
    assert data["model"] == "qwen2.5:7b"
    assert llm_ok.calls[0]["description"] == ASSESS["description"]
    assert llm_ok.calls[0]["photo_count"] == 2


def test_unsigned_request_is_rejected(llm_ok):
    body = assess_body()
    with TestClient(app) as client:
        response = client.post(
            ASSESS_TARGET,
            content=body,
            headers={
                "Content-Type": "application/json",
                "Idempotency-Key": ASSESS["event_id"],
            },
        )
    assert response.status_code in (401, 403)
    assert llm_ok.calls == []


def test_idempotency_key_must_equal_event_id(llm_ok):
    response = post(assess_body(), idempotency_key="etwas-anderes")
    assert response.status_code == 409
    assert llm_ok.calls == []


def test_signed_generation_must_match_the_body(llm_ok):
    body = assess_body()
    with TestClient(app) as client:
        response = client.post(
            ASSESS_TARGET,
            content=body,
            headers=signed_headers(
                body,
                ASSESS_TARGET,
                generation=2,
                idempotency_key=ASSESS["event_id"],
            ),
        )
    assert response.status_code == 409
    assert llm_ok.calls == []


def test_unknown_field_is_refused(llm_ok):
    response = post(assess_body({"schmuggel": "x"}))
    assert response.status_code == 422
    assert llm_ok.calls == []


def test_llm_failure_reports_not_ok_without_verdict(llm_down):
    response = post(assess_body())
    assert response.status_code == 200
    data = response.json()
    assert data["llm_ok"] is False
    assert data["disposition"] is None
    assert data["confidence"] is None
    assert data["summary"] is None


def test_route_reads_media_but_never_writes(llm_ok, signed_env):
    """Loest `test_route_never_writes_to_odoo` ab. Die Route liest jetzt
    Bilder aus Odoo -- sie entscheidet und aendert weiterhin nichts, ueber
    Wirkung entscheidet ausschliesslich der Callback. Geprueft wird deshalb
    WAS sie ruft, nicht mehr OB. Zwei Tests mit gegensaetzlicher Behauptung
    ueber dieselbe Route waeren schlimmer als keiner."""
    signed_env["o19-a"].response = MEDIA_RESPONSE
    install_vision(
        ArticleMatch(ok=True, same_article=True, reason="passt"),
        DamageCheck(ok=True, damaged=False, anomalies=()),
    )
    try:
        post(assess_body())
    finally:
        app.dependency_overrides.pop(dependencies.get_vision_client, None)

    assert [(model, method) for model, method, _ in signed_env["o19-a"].calls] == [
        ("quality.alert.custom", "api_get_assessment_media")
    ]
    assert signed_env["local"].calls == []
    assert signed_env["o19-b"].calls == []


# --- Bildpruefung -----------------------------------------------------------
# Die Bilder holt die Route SELBST aus Odoo; `signed_env` stellt je Instanz ein
# FakeOdoo mit setzbarem `.response` bereit, und ASSESS nennt "o19-a".


def _tiny_jpeg_b64():
    buffer = io.BytesIO()
    Image.new("RGB", (32, 32), (255, 200, 0)).save(buffer, format="JPEG")
    return base64.b64encode(buffer.getvalue()).decode("ascii")


MEDIA_RESPONSE = {
    "photos": [{"filename": "hund.webp", "data_b64": _tiny_jpeg_b64()}],
    "photo_total": 1,
    "reference_image_b64": _tiny_jpeg_b64(),
    "product_label": "[6023350] Brick 2x2x2 R=15 gelb",
}


class FakeVision:
    def __init__(self, match, damage):
        self._match = match
        self._damage = damage
        self.damage_calls = 0

    async def compare_article(self, reference, candidate):
        return self._match

    async def inspect_damage(self, candidate):
        self.damage_calls += 1
        return self._damage


def install_vision(match, damage):
    fake = FakeVision(match, damage)
    app.dependency_overrides[dependencies.get_vision_client] = lambda: fake
    return fake


def test_a_dog_photo_contradicts_a_sellable_verdict(signed_env):
    """Der Fall, der diesen Umbau ausgeloest hat: QA/0014, Text 'Verpackung
    defekt' -> sellable, Foto ein Hund."""
    signed_env["o19-a"].response = MEDIA_RESPONSE
    install_llm(
        LlmDispositionResult(
            ok=True,
            model="qwen2.5:7b",
            disposition="sellable",
            confidence=0.9,
            summary="Defekte Verpackung, Produkt unbeeintraechtigt.",
            recommended_action="Sichtpruefung.",
        )
    )
    install_vision(
        ArticleMatch(
            ok=True,
            same_article=False,
            reason="Image 2 shows an animal, not a product.",
            candidate_description="a dog on a beach",
        ),
        DamageCheck(ok=True, damaged=False, anomalies=()),
    )
    try:
        response = post(assess_body())
    finally:
        app.dependency_overrides.pop(dependencies.get_llm_client, None)
        app.dependency_overrides.pop(dependencies.get_vision_client, None)

    assert response.status_code == 200
    body = response.json()
    assert body["photo_checked"] is True
    assert body["contradiction"] is True
    assert "nicht den gemeldeten Artikel" in body["photo_analysis"]
    assert "a dog on a beach" in body["photo_analysis"]
    # Das Texturteil bleibt unangetastet -- der Callback entscheidet, was damit
    # geschieht, nicht diese Route.
    assert body["disposition"] == "sellable"


def test_damage_reported_but_unseen_is_noted_not_blocked(llm_ok, signed_env):
    """llm_ok liefert scrap. Das Modell sieht keinen Schaden -- der
    Kommissionierer hatte den Artikel in der Hand, also bleibt sein Urteil."""
    signed_env["o19-a"].response = MEDIA_RESPONSE
    install_vision(
        ArticleMatch(ok=True, same_article=True, reason="passt"),
        DamageCheck(ok=True, damaged=False, anomalies=()),
    )
    try:
        response = post(assess_body())
    finally:
        app.dependency_overrides.pop(dependencies.get_vision_client, None)

    body = response.json()
    assert body["disposition"] == "scrap"
    assert body["contradiction"] is False
    assert "keinen sichtbaren Schaden" in body["photo_analysis"]


def test_vision_failure_leaves_the_text_verdict_standing(llm_ok, signed_env):
    signed_env["o19-a"].response = MEDIA_RESPONSE
    install_vision(ArticleMatch(ok=False), DamageCheck(ok=False))
    try:
        response = post(assess_body())
    finally:
        app.dependency_overrides.pop(dependencies.get_vision_client, None)

    body = response.json()
    assert body["llm_ok"] is True
    assert body["disposition"] == "scrap"
    assert body["photo_checked"] is False
    assert body["contradiction"] is False
    assert "nicht moeglich" in body["photo_analysis"]


def test_odoo_failure_leaves_the_text_verdict_standing(llm_ok, signed_env):
    """Odoo antwortet gar nicht. Ein Ausfall der Zweitmeinung darf die
    Erstmeinung nicht loeschen."""
    signed_env["o19-a"].error = RuntimeError("Odoo weg")
    install_vision(
        ArticleMatch(ok=True, same_article=True, reason="passt"),
        DamageCheck(ok=True, damaged=True, anomalies=("torn",)),
    )
    try:
        response = post(assess_body())
    finally:
        signed_env["o19-a"].error = None
        app.dependency_overrides.pop(dependencies.get_vision_client, None)

    body = response.json()
    assert body["disposition"] == "scrap"
    assert body["photo_checked"] is False
    assert "Bildpruefung nicht moeglich" in body["photo_analysis"]


def test_alert_without_a_photo_is_not_an_error(llm_ok, signed_env):
    signed_env["o19-a"].response = {
        "photos": [],
        "photo_total": 0,
        "reference_image_b64": False,
        "product_label": "",
    }
    install_vision(ArticleMatch(ok=False), DamageCheck(ok=False))
    try:
        response = post(assess_body())
    finally:
        app.dependency_overrides.pop(dependencies.get_vision_client, None)

    body = response.json()
    assert body["disposition"] == "scrap"
    assert body["photo_checked"] is False
    assert "kein Foto" in body["photo_analysis"]


def test_every_photo_is_inspected_and_the_rest_is_declared(llm_ok, signed_env):
    """Bis zu drei Fotos werden geprueft; was darueber hinausgeht, wird
    genannt statt stillschweigend uebergangen."""
    signed_env["o19-a"].response = {
        "photos": [
            {"filename": f"foto_{i}.jpg", "data_b64": _tiny_jpeg_b64()} for i in range(3)
        ],
        "photo_total": 5,
        "reference_image_b64": _tiny_jpeg_b64(),
        "product_label": "Brick",
    }
    fake = install_vision(
        ArticleMatch(ok=True, same_article=True, reason="passt"),
        DamageCheck(ok=True, damaged=False, anomalies=()),
    )
    try:
        response = post(assess_body())
    finally:
        app.dependency_overrides.pop(dependencies.get_vision_client, None)

    assert fake.damage_calls == 3
    assert "2 weitere Foto(s) ungeprueft" in response.json()["photo_analysis"]


def test_spent_budget_stops_further_photos_and_says_so(llm_ok, signed_env):
    """Drei Fotos ergeben vier Bildaufrufe. Auf der CPU dauert einer rund 60 s,
    der n8n-Knoten wartet 240 s -- ohne Gesamtbudget reisst die Zeitgrenze im
    Knoten, und dann geht der Befund ersatzlos verloren. Das erste Foto wird
    immer geprueft, der Rest nur solange Zeit bleibt."""
    signed_env["o19-a"].response = {
        "photos": [
            {"filename": f"foto_{i}.jpg", "data_b64": _tiny_jpeg_b64()} for i in range(3)
        ],
        "photo_total": 3,
        "reference_image_b64": _tiny_jpeg_b64(),
        "product_label": "Brick",
    }
    fake = install_vision(
        ArticleMatch(ok=True, same_article=True, reason="passt"),
        DamageCheck(ok=True, damaged=False, anomalies=()),
    )
    vorher = config.settings.vision_budget_ms
    config.settings.vision_budget_ms = 0
    try:
        response = post(assess_body())
    finally:
        config.settings.vision_budget_ms = vorher
        app.dependency_overrides.pop(dependencies.get_vision_client, None)

    assert fake.damage_calls == 1
    assert "2 weitere Foto(s) ungeprueft" in response.json()["photo_analysis"]


def test_vision_disabled_behaves_like_before_the_rebuild(llm_ok, signed_env):
    """Der Notausgang: vision_enabled=false. Kein Odoo-Aufruf, kein
    Bildbefund, Texturteil wie vorher."""
    app.dependency_overrides[dependencies.get_vision_client] = lambda: None
    try:
        response = post(assess_body())
    finally:
        app.dependency_overrides.pop(dependencies.get_vision_client, None)

    body = response.json()
    assert body["disposition"] == "scrap"
    assert body["photo_checked"] is False
    assert body["photo_analysis"] == "Bildpruefung abgeschaltet."
    assert signed_env["o19-a"].calls == []
