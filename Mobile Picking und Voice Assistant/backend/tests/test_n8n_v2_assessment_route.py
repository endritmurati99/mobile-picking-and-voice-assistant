"""Die v2-signierte Bewertungsroute.

Sie existiert, weil der signierte n8n-Knoten keinen frei gesetzten Header
tragen kann (`PwrSignedHttpRequest` kennt nur `pwrOutboundHmac`), die abgeloeste
Route `/api/internal/llm/quality-disposition` aber genau auf
`X-N8N-Callback-Secret` bestand. Eine Auth-Art fuer die ganze v2-Kette statt
zwei nebeneinander -- die alte Route ist inzwischen geloescht.
"""
import asyncio
import base64
import io
import json

import pytest
from PIL import Image
from fastapi.testclient import TestClient

from app import config, dependencies
from app.main import app
from app.services.llm_client import (
    ArticleComparison,
    ConditionComparison,
    LlmDispositionResult,
)
from app.services.vision_client import ArticleDescription, DamageCheck
from app.services import assessment_media
from app.routers import n8n_v2

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
    """Textmodell: Einstufung UND -- seit dem Umbau -- der Artikelvergleich.

    Der Vergleich liegt beim Textmodell, weil das Bildmodell zwei aehnliche
    Bilder in einem Aufruf gleich beschrieb (siehe `vision_client`).
    """

    def __init__(self, result, article=None, condition=None):
        self.result = result
        self.article = article or ArticleComparison(
            ok=True, same_article=True, reason="passt"
        )
        # Voreinstellung: der Zustandsvergleich bestaetigt, was die absolute
        # Schadenspruefung gesehen hat. Damit aendert er in allen Tests, die
        # nichts ueber ihn aussagen, nichts am Befund.
        self.condition = condition
        self.calls = []
        self.article_calls = []
        self.condition_calls = []

    async def classify_disposition(self, **kwargs):
        self.calls.append(kwargs)
        return self.result

    async def compare_articles(self, **kwargs):
        self.article_calls.append(kwargs)
        return self.article

    async def compare_condition(self, **kwargs):
        self.condition_calls.append(kwargs)
        if self.condition is not None:
            return self.condition
        gesehen = "torn" in kwargs.get("candidate_text", "")
        return ConditionComparison(ok=True, new_damage=gesehen, reason="bestaetigt")


def install_llm(result, article=None, condition=None):
    fake = FakeLlm(result, article, condition)
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
        SIEHT_ARTIKEL,
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


# Zwei Beschreibungen je Bewertung: erst das Katalogbild, dann das Meldefoto.
SIEHT_ARTIKEL = ArticleDescription(
    ok=True, text="toy building brick, yellow, 2x2 studs", is_a_product=True
)
SIEHT_HUND = ArticleDescription(
    ok=True, text="dog, light brown, standing on a beach", is_a_product=False
)
SIEHT_NICHTS = ArticleDescription(ok=False)


class FakeVision:
    def __init__(self, description, damage):
        self._description = description
        self._damage = damage
        self.damage_calls = 0
        self.describe_calls = 0

    async def describe(self, image):
        # Zuerst das MELDEFOTO -- darueber sagt der Test etwas aus --, danach
        # das Katalogbild, das immer erkannt wird.
        self.describe_calls += 1
        if self.describe_calls == 1:
            return self._description
        return SIEHT_ARTIKEL if self._description.ok else self._description

    async def inspect_damage(self, candidate):
        self.damage_calls += 1
        return self._damage


