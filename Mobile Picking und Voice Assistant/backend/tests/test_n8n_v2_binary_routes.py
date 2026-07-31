"""Tests fuer die signierten Medien-/Artefakt-Routen (Task 11).

Drei Leitmotive, alle aus Task 10 uebernommen und hier fortgesetzt:

1. JEDE Ablehnung passiert VOR jedem Odoo-Aufruf. Fast jeder Negativtest
   behauptet zusaetzlich `fake_odoo.calls == []`.
2. Paritaet: die Transport-Abwehr (Signatur, Query-Verbot, Skew, Key-Id) wird
   fuer BEIDE Routen geprueft, damit eine Verteidigung nicht in einer Route
   sitzt und in der anderen fehlt.
3. Job- und Generationsbindung: die Route reicht Job-Id, Quell-Event und die
   SIGNIERTE Generation an Odoo weiter; eine veraltete Generation darf weder
   lesen noch anhaengen. Der Beweis dafuer liegt in den Argumenten, mit denen
   Odoo aufgerufen wird -- nicht in einem Mock-Rueckgabewert.

Ausserdem: keine Route darf Base64 nach draussen geben. Die Medien-Route
antwortet mit ROHEN Bytes, die Artefakt-Route nimmt ROHE Bytes an; Base64
existiert ausschliesslich auf dem internen JSON-RPC-Hop zu Odoo.
"""
import base64
import hashlib
from datetime import datetime, timezone
from io import BytesIO

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from pypdf import PdfWriter

from app import dependencies
from app.config import OdooProfile
from app.dependencies import (
    get_n8n_to_backend_keyring,
    get_signature_now,
)
from app.main import app
from app.models.webhook_security import HmacKey, HmacKeyring
from app.services.hmac_signing import sign_request

JOB_ID = "4ddb2442-e58a-47fe-9a6f-1ec1d779ef88"
OTHER_JOB_ID = "00000000-0000-4000-8000-000000000099"
EVENT_ID = "a4ff5ca2-4546-4ea4-8e6c-b75bc003ca32"
MEDIA_REF = "media-1"
SIGNING_KEY = HmacKey("n2b-test", b"2" * 32)
FIXED_TS = 1760000000
NONCE = "123e4567-e89b-42d3-a456-426614174050"
# Fix-round-1 (#5b): the processing lease token travels as a PATH segment,
# not a JSON body field -- see the module docstring addition in
# `app/routers/n8n_v2.py`. Shaped like a real `secrets.token_urlsafe(32)`
# output (this addon's Odoo side issues those).
LEASE_TOKEN = "AbCdEfGhIjKlMnOpQrStUvWxYz0123456789_-ABCD"
OTHER_LEASE_TOKEN = "ZyXwVuTsRqPoNmLkJiHgFeDcBa9876543210_-WXYZ"

def media_path(
    media_ref: str = MEDIA_REF,
    job_id: str = JOB_ID,
    lease_token: str = LEASE_TOKEN,
    instance: str = "o19",
) -> str:
    return (
        f"/api/internal/instances/{instance}/jobs/{job_id}"
        f"/leases/{lease_token}/media/{media_ref}"
    )


MEDIA_PATH = media_path()


def artifact_path(
    kind: str = "pdf",
    job_id: str = JOB_ID,
    event_id: str = EVENT_ID,
    lease_token: str = LEASE_TOKEN,
) -> str:
    return (
        f"/api/internal/instances/o19/jobs/{job_id}"
        f"/leases/{lease_token}/events/{event_id}/artifacts/{kind}"
    )


ARTIFACT_PATH = artifact_path()


# --------------------------------------------------------------------------
# Builders
# --------------------------------------------------------------------------


def png_bytes(size=(32, 32)) -> bytes:
    stream = BytesIO()
    Image.new("RGB", size, "white").save(stream, format="PNG")
    return stream.getvalue()


def animated_webp_bytes() -> bytes:
    frames = [Image.new("RGB", (16, 16), color) for color in ("red", "blue")]
    stream = BytesIO()
    frames[0].save(
        stream, format="WEBP", save_all=True, append_images=frames[1:], duration=100
    )
    return stream.getvalue()


