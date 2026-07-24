from datetime import datetime, timezone

import pytest

from app.models.webhook_security import HmacKey, HmacKeyring
from app.services.hmac_signing import (
    SignatureError,
    canonical_signature_input,
    payload_fingerprint,
    sign_request,
    verify_signature,
)

BODY = b'{"event_id":"a4ff5ca2-4546-4ea4-8e6c-b75bc003ca32"}'
NONCE = "123e4567-e89b-42d3-a456-426614174000"
NOW = datetime.fromtimestamp(1760000000, tz=timezone.utc)


def test_python_signature_matches_frozen_cross_runtime_vector():
    signed = sign_request(
        method="POST",
        target="/webhook/quality-assessment-v2",
        delivery_generation=1,
        timestamp=1760000000,
        nonce=NONCE,
        raw_body=BODY,
        key=HmacKey("b2n-test", b"0" * 32),
    )
    assert payload_fingerprint(BODY) == (
        "cdc9aeda6396616866f863a30ce8507232b2cecd6cdd68c206c24b8c128751fc"
    )
    assert signed.signature == (
        "v1=6466f16aca767c63504c2d002d729c35fdc12df969060bc4e7e76fd0c69a43d4"
    )


def test_verifier_accepts_previous_rotation_key():
    headers = sign_request(
        method="POST",
        target="/api/internal/n8n/v2/callbacks/status",
        delivery_generation=2,
        timestamp=1760000000,
        nonce=NONCE,
        raw_body=BODY,
        key=HmacKey("previous", b"1" * 32),
    )
    verified = verify_signature(
        actual_method="POST",
        actual_target="/api/internal/n8n/v2/callbacks/status",
        raw_query=b"",
        raw_body=BODY,
        headers=headers.as_http_headers(),
        keyring=HmacKeyring(
            active=HmacKey("active", b"2" * 32),
            previous=HmacKey("previous", b"1" * 32),
        ),
        now=NOW,
        max_skew_seconds=300,
    )
    assert verified.key_id == "previous"
    assert verified.delivery_generation == 2


def test_verifier_accepts_starlette_lowercase_header_mapping():
    signed = sign_request(
        method="POST",
        target="/api/internal/n8n/v2/callbacks/status",
        delivery_generation=1,
        timestamp=1760000000,
        nonce=NONCE,
        raw_body=BODY,
        key=HmacKey("active", b"2" * 32),
    )
    verified = verify_signature(
        actual_method="POST",
        actual_target="/api/internal/n8n/v2/callbacks/status",
        raw_query=b"",
        raw_body=BODY,
        headers={key.lower(): value for key, value in signed.as_http_headers().items()},
        keyring=HmacKeyring(active=HmacKey("active", b"2" * 32)),
        now=NOW,
        max_skew_seconds=300,
    )
    assert verified.key_id == "active"


@pytest.mark.parametrize(
    ("target", "generation", "query"),
    [
        ("/api/internal/n8n/v2/callbacks/status?x=1", "1", b"x=1"),
        ("/api/internal/n8n/v2/callbacks/status", "01", b""),
        ("/api/internal/n8n/v2/callbacks/status", "0", b""),
    ],
)
def test_verifier_rejects_query_and_noncanonical_generation(target, generation, query):
    headers = {
        "X-PWR-Key-Id": "active",
        "X-PWR-Timestamp": "1760000000",
        "X-PWR-Nonce": NONCE,
        "X-PWR-Signed-Method": "POST",
        "X-PWR-Signed-Target": target,
        "X-PWR-Delivery-Generation": generation,
        "X-PWR-Signature": "v1=" + ("0" * 64),
    }
    with pytest.raises(SignatureError):
        verify_signature(
            actual_method="POST",
            actual_target="/api/internal/n8n/v2/callbacks/status",
            raw_query=query,
            raw_body=BODY,
            headers=headers,
            keyring=HmacKeyring(active=HmacKey("active", b"2" * 32)),
            now=NOW,
            max_skew_seconds=300,
        )