def install_vision(description, damage):
    fake = FakeVision(description, damage)
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
        ),
        ArticleComparison(
            ok=True, same_article=False, reason="B zeigt ein Tier, keinen Artikel."
        ),
    )
    install_vision(
        SIEHT_HUND,
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
    assert "dog, light brown, standing on a beach" in body["photo_analysis"]
    # Das Texturteil bleibt unangetastet -- der Callback entscheidet, was damit
    # geschieht, nicht diese Route.
    assert body["disposition"] == "sellable"


def test_damage_reported_but_unseen_is_noted_not_blocked(llm_ok, signed_env):
    """llm_ok liefert scrap. Das Modell sieht keinen Schaden -- der
    Kommissionierer hatte den Artikel in der Hand, also bleibt sein Urteil."""
    signed_env["o19-a"].response = MEDIA_RESPONSE
    install_vision(
        SIEHT_ARTIKEL,
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
    install_vision(SIEHT_NICHTS, DamageCheck(ok=False))
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
        SIEHT_ARTIKEL,
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
    install_vision(SIEHT_NICHTS, DamageCheck(ok=False))
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
        SIEHT_ARTIKEL,
        DamageCheck(ok=True, damaged=False, anomalies=()),
    )
    try:
        response = post(assess_body())
    finally:
        app.dependency_overrides.pop(dependencies.get_vision_client, None)

    assert fake.damage_calls == 3
    assert "2 weitere Foto(s) ungeprueft" in response.json()["photo_analysis"]


def test_spent_budget_stops_the_damage_checks_and_says_so(llm_ok, signed_env):
    """Bei aufgebrauchtem Budget wird das Meldefoto trotzdem EINMAL beschrieben
    -- sonst stuende in der Meldung nicht, was auf dem Foto zu sehen war. Der
    Vergleich mit dem Katalogbild entfaellt dann, und weil der Artikelabgleich
    damit ausfaellt, traegt die Schadenspruefung den garantierten Aufruf. Was
    liegen bleibt, wird gezaehlt statt stillschweigend uebergangen."""
    signed_env["o19-a"].response = {
        "photos": [
            {"filename": f"foto_{i}.jpg", "data_b64": _tiny_jpeg_b64()} for i in range(3)
        ],
        "photo_total": 3,
        "reference_image_b64": _tiny_jpeg_b64(),
        "product_label": "Brick",
    }
    fake = install_vision(
        SIEHT_ARTIKEL,
        DamageCheck(ok=True, damaged=False, anomalies=()),
    )
    vorher = config.settings.vision_budget_ms
    config.settings.vision_budget_ms = 0
    try:
        response = post(assess_body())
    finally:
        config.settings.vision_budget_ms = vorher
        app.dependency_overrides.pop(dependencies.get_vision_client, None)

    body = response.json()
    # Ein garantierter Schadensaufruf, weil der Artikelabgleich ausfiel.
    assert fake.damage_calls == 1
    assert fake.describe_calls == 1
    assert "Zeitbudget erschoepft" in body["photo_analysis"]
    # Was auf dem Foto war, steht trotzdem da.
    assert "Foto zeigt: toy building brick, yellow" in body["photo_analysis"]
    assert "2 weitere Foto(s) ungeprueft" in body["photo_analysis"]


def test_without_a_catalogue_image_one_damage_check_still_runs(llm_ok, signed_env):
    """Ohne Katalogbild entfaellt der Artikelabgleich. Dann muss die
    Schadenspruefung den einen garantierten Bildaufruf tragen, sonst kaeme bei
    aufgebrauchtem Budget gar kein Befund zustande."""
    signed_env["o19-a"].response = {
        "photos": [
            {"filename": f"foto_{i}.jpg", "data_b64": _tiny_jpeg_b64()} for i in range(2)
        ],
        "photo_total": 2,
        "reference_image_b64": False,
        "product_label": "Brick",
    }
    fake = install_vision(
        SIEHT_NICHTS,
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
    assert "1 weitere Foto(s) ungeprueft" in response.json()["photo_analysis"]


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


def _large_jpeg_b64(edge=1200):
    buffer = io.BytesIO()
    Image.new("RGB", (edge, edge), (255, 200, 0)).save(buffer, format="JPEG")
    return base64.b64encode(buffer.getvalue()).decode("ascii")


class SizeRecordingVision(FakeVision):
    """Merkt sich, wie gross die Bilder ankamen."""

    def __init__(self, match, damage):
        super().__init__(match, damage)
        self.article_edge = None
        self.damage_edge = None

    @staticmethod
    def _edge(body: bytes) -> int:
        with Image.open(io.BytesIO(body)) as image:
            return max(image.size)

    async def describe(self, image):
        # Der ERSTE Aufruf ist das Meldefoto; der zweite ist das Katalogbild
        # und sagt ueber die Aufbereitung des Fotos nichts aus.
        if self.describe_calls == 0:
            self.article_edge = self._edge(image)
        return await super().describe(image)

    async def inspect_damage(self, candidate):
        self.damage_edge = self._edge(candidate)
        return await super().inspect_damage(candidate)


def test_the_damage_check_sees_a_larger_image_than_the_article_check(llm_ok, signed_env):
    """Gemessen am 2026-08-07: bei 512 px meldete `qwen2.5vl:7b` das Rissfoto
    aus QA/0011 als heil, bei 768 px fand es den Riss. Der Artikelabgleich
    bleibt klein, weil er ZWEI Bilder in dasselbe Fenster legt."""
    signed_env["o19-a"].response = dict(
        MEDIA_RESPONSE, photos=[{"filename": "riss.jpg", "data_b64": _large_jpeg_b64()}]
    )
    fake = SizeRecordingVision(
        SIEHT_ARTIKEL,
        DamageCheck(ok=True, damaged=True, anomalies=("aufgerissene Zone",)),
    )
    app.dependency_overrides[dependencies.get_vision_client] = lambda: fake
    try:
        response = post(assess_body())
    finally:
        app.dependency_overrides.pop(dependencies.get_vision_client, None)

    assert response.status_code == 200
    assert fake.article_edge == assessment_media.MAX_EDGE
    assert fake.damage_edge == assessment_media.DAMAGE_MAX_EDGE
    assert fake.damage_edge > fake.article_edge


def test_the_damage_line_states_the_finding_before_the_models_words(llm_ok, signed_env):
    """Am Rissfoto aus QA/0011 lieferte das Modell die Anomalie "feather".
    Als ganze Zeile waere das keine Aussage ueber einen Schaden."""
    signed_env["o19-a"].response = MEDIA_RESPONSE
    install_vision(
        SIEHT_ARTIKEL,
        DamageCheck(ok=True, damaged=True, anomalies=("feather",)),
    )
    try:
        response = post(assess_body())
    finally:
        app.dependency_overrides.pop(dependencies.get_vision_client, None)

    assert "Schadenspruefung: Schaden sichtbar (feather)." in response.json()["photo_analysis"]


def test_damage_without_named_anomalies_still_reads_as_damage(llm_ok, signed_env):
    signed_env["o19-a"].response = MEDIA_RESPONSE
    install_vision(
        SIEHT_ARTIKEL,
        DamageCheck(ok=True, damaged=True, anomalies=()),
    )
    try:
        response = post(assess_body())
    finally:
        app.dependency_overrides.pop(dependencies.get_vision_client, None)

    assert "Schadenspruefung: Schaden sichtbar." in response.json()["photo_analysis"]


def test_a_second_assessment_waits_instead_of_starting(llm_ok, signed_env):
    """Am 2026-08-07 liefen zwei Bewertungen gleichzeitig in Ollama: Aufrufe,
    die sonst 8 s brauchen, dauerten bis 3m20, zwei endeten in HTTP 500, und
    BEIDE Meldungen fielen aus. Ein Rechner ohne GPU traegt ein 7B-Text- und
    ein 7B-Bildmodell nicht gleichzeitig."""
    signed_env["o19-a"].response = MEDIA_RESPONSE
    install_vision(
        SIEHT_ARTIKEL,
        DamageCheck(ok=True, damaged=False, anomalies=()),
    )
    n8n_v2._ASSESSMENT_GATE._value = 0        # die Sperre haelt gerade jemand
    vorher = config.settings.assessment_wait_ms
    config.settings.assessment_wait_ms = 50   # nicht ewig warten im Test
    try:
        response = post(assess_body())
    finally:
        config.settings.assessment_wait_ms = vorher
        n8n_v2._ASSESSMENT_GATE = asyncio.Semaphore(1)
        app.dependency_overrides.pop(dependencies.get_vision_client, None)

    body = response.json()
    assert response.status_code == 200
    # Kein Urteil, aber ein Grund -- und kein einziger Modellaufruf.
    assert body["llm_ok"] is False
    assert body["disposition"] is None
    assert body["photo_checked"] is False
    assert "nur nacheinander" in body["photo_analysis"]
    assert llm_ok.calls == []


def test_the_gate_is_released_even_when_the_assessment_raises(signed_env):
    """Eine Sperre, die ein Fehlschlag nicht mehr freigibt, legt die ganze
    Kette still -- jede weitere Meldung liefe in die Absage."""
    signed_env["o19-a"].response = MEDIA_RESPONSE

    class Boom:
        async def classify_disposition(self, **kwargs):
            raise RuntimeError("Modell weg")

    app.dependency_overrides[dependencies.get_llm_client] = lambda: Boom()
    try:
        with pytest.raises(RuntimeError):
            post(assess_body())
    finally:
        app.dependency_overrides.pop(dependencies.get_llm_client, None)

    assert n8n_v2._ASSESSMENT_GATE._value == 1


def test_one_unreadable_photo_does_not_erase_the_others(llm_ok, signed_env):
    """Vorher lagen alle Fotos in EINEM try: ein Chatter-PDF liess die
    Bildpruefung fuer die ganze Meldung ausfallen, obwohl ein gueltiges
    Meldefoto danebenlag."""
    signed_env["o19-a"].response = dict(
        MEDIA_RESPONSE,
        photos=[
            {"filename": "foto.jpg", "data_b64": _tiny_jpeg_b64()},
            {"filename": "lieferschein.pdf", "data_b64": base64.b64encode(
                b"%PDF-1.4 kein Bild"
            ).decode("ascii")},
        ],
        photo_total=2,
    )
    fake = install_vision(
        SIEHT_ARTIKEL, DamageCheck(ok=True, damaged=False, anomalies=())
    )
    try:
        response = post(assess_body())
    finally:
        app.dependency_overrides.pop(dependencies.get_vision_client, None)

    body = response.json()
    assert body["photo_checked"] is True
    assert "Artikelabgleich: stimmt mit Katalogbild ueberein." in body["photo_analysis"]
    assert "1 Foto(s) nicht lesbar" in body["photo_analysis"]
    # Das lesbare Foto wurde geprueft, das unlesbare gar nicht erst geschickt.
    assert fake.damage_calls == 1


def test_photos_without_an_answer_are_counted_not_swallowed(llm_ok, signed_env):
    """Drei Fotos, das Bildmodell antwortet auf keines. Vorher stand am Ende
    "keine Auffaelligkeit sichtbar" -- eine Aussage ueber Bilder, die niemand
    angesehen hat."""
    signed_env["o19-a"].response = dict(
        MEDIA_RESPONSE,
        photos=[
            {"filename": f"foto_{i}.jpg", "data_b64": _tiny_jpeg_b64()} for i in range(3)
        ],
        photo_total=3,
    )
    install_vision(SIEHT_ARTIKEL, DamageCheck(ok=False))
    try:
        response = post(assess_body())
    finally:
        app.dependency_overrides.pop(dependencies.get_vision_client, None)

    analyse = response.json()["photo_analysis"]
    assert "keine Auffaelligkeit sichtbar" not in analyse
    assert "Schadenspruefung nicht moeglich" in analyse
    assert "3 weitere Foto(s) ungeprueft" in analyse


def test_a_partial_damage_check_says_how_much_it_covered(llm_ok, signed_env):
    """Foto 1 antwortet, Foto 2 nicht. Der Satz nennt, worueber er redet."""
    signed_env["o19-a"].response = dict(
        MEDIA_RESPONSE,
        photos=[
            {"filename": f"foto_{i}.jpg", "data_b64": _tiny_jpeg_b64()} for i in range(2)
        ],
        photo_total=2,
    )

    class HalbstummeVision(FakeVision):
        async def inspect_damage(self, candidate):
            self.damage_calls += 1
            if self.damage_calls == 1:
                return DamageCheck(ok=True, damaged=False, anomalies=())
            return DamageCheck(ok=False)

    fake = HalbstummeVision(SIEHT_ARTIKEL, DamageCheck(ok=False))
    app.dependency_overrides[dependencies.get_vision_client] = lambda: fake
    try:
        response = post(assess_body())
    finally:
        app.dependency_overrides.pop(dependencies.get_vision_client, None)

    analyse = response.json()["photo_analysis"]
    assert "1 von 2 Foto(s) geprueft, dabei keine Auffaelligkeit sichtbar" in analyse


def test_the_internal_article_number_does_not_reach_the_model(llm_ok, signed_env):
    """Odoo liefert "[6023350] Brick 2x2x2 R=15 gelb". An der Nummer hat ein
    Modell nichts zu pruefen -- sie steht auf keinem Foto."""
    signed_env["o19-a"].response = MEDIA_RESPONSE
    install_vision(SIEHT_ARTIKEL, DamageCheck(ok=True, damaged=False, anomalies=()))
    try:
        post(assess_body())
    finally:
        app.dependency_overrides.pop(dependencies.get_vision_client, None)

    label = llm_ok.article_calls[0]["product_label"]
    assert label == "Brick 2x2x2 R=15 gelb"


# --- Zustandsvergleich Soll/Ist ---------------------------------------------
# Die absolute Schadenspruefung beantwortet "bricht hier etwas die glatte
# Oberflaeche?". Das reicht in zwei Richtungen nicht: eine Noppenreihe kann sie
# als Auffaelligkeit lesen, und ein sauber abgebrochenes Eck laesst sie durch,
# weil eine glatte Bruchflaeche keine ausgefranste Stelle ist. Erst der
# Vergleich gegen das Katalogbild entscheidet beides.


@pytest.fixture(autouse=True)
def _leerer_sollspeicher():
    """Der Soll-Befund wird je Katalogbild gespeichert und lebt im Modul.

    Alle Tests hier schicken DASSELBE Katalogbild; ohne Leeren truege der
    Speicher den Befund des vorigen Tests in den naechsten.
    """
    n8n_v2._SOLL_BEFUNDE.clear()
    yield
    n8n_v2._SOLL_BEFUNDE.clear()


class ZustandsVision:
    """Trennt Meldefoto und Katalogbild nach der REIHENFOLGE der Aufrufe.

    `_check_damage` sieht erst jedes Meldefoto an und erst danach, im
    Zustandsvergleich, das Katalogbild. Bei einem Foto ist der erste Aufruf
    also das Meldefoto und der zweite das Katalogbild.
    """

    def __init__(self, ist, soll, fotos=1):
        self._ist = ist
        self._soll = soll
        self._fotos = fotos
        self.damage_calls = 0
        self.describe_calls = 0

    async def describe(self, image):
        self.describe_calls += 1
        return SIEHT_ARTIKEL

    async def inspect_damage(self, candidate):
        self.damage_calls += 1
        return self._ist if self.damage_calls <= self._fotos else self._soll


def _install_zustand(ist, soll, fotos=1):
    fake = ZustandsVision(ist, soll, fotos)
    app.dependency_overrides[dependencies.get_vision_client] = lambda: fake
    return fake


def test_the_comparison_never_clears_a_damage_the_check_already_found(
    llm_ok, signed_env
):
    """Der Rueckschritt, der diese Asymmetrie ausgeloest hat.

    Gemessen am 2026-08-08 (QA/0223, Rissfoto aus QA/0011, Artikel [6023350]):
    die Schadenspruefung fand die Stelle ("feather"), der Vergleich erklaerte
    sie weg -- "Die Beschreibungen stimmen in Bezug auf glatte Oberflaeche
    ueberein." Beide Zustandsbeschreibungen enthalten "smooth", und daran
    haengt sich das Textmodell auf. Derselbe Fehler wie im Zwei-Bild-Aufruf,
    nur eine Ebene hoeher.
    """
    signed_env["o19-a"].response = MEDIA_RESPONSE
    llm_ok.condition = ConditionComparison(
        ok=True,
        new_damage=False,
        reason="Die Beschreibungen stimmen in Bezug auf glatte Oberflaeche ueberein.",
    )
    fake = _install_zustand(
        ist=DamageCheck(
            ok=True,
            damaged=True,
            anomalies=("feather",),
            description="mostly smooth, with a feather-like area near the corner",
        ),
        soll=DamageCheck(
            ok=True,
            damaged=False,
            anomalies=(),
            description="smooth and continuous everywhere",
        ),
    )
    try:
        response = post(assess_body())
    finally:
        app.dependency_overrides.pop(dependencies.get_vision_client, None)

    analyse = response.json()["photo_analysis"]
    assert "Schadenspruefung: Schaden sichtbar (feather)." in analyse
    assert "findet die Auffaelligkeit nicht wieder" in analyse
    assert "Der Befund der Schadenspruefung bleibt stehen." in analyse
    assert fake.damage_calls == 2  # ein Meldefoto, ein Katalogbild


def test_a_clean_photo_that_matches_the_catalogue_image_says_so(llm_ok, signed_env):
    """Ohne Befund in beiden Stufen bleibt es dabei -- und der Satz sagt, dass
    verglichen wurde. Ein Vergleich, der nur bei Widerspruch etwas schreibt,
    laesst offen, ob er ueberhaupt gelaufen ist."""
    signed_env["o19-a"].response = MEDIA_RESPONSE
    llm_ok.condition = ConditionComparison(
        ok=True, new_damage=False, reason="Beide zeigen eine durchgehende Oberflaeche."
    )
    _install_zustand(
        ist=DamageCheck(
            ok=True, damaged=False, anomalies=(), description="smooth everywhere"
        ),
        soll=DamageCheck(
            ok=True, damaged=False, anomalies=(), description="smooth everywhere"
        ),
    )
    try:
        response = post(assess_body())
    finally:
        app.dependency_overrides.pop(dependencies.get_vision_client, None)

    analyse = response.json()["photo_analysis"]
    assert "Schadenspruefung: keine Auffaelligkeit sichtbar." in analyse
    assert "keine Abweichung vom Neuzustand" in analyse


def test_a_cleanly_broken_off_corner_is_only_caught_against_the_catalogue_image(
    llm_ok, signed_env
):
    """Die Luecke in der anderen Richtung: eine glatte Bruchflaeche ist keine
    ausgefranste Stelle, `DAMAGE_PROMPT` laesst sie durch. Dass ein Eck FEHLT,
    faellt erst gegen den Neuzustand auf."""
    signed_env["o19-a"].response = MEDIA_RESPONSE
    llm_ok.condition = ConditionComparison(
        ok=True, new_damage=True, reason="Dem Stein fehlt ein Eck, das SOLL hat."
    )
    _install_zustand(
        ist=DamageCheck(
            ok=True,
            damaged=False,
            anomalies=(),
            description="smooth and continuous everywhere, three corners visible",
        ),
        soll=DamageCheck(
            ok=True,
            damaged=False,
            anomalies=(),
            description="smooth and continuous everywhere, four corners visible",
        ),
    )
    try:
        response = post(assess_body())
    finally:
        app.dependency_overrides.pop(dependencies.get_vision_client, None)

    body = response.json()
    assert "Abweichung vom Neuzustand, die der Schadenspruefung entgangen ist" in body["photo_analysis"]
    assert "fehlt ein Eck" in body["photo_analysis"]


def test_the_condition_comparison_confirms_a_real_crack(llm_ok, signed_env):
    """Bestaetigt der Vergleich, bleibt der Befund stehen und der Satz sagt es.
    Ein Vergleich, der nur bei Widerspruch etwas schreibt, laesst offen, ob er
    ueberhaupt gelaufen ist."""
    signed_env["o19-a"].response = MEDIA_RESPONSE
    llm_ok.condition = ConditionComparison(
        ok=True, new_damage=True, reason="Riss, den das Katalogbild nicht zeigt."
    )
    _install_zustand(
        ist=DamageCheck(
            ok=True,
            damaged=True,
            anomalies=("torn area",),
            description="a torn area across the curved top",
        ),
        soll=DamageCheck(
            ok=True,
            damaged=False,
            anomalies=(),
            description="smooth and continuous everywhere",
        ),
    )
    try:
        response = post(assess_body())
    finally:
        app.dependency_overrides.pop(dependencies.get_vision_client, None)

    analyse = response.json()["photo_analysis"]
    assert "Schadenspruefung: Schaden sichtbar (torn area)." in analyse
    assert "bestaetigt den Befund" in analyse


def test_a_silent_text_model_does_not_clear_the_damage_finding(llm_ok, signed_env):
    """Ein ausgefallener Vergleich ist kein Freispruch. Der Befund der
    absoluten Pruefung bleibt stehen, und im Klartext steht, warum nicht
    verglichen wurde."""
    signed_env["o19-a"].response = MEDIA_RESPONSE
    llm_ok.condition = ConditionComparison(ok=False)
    _install_zustand(
        ist=DamageCheck(
            ok=True,
            damaged=True,
            anomalies=("torn area",),
            description="a torn area across the curved top",
        ),
        soll=DamageCheck(
            ok=True, damaged=False, anomalies=(), description="smooth everywhere"
        ),
    )
    try:
        response = post(assess_body())
    finally:
        app.dependency_overrides.pop(dependencies.get_vision_client, None)

    analyse = response.json()["photo_analysis"]
    assert "Schadenspruefung: Schaden sichtbar (torn area)." in analyse
    assert "Zustandsvergleich nicht moeglich: Textmodell antwortet nicht." in analyse


def test_an_unreadable_catalogue_image_is_said_not_swallowed(llm_ok, signed_env):
    """Antwortet das Bildmodell auf das KATALOGBILD nicht, gibt es keinen
    Soll-Zustand. Auch das steht im Klartext statt zu verschwinden."""
    signed_env["o19-a"].response = MEDIA_RESPONSE
    _install_zustand(
        ist=DamageCheck(
            ok=True,
            damaged=True,
            anomalies=("torn area",),
            description="a torn area across the curved top",
        ),
        soll=DamageCheck(ok=False),
    )
    try:
        response = post(assess_body())
    finally:
        app.dependency_overrides.pop(dependencies.get_vision_client, None)

    analyse = response.json()["photo_analysis"]
    assert "Schadenspruefung: Schaden sichtbar (torn area)." in analyse
    assert "Zustandsvergleich nicht moeglich: Katalogbild nicht auswertbar." in analyse
    assert llm_ok.condition_calls == []


def test_without_a_catalogue_image_nothing_is_compared_and_nothing_is_claimed(
    llm_ok, signed_env
):
    """Ohne Katalogbild gibt es keinen Soll-Zustand -- dann laeuft die Kette
    genau wie vorher, ohne zusaetzlichen Bildaufruf und ohne einen Satz ueber
    einen Vergleich, den niemand gemacht hat."""
    signed_env["o19-a"].response = dict(MEDIA_RESPONSE, reference_image_b64=False)
    fake = _install_zustand(
        ist=DamageCheck(
            ok=True,
            damaged=True,
            anomalies=("torn area",),
            description="a torn area across the curved top",
        ),
        soll=DamageCheck(ok=True, damaged=False, anomalies=(), description="smooth"),
    )
    try:
        response = post(assess_body())
    finally:
        app.dependency_overrides.pop(dependencies.get_vision_client, None)

    analyse = response.json()["photo_analysis"]
    assert "Zustandsvergleich" not in analyse
    assert fake.damage_calls == 1
    assert llm_ok.condition_calls == []


def test_the_catalogue_finding_is_asked_once_per_article(llm_ok, signed_env):
    """Das Katalogbild eines Artikels ist konstant, sein Zustandsbefund also
    auch. Ohne diesen Speicher kostete der Vergleich JEDE Meldung einen
    zusaetzlichen Bildaufruf -- auf CPU 20 bis 100 Sekunden gegen einen Knoten,
    der bei 270 Sekunden abschneidet."""
    signed_env["o19-a"].response = MEDIA_RESPONSE
    fake = _install_zustand(
        ist=DamageCheck(
            ok=True, damaged=True, anomalies=("torn",), description="a torn area"
        ),
        soll=DamageCheck(ok=True, damaged=False, anomalies=(), description="smooth"),
    )
    try:
        erste = post(assess_body())
        # Zweite Meldung zum SELBEN Artikel, eigenes Ereignis.
        zweites_ereignis = "b4ff5ca2-4546-4ea4-8e6c-b75bc003ca33"
        zweite = post(
            assess_body({"event_id": zweites_ereignis}),
            idempotency_key=zweites_ereignis,
        )
    finally:
        app.dependency_overrides.pop(dependencies.get_vision_client, None)

    assert erste.status_code == 200
    assert zweite.status_code == 200
    # Zwei Meldefotos, aber nur EIN Katalogbild-Aufruf.
    assert fake.damage_calls == 3
    assert len(llm_ok.condition_calls) == 2


def test_a_failed_catalogue_call_is_not_remembered_as_intact(llm_ok, signed_env):
    """Ein gescheiterter Aufruf ist keine Aussage ueber das Bild, sondern ueber
    das Modell. Wuerde er im Speicher landen, waere jede weitere Meldung zu
    diesem Artikel dauerhaft ohne Zustandsvergleich."""
    signed_env["o19-a"].response = MEDIA_RESPONSE
    _install_zustand(ist=DamageCheck(ok=True, damaged=True, anomalies=("torn",),
                                     description="a torn area"),
                     soll=DamageCheck(ok=False))
    try:
        post(assess_body())
    finally:
        app.dependency_overrides.pop(dependencies.get_vision_client, None)

    assert n8n_v2._SOLL_BEFUNDE == {}