def pdf_bytes(pages: int = 1, mutate=None) -> bytes:
    stream = BytesIO()
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=100, height=100)
    if mutate is not None:
        mutate(writer)
    writer.write(stream)
    return stream.getvalue()


ZPL_LABEL = b"^XA^FO20,20^FDParcel 42^FS^XZ"


# --------------------------------------------------------------------------
# Fixtures
# --------------------------------------------------------------------------


class FakeOdoo:
    """Minimaler Odoo-Doppelgaenger. `calls` ist die Beweisliste: bleibt sie
    leer, hat die Route vor jedem Seiteneffekt abgelehnt."""

    def __init__(self, name="o19"):
        self.name = name
        self.calls = []
        self.media = None
        self.artifact = {"artifact_ref": "artifact-1", "replayed": False}
        self.error = None

    async def execute_kw(self, model, method, args, kwargs=None):
        self.calls.append((model, method, args))
        if self.error is not None:
            raise self.error
        if method == "api_reserve_request_nonce":
            return {"reserved": True, "expires_at": "2026-07-26 12:15:00"}
        if method == "api_get_job_media":
            if self.media is None:
                raise AssertionError("media not configured")
            return self.media
        if method == "api_store_job_artifact":
            return self.artifact
        raise AssertionError((model, method, args))


def media_payload(body: bytes, mimetype: str = "image/png", sha256: str | None = None):
    return {
        "content_base64": base64.b64encode(body).decode(),
        "mimetype": mimetype,
        "sha256": sha256 if sha256 is not None else hashlib.sha256(body).hexdigest(),
        "original_filename": "picker upload.png",
    }


@pytest.fixture
def fake_odoo(monkeypatch):
    fake = FakeOdoo()
    registry = {
        name: OdooProfile(name, name, "http://odoo:8069", name, "admin", "k", "")
        for name in ("local", "o19")
    }
    monkeypatch.setattr(dependencies, "get_instance_registry", lambda: registry)
    monkeypatch.setattr(
        dependencies,
        "_get_cached_client",
        lambda name: fake if name == "o19" else (_ for _ in ()).throw(KeyError(name)),
    )
    return fake


@pytest.fixture
def client():
    app.dependency_overrides[get_signature_now] = lambda: datetime.fromtimestamp(
        FIXED_TS, tz=timezone.utc
    )
    app.dependency_overrides[get_n8n_to_backend_keyring] = lambda: HmacKeyring(
        active=SIGNING_KEY
    )
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def signed(
    path: str,
    body: bytes = b"",
    *,
    method: str = "POST",
    generation: int = 1,
    timestamp: int = FIXED_TS,
    nonce: str = NONCE,
    key: HmacKey = SIGNING_KEY,
    content_type: str | None = None,
    idempotency_key: str | None = "artifact-request-1",
    signed_target: str | None = None,
) -> dict[str, str]:
    header_signature = sign_request(
        method=method,
        target=signed_target if signed_target is not None else path,
        delivery_generation=generation,
        timestamp=timestamp,
        nonce=nonce,
        raw_body=body,
        key=key,
    )
    headers = dict(header_signature.as_http_headers())
    if content_type is not None:
        headers["Content-Type"] = content_type
    if idempotency_key is not None:
        headers["Idempotency-Key"] = idempotency_key
    return headers


@pytest.fixture
def signed_request_headers():
    """Signaturbau fuer die Artefakt-Route (POST, application/pdf)."""

    def build(path: str, body: bytes, *, generation: int):
        return signed(
            path,
            body,
            method="POST",
            generation=generation,
            content_type="application/pdf",
        )

    return build


@pytest.fixture
def minimal_pdf():
    return pdf_bytes()


def get_media(client, *, path: str = MEDIA_PATH, **kwargs):
    kwargs.setdefault("idempotency_key", None)
    return client.get(path, headers=signed(path, b"", method="GET", **kwargs))


def post_artifact(client, body: bytes, *, path: str = ARTIFACT_PATH, **kwargs):
    kwargs.setdefault("content_type", "application/pdf")
    return client.post(path, content=body, headers=signed(path, body, **kwargs))


# --------------------------------------------------------------------------
# Transport-Abwehr, fuer BEIDE Routen parametrisiert
# --------------------------------------------------------------------------


def test_media_bad_signature_never_reads_odoo(client, fake_odoo):
    response = client.get(
        MEDIA_PATH,
        headers={"X-PWR-Signature": "v1=" + ("0" * 64)},
    )
    assert response.status_code == 401
    assert fake_odoo.calls == []


def test_artifact_bad_signature_never_writes_odoo(client, fake_odoo, minimal_pdf):
    response = client.post(
        ARTIFACT_PATH,
        content=minimal_pdf,
        headers={"X-PWR-Signature": "v1=" + ("0" * 64)},
    )
    assert response.status_code == 401
    assert fake_odoo.calls == []


def test_media_wrong_key_and_tampered_body_are_rejected(client, fake_odoo):
    fake_odoo.media = media_payload(png_bytes())
    other = HmacKey("n2b-attacker", b"9" * 32)
    assert get_media(client, key=other).status_code == 401
    assert fake_odoo.calls == []


def test_artifact_signature_over_a_different_body_is_rejected(
    client, fake_odoo, minimal_pdf
):
    headers = signed(ARTIFACT_PATH, b"other bytes", content_type="application/pdf")
    response = client.post(ARTIFACT_PATH, content=minimal_pdf, headers=headers)
    assert response.status_code == 401
    assert fake_odoo.calls == []


@pytest.mark.parametrize("method", ["GET", "POST"])
def test_query_string_is_forbidden_on_both_routes(client, fake_odoo, method, minimal_pdf):
    fake_odoo.media = media_payload(png_bytes())
    if method == "GET":
        path = MEDIA_PATH + "?download=1"
        response = client.get(path, headers=signed(path, b"", method="GET", idempotency_key=None))
    else:
        path = ARTIFACT_PATH + "?force=1"
        response = client.post(
            path, content=minimal_pdf, headers=signed(path, minimal_pdf, content_type="application/pdf")
        )
    assert response.status_code == 400
    assert fake_odoo.calls == []


@pytest.mark.parametrize("method", ["GET", "POST"])
def test_stale_timestamp_is_rejected_on_both_routes(client, fake_odoo, method, minimal_pdf):
    fake_odoo.media = media_payload(png_bytes())
    if method == "GET":
        response = get_media(client, timestamp=FIXED_TS - 4000)
    else:
        response = post_artifact(client, minimal_pdf, timestamp=FIXED_TS - 4000)
    assert response.status_code == 409
    assert fake_odoo.calls == []


@pytest.mark.parametrize("method", ["GET", "POST"])
def test_signed_target_must_equal_the_requested_path(
    client, fake_odoo, method, minimal_pdf
):
    """Eine Signatur ueber einen anderen Pfad darf diesen Pfad nicht bedienen --
    sonst koennte ein Medien-Token ein Artefakt schreiben."""
    fake_odoo.media = media_payload(png_bytes())
    if method == "GET":
        response = client.get(
            MEDIA_PATH,
            headers=signed(
                MEDIA_PATH,
                b"",
                method="GET",
                idempotency_key=None,
                signed_target=media_path(job_id=OTHER_JOB_ID),
            ),
        )
    else:
        response = client.post(
            ARTIFACT_PATH,
            content=minimal_pdf,
            headers=signed(
                ARTIFACT_PATH,
                minimal_pdf,
                content_type="application/pdf",
                signed_target=artifact_path(job_id=OTHER_JOB_ID),
            ),
        )
    assert response.status_code == 401
    assert fake_odoo.calls == []


def test_media_route_rejects_a_post_signature(client, fake_odoo):
    """Die Methode ist Teil der kanonischen Signatureingabe."""
    fake_odoo.media = media_payload(png_bytes())
    response = client.get(
        MEDIA_PATH,
        headers=signed(MEDIA_PATH, b"", method="POST", idempotency_key=None),
    )
    assert response.status_code == 401
    assert fake_odoo.calls == []


# --------------------------------------------------------------------------
# Instanz-, Job- und Generationsbindung
# --------------------------------------------------------------------------


def test_unknown_instance_is_rejected_before_odoo(client, fake_odoo):
    path = MEDIA_PATH.replace("/instances/o19/", "/instances/o19-ghost/")
    response = client.get(path, headers=signed(path, b"", method="GET", idempotency_key=None))
    assert response.status_code == 403
    assert fake_odoo.calls == []


def test_media_passes_job_media_ref_and_signed_generation_to_odoo(client, fake_odoo):
    body = png_bytes()
    fake_odoo.media = media_payload(body)
    response = get_media(client, generation=7)
    assert response.status_code == 200
    reserve, read = fake_odoo.calls
    assert reserve[1] == "api_reserve_request_nonce"
    # Die Nonce-Reservierung ist job-, generations- UND (Fix-Runde 1)
    # lease-token-gebunden.
    assert reserve[2][0] == "n8n_to_backend"
    assert reserve[2][1] == SIGNING_KEY.key_id
    assert reserve[2][2] == NONCE
    assert JOB_ID in reserve[2]
    assert 7 in reserve[2]
    assert LEASE_TOKEN in reserve[2]
    assert read[1] == "api_get_job_media"
    assert read[2] == [JOB_ID, MEDIA_REF, 7, LEASE_TOKEN]


def test_artifact_pdf_is_raw_and_job_bound(
    signed_request_headers, client, fake_odoo, minimal_pdf
):
    path = (
        "/api/internal/instances/o19/jobs/"
        f"4ddb2442-e58a-47fe-9a6f-1ec1d779ef88/leases/{LEASE_TOKEN}/events/"
        "a4ff5ca2-4546-4ea4-8e6c-b75bc003ca32/artifacts/pdf"
    )
    response = client.post(
        path,
        content=minimal_pdf,
        headers=signed_request_headers(path, minimal_pdf, generation=1),
    )
    assert response.status_code == 201
    call = fake_odoo.calls[-1]
    assert call[1] == "api_store_job_artifact"
    assert call[2][0] == "4ddb2442-e58a-47fe-9a6f-1ec1d779ef88"
    assert call[2][2] == "pdf"


def test_artifact_passes_source_event_and_signed_generation(
    client, fake_odoo, minimal_pdf
):
    response = post_artifact(client, minimal_pdf, generation=3)
    assert response.status_code == 201
    reserve, store = fake_odoo.calls
    assert reserve[1] == "api_reserve_request_nonce"
    assert JOB_ID in reserve[2] and 3 in reserve[2] and LEASE_TOKEN in reserve[2]
    assert store[2][0] == JOB_ID
    assert store[2][1] == EVENT_ID
    assert store[2][2] == "pdf"
    assert store[2][3] == 3
    # Base64 nur auf dem internen Hop; der SHA-256 kommt aus dem Validator.
    assert base64.b64decode(store[2][4], validate=True) == minimal_pdf
    assert store[2][5] == hashlib.sha256(minimal_pdf).hexdigest()
    assert store[2][6] == "application/pdf"
    assert store[2][7] == f"{JOB_ID}-pdf.pdf"
    assert store[2][8] == LEASE_TOKEN


def test_stale_generation_conflict_from_odoo_becomes_409(client, fake_odoo, minimal_pdf):
    """Odoo ist die Autoritaet fuer die aktuelle Generation. Ein Konflikt darf
    nie als 200/201 durchgehen und nie die Odoo-Meldung spiegeln."""
    from app.services.odoo_client import OdooAPIError

    fake_odoo.error = OdooAPIError("Stale delivery generation.")
    response = post_artifact(client, minimal_pdf, generation=1)
    assert response.status_code == 409
    assert "Stale" not in response.text


def test_stale_generation_conflict_blocks_media_read(client, fake_odoo):
    from app.services.odoo_client import OdooAPIError

    fake_odoo.media = media_payload(png_bytes())
    fake_odoo.error = OdooAPIError("Stale delivery generation.")
    response = get_media(client)
    assert response.status_code == 409
    assert "Stale" not in response.text


def test_replayed_nonce_conflict_never_reaches_the_resource(client, fake_odoo):
    """Die Nonce-Reservierung ist der erste Odoo-Aufruf. Scheitert sie, darf
    kein Lese-/Schreibzugriff auf die Ressource folgen."""
    from app.services.odoo_client import OdooAPIError

    fake_odoo.error = OdooAPIError("Webhook nonce replay.")
    response = get_media(client)
    assert response.status_code == 409
    assert [call[1] for call in fake_odoo.calls] == ["api_reserve_request_nonce"]


@pytest.mark.parametrize(
    "job_id",
    [
        "not-a-uuid",
        "4ddb2442e58a47fe9a6f1ec1d779ef88",  # ohne Bindestriche
        "4ddb2442-e58a-47fe-9a6f-1ec1d779ef8",  # zu kurz
        "4DDB2442-E58A-47FE-9A6F-1EC1D779EF88",  # Grossschreibung
    ],
)
def test_malformed_job_id_is_rejected_before_odoo(client, fake_odoo, job_id):
    path = media_path(job_id=job_id)
    response = client.get(path, headers=signed(path, b"", method="GET", idempotency_key=None))
    assert response.status_code == 400
    assert fake_odoo.calls == []


@pytest.mark.parametrize(
    "media_ref",
    ["x" * 200, "media~1", "media:1", "-media", ".media", "media%1", "media,1"],
)
def test_malformed_media_ref_is_rejected_before_odoo(client, fake_odoo, media_ref):
    path = media_path(media_ref=media_ref)
    response = client.get(
        path, headers=signed(path, b"", method="GET", idempotency_key=None)
    )
    assert response.status_code == 400
    assert fake_odoo.calls == []


@pytest.mark.parametrize(
    "lease_token",
    ["", "short", "token/with/slash", "x" * 200, "token~with~tilde", "token,with,comma"],
)
def test_malformed_lease_token_is_rejected_before_odoo(client, fake_odoo, lease_token):
    """Fix-round-1, Finding 3: the lease token is a path segment now, so it
    gets the same cheap allowlist treatment as job_id/media_ref -- rejected
    before any Odoo call, not passed through unchecked.

    Status code is allowed to be 400 (allowlist rejection), 404 (a literal
    `/` splits the single `{processing_lease_token}` path segment into more
    segments than the route template has, so it just doesn't match), or 401
    (a value the HTTP client re-encodes differently than what got signed, as
    with the existing malformed-media-ref percent-encoding tests) -- all
    three share the property under test: Odoo is never called.
    """
    path = media_path(lease_token=lease_token)
    response = client.get(path, headers=signed(path, b"", method="GET", idempotency_key=None))
    assert response.status_code in (400, 401, 404)
    assert fake_odoo.calls == []


def test_percent_encoded_media_ref_is_validated_after_decoding(client, fake_odoo):
    """Der signierte Pfad ist der ROHE Pfad, der Handler sieht den dekodierten
    Wert. Beides muss geprueft werden: die Signatur passt hier, und trotzdem
    darf `média` die Allowlist nicht passieren."""
    path = f"/api/internal/instances/o19/jobs/{JOB_ID}/leases/{LEASE_TOKEN}/media/m%C3%A9dia"
    response = client.get(path, headers=signed(path, b"", method="GET", idempotency_key=None))
    assert response.status_code == 400
    assert fake_odoo.calls == []


def test_percent_encoded_traversal_never_escapes_the_media_reference(client, fake_odoo):
    """%2e%2e%2f dekodiert zu "../". Das darf nie zu einem Ressourcenzugriff
    fuehren: entweder passt nach dem Dekodieren kein Routenmuster mehr (404)
    oder die Allowlist weist den Wert ab (400) -- ein 200 waere der Fehler."""
    path = (
        f"/api/internal/instances/o19/jobs/{JOB_ID}/leases/{LEASE_TOKEN}"
        "/media/%2e%2e%2f%2e%2e%2fetc%2fpasswd"
    )
    response = client.get(path, headers=signed(path, b"", method="GET", idempotency_key=None))
    assert response.status_code in (400, 404)
    assert fake_odoo.calls == []


def test_traversal_in_the_media_path_matches_no_route(client, fake_odoo):
    path = (
        f"/api/internal/instances/o19/jobs/{JOB_ID}/leases/{LEASE_TOKEN}"
        "/media/../../../etc/passwd"
    )
    response = client.get(path, headers=signed(path, b"", method="GET", idempotency_key=None))
    assert response.status_code in (401, 404)
    assert fake_odoo.calls == []


def test_malformed_source_event_id_is_rejected_before_odoo(
    client, fake_odoo, minimal_pdf
):
    path = artifact_path(event_id="not-a-uuid")
    response = client.post(
        path,
        content=minimal_pdf,
        headers=signed(path, minimal_pdf, content_type="application/pdf"),
    )
    assert response.status_code == 400
    assert fake_odoo.calls == []


# --------------------------------------------------------------------------
# Medien-Route: Validierung des von Odoo gelieferten Bildes
# --------------------------------------------------------------------------


def test_media_returns_raw_bytes_with_server_generated_filename(client, fake_odoo):
    body = png_bytes()
    fake_odoo.media = media_payload(body)
    response = get_media(client)
    assert response.status_code == 200
    assert response.content == body
    assert response.headers["content-type"] == "image/png"
    disposition = response.headers["content-disposition"]
    assert disposition == f'inline; filename="{JOB_ID}-{MEDIA_REF}.png"'
    # Der von n8n/Picker gelieferte Originalname taucht nirgends in der Antwort
    # auf -- der Dateiname wird serverseitig erzeugt.
    assert "picker upload" not in response.text


def test_media_hash_mismatch_is_rejected(client, fake_odoo):
    fake_odoo.media = media_payload(png_bytes(), sha256="f" * 64)
    response = get_media(client)
    assert response.status_code == 409


def test_media_with_false_declared_mime_is_rejected(client, fake_odoo):
    fake_odoo.media = media_payload(png_bytes(), mimetype="image/jpeg")
    assert get_media(client).status_code == 422


@pytest.mark.parametrize(
    "body,mimetype",
    [
        (b"%PDF-1.7\n%%EOF\n", "image/png"),
        (b'<svg xmlns="http://www.w3.org/2000/svg"/>', "image/png"),
        (animated_webp_bytes(), "image/webp"),
        (png_bytes() + b"%PDF-1.7", "image/png"),
        (png_bytes((5000, 5000)), "image/png"),
    ],
)
def test_media_that_is_not_a_single_frame_allowlisted_image_is_rejected(
    client, fake_odoo, body, mimetype
):
    fake_odoo.media = media_payload(body, mimetype=mimetype)
    assert get_media(client).status_code == 422


def test_media_over_15_mib_is_rejected(client, fake_odoo):
    body = b"\x89PNG\r\n\x1a\n" + b"0" * (15 * 1024 * 1024)
    fake_odoo.media = media_payload(body)
    assert get_media(client).status_code == 422


def test_media_with_unusable_odoo_payload_is_a_conflict(client, fake_odoo):
    for payload in (
        False,
        {},
        {"content_base64": "!!!not base64!!!", "mimetype": "image/png", "sha256": "a" * 64},
        {"content_base64": base64.b64encode(png_bytes()).decode(), "mimetype": "image/png"},
    ):
        fake_odoo.calls.clear()
        fake_odoo.media = payload
        assert get_media(client).status_code == 409


# --------------------------------------------------------------------------
# Artefakt-Route
# --------------------------------------------------------------------------


def test_artifact_zpl_round_trip(client, fake_odoo):
    response = post_artifact(
        client,
        ZPL_LABEL,
        path=artifact_path("zpl"),
        content_type="application/zpl",
    )
    assert response.status_code == 201
    store = fake_odoo.calls[-1]
    assert store[2][2] == "zpl"
    assert store[2][6] == "application/zpl"
    assert store[2][7] == f"{JOB_ID}-zpl.zpl"


def test_artifact_replay_of_identical_bytes_answers_200(client, fake_odoo, minimal_pdf):
    fake_odoo.artifact = {"artifact_ref": "artifact-1", "replayed": True}
    response = post_artifact(client, minimal_pdf)
    assert response.status_code == 200
    assert response.json() == {"artifact_ref": "artifact-1", "replayed": True}


@pytest.mark.parametrize("kind", ["png", "exe", "PDF", "zip"])
def test_artifact_kind_outside_the_allowlist_is_rejected(
    client, fake_odoo, minimal_pdf, kind
):
    path = artifact_path(kind)
    response = client.post(
        path,
        content=minimal_pdf,
        headers=signed(path, minimal_pdf, content_type="application/pdf"),
    )
    assert response.status_code == 400
    assert fake_odoo.calls == []


@pytest.mark.parametrize(
    "idempotency_key",
    [None, "", "k" * 129, "key with space", "key\ttab"],
)
def test_artifact_requires_a_short_ascii_idempotency_key(
    client, fake_odoo, minimal_pdf, idempotency_key
):
    response = post_artifact(client, minimal_pdf, idempotency_key=idempotency_key)
    assert response.status_code == 400
    assert fake_odoo.calls == []


def test_artifact_rejects_a_non_ascii_idempotency_key(client, fake_odoo, minimal_pdf):
    """httpx kann einen Nicht-ASCII-String gar nicht als Header senden, ein
    roher Byte-Header aber schon -- genau so wuerde ein Angreifer es tun."""
    headers = signed(ARTIFACT_PATH, minimal_pdf, content_type="application/pdf")
    headers.pop("Idempotency-Key")
    raw_headers = [(name.encode(), value.encode()) for name, value in headers.items()]
    raw_headers.append((b"Idempotency-Key", "schlüssel".encode("utf-8")))
    response = client.post(ARTIFACT_PATH, content=minimal_pdf, headers=raw_headers)
    assert response.status_code == 400
    assert fake_odoo.calls == []


def test_artifact_content_type_must_match_its_kind(client, fake_odoo, minimal_pdf):
    response = post_artifact(client, minimal_pdf, content_type="application/zpl")
    assert response.status_code == 422
    assert fake_odoo.calls == []


@pytest.mark.parametrize(
    "kind,body,content_type",
    [
        ("pdf", ZPL_LABEL, "application/pdf"),
        ("zpl", pdf_bytes(), "application/zpl"),
        ("pdf", png_bytes(), "application/pdf"),
        ("pdf", pdf_bytes() + b"HOSTILE", "application/pdf"),
        ("zpl", b"^XA^JUS^XZ", "application/zpl"),
        ("zpl", b"^XA^DFE:FORMAT.ZPL^XZ", "application/zpl"),
        ("zpl", "^XA^FDPäckchen^FS^XZ".encode(), "application/zpl"),
    ],
)
def test_artifact_rejected_by_the_cheap_phase_never_touches_odoo(
    client, fake_odoo, kind, body, content_type
):
    """Phase 1: was an Groesse, Magic, deklariertem Typ oder der
    ZPL-Allowlist scheitert, erreicht Odoo gar nicht und verbrennt deshalb
    auch keine Nonce."""
    response = post_artifact(
        client, body, path=artifact_path(kind), content_type=content_type
    )
    assert response.status_code == 422
    assert fake_odoo.calls == []


@pytest.mark.parametrize(
    "body",
    [pdf_bytes(pages=21), pdf_bytes(mutate=lambda writer: writer.encrypt("pw"))],
)
def test_artifact_rejected_by_the_expensive_phase_stores_nothing(
    client, fake_odoo, body
):
    """Phase 3: was nur der volle Durchlauf erkennt, kostet eine Nonce -- aber
    niemals eine Ablage. Genau dafuer sitzt das Replay-Gate davor."""
    response = post_artifact(client, body)
    assert response.status_code == 422
    assert [call[1] for call in fake_odoo.calls] == ["api_reserve_request_nonce"]


def test_replayed_request_is_stopped_before_the_expensive_parse(
    client, fake_odoo, monkeypatch, minimal_pdf
):
    """Der Kern der Dreiteilung: schlaegt die Nonce-Reservierung fehl (also
    bei einer Wiedervorlage), darf der teure Durchlauf gar nicht erst
    laufen -- sonst waere jede mitgeschnittene Anfrage ein beliebig oft
    ausloesbarer Parser-Aufwand."""
    from app.routers import n8n_v2
    from app.services.odoo_client import OdooAPIError

    calls = []
    real = n8n_v2.validate_artifact
    monkeypatch.setattr(
        n8n_v2,
        "validate_artifact",
        lambda *args, **kwargs: (calls.append(1), real(*args, **kwargs))[1],
    )
    fake_odoo.error = OdooAPIError("Webhook nonce replay.")
    response = post_artifact(client, minimal_pdf)
    assert response.status_code == 409
    assert [call[1] for call in fake_odoo.calls] == ["api_reserve_request_nonce"]
    assert calls == []


def test_encrypted_pdf_artifact_is_rejected(client, fake_odoo):
    def mutate(writer):
        writer.encrypt("pw")

    response = post_artifact(client, pdf_bytes(mutate=mutate))
    assert response.status_code == 422
    assert "api_store_job_artifact" not in [call[1] for call in fake_odoo.calls]


def test_artifact_over_10_mib_is_rejected(client, fake_odoo):
    response = post_artifact(client, b"%PDF-1.7" + b"0" * (10 * 1024 * 1024))
    assert response.status_code == 422
    assert fake_odoo.calls == []


def test_artifact_with_unusable_odoo_result_is_a_conflict(client, fake_odoo, minimal_pdf):
    for payload in (False, {}, {"replayed": False}, {"artifact_ref": "a", "replayed": "no"}):
        fake_odoo.calls.clear()
        fake_odoo.artifact = payload
        assert post_artifact(client, minimal_pdf).status_code == 409


# --------------------------------------------------------------------------
# Fix-round-1 (#5b): the lease token is a signed PATH segment, not a JSON
# body field -- see the module docstring in `app/routers/n8n_v2.py` for why
# (bodyless GET, raw-bytes POST body, shared HMAC canonical input). The
# brief's own two tests are adapted to that shape below: "the field is
# required" becomes "the pre-fix path shape (without the segment) is no
# longer a route at all", and "part of the signed bytes" becomes "swapping
# the token after signing invalidates the signature", since the token lives
# in the same signed `target` as job_id/media_ref/etc. already do.
# --------------------------------------------------------------------------


def test_media_request_without_a_lease_token_segment_no_longer_matches_a_route(
    client, fake_odoo
):
    """The pre-fix path shape (`/jobs/{job}/media/{ref}`, no `/leases/...`
    segment) must not silently keep working as some kind of "token optional"
    fallback -- it should not match a route at all."""
    old_shape_path = f"/api/internal/instances/o19/jobs/{JOB_ID}/media/{MEDIA_REF}"
    response = client.get(
        old_shape_path,
        headers=signed(old_shape_path, b"", method="GET", idempotency_key=None),
    )
    assert response.status_code == 404
    assert fake_odoo.calls == []


def test_artifact_request_without_a_lease_token_segment_no_longer_matches_a_route(
    client, fake_odoo, minimal_pdf
):
    old_shape_path = (
        f"/api/internal/instances/o19/jobs/{JOB_ID}/events/{EVENT_ID}/artifacts/pdf"
    )
    response = client.post(
        old_shape_path,
        content=minimal_pdf,
        headers=signed(old_shape_path, minimal_pdf, content_type="application/pdf"),
    )
    assert response.status_code == 404
    assert fake_odoo.calls == []


def test_media_lease_token_is_part_of_the_signed_bytes(client, fake_odoo):
    """Swapping the token after signing must invalidate the signature -- the
    token is bound the same way `job_id`/`media_ref` already are (the signed
    `target` is the raw request path, `hmac_signing.py:117`)."""
    fake_odoo.media = media_payload(png_bytes())
    signed_for_a = media_path(lease_token=LEASE_TOKEN)
    headers = signed(signed_for_a, b"", method="GET", idempotency_key=None)
    swapped_path = media_path(lease_token=OTHER_LEASE_TOKEN)
    response = client.get(swapped_path, headers=headers)
    assert response.status_code == 401
    assert fake_odoo.calls == []


def test_artifact_lease_token_is_part_of_the_signed_bytes(client, fake_odoo, minimal_pdf):
    signed_for_a = artifact_path(lease_token=LEASE_TOKEN)
    headers = signed(
        signed_for_a, minimal_pdf, content_type="application/pdf"
    )
    swapped_path = artifact_path(lease_token=OTHER_LEASE_TOKEN)
    response = client.post(swapped_path, content=minimal_pdf, headers=headers)
    assert response.status_code == 401
    assert fake_odoo.calls == []
