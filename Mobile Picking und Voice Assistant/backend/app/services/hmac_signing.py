import hashlib
import hmac
import re
from datetime import datetime
from uuid import UUID

from app.models.webhook_security import (
    HmacKey,
    HmacKeyring,
    SignedHeaders,
    VerifiedSignature,
)

_GENERATION = re.compile(r"^[1-9][0-9]*$")
_SIGNATURE = re.compile(r"^v1=([0-9a-f]{64})$")


class SignatureError(ValueError):
    def __init__(self, status_code: int, reason_code: str):
        self.status_code = status_code
        self.reason_code = reason_code
        super().__init__(reason_code)


def payload_fingerprint(raw_body: bytes) -> str:
    return hashlib.sha256(raw_body).hexdigest()


def canonical_signature_input(
    method: str,
    target: str,
    delivery_generation: int | str,
    timestamp: int | str,
    nonce: str,
    raw_body: bytes,
) -> bytes:
    generation = str(delivery_generation)
    if not _GENERATION.fullmatch(generation):
        raise SignatureError(400, "invalid_delivery_generation")
    return "\n".join(
        (
            method,
            target,
            generation,
            str(timestamp),
            nonce,
            payload_fingerprint(raw_body),
        )
    ).encode("utf-8")


def sign_request(
    *,
    method: str,
    target: str,
    delivery_generation: int,
    timestamp: int,
    nonce: str,
    raw_body: bytes,
    key: HmacKey,
) -> SignedHeaders:
    canonical = canonical_signature_input(
        method, target, delivery_generation, timestamp, nonce, raw_body
    )
    digest = hmac.new(key.secret, canonical, hashlib.sha256).hexdigest()
    return SignedHeaders(
        key_id=key.key_id,
        timestamp=timestamp,
        nonce=nonce,
        signed_method=method,
        signed_target=target,
        delivery_generation=delivery_generation,
        signature=f"v1={digest}",
    )


def verify_signature(
    *,
    actual_method: str,
    actual_target: str,
    raw_query: bytes,
    raw_body: bytes,
    headers: dict[str, str],
    keyring: HmacKeyring,
    now: datetime,
    max_skew_seconds: int,
) -> VerifiedSignature:
    if raw_query:
        raise SignatureError(400, "query_not_allowed")
    normalized = {str(name).lower(): value for name, value in headers.items()}
    names = (
        "x-pwr-key-id",
        "x-pwr-timestamp",
        "x-pwr-nonce",
        "x-pwr-signed-method",
        "x-pwr-signed-target",
        "x-pwr-delivery-generation",
        "x-pwr-signature",
    )
    if any(not normalized.get(name) for name in names):
        raise SignatureError(401, "missing_signature_header")

    key = keyring.resolve(normalized["x-pwr-key-id"])
    if key is None:
        raise SignatureError(401, "unknown_key_id")
    try:
        timestamp = int(normalized["x-pwr-timestamp"])
        UUID(normalized["x-pwr-nonce"])
    except (ValueError, TypeError) as exc:
        raise SignatureError(400, "malformed_timestamp_or_nonce") from exc
    if abs(int(now.timestamp()) - timestamp) > max_skew_seconds:
        raise SignatureError(409, "timestamp_outside_window")

    method = normalized["x-pwr-signed-method"]
    target = normalized["x-pwr-signed-target"]
    generation_text = normalized["x-pwr-delivery-generation"]
    if method != actual_method or target != actual_target:
        raise SignatureError(401, "signed_request_mismatch")
    if not _GENERATION.fullmatch(generation_text):
        raise SignatureError(400, "invalid_delivery_generation")
    if not _SIGNATURE.fullmatch(normalized["x-pwr-signature"]):
        raise SignatureError(401, "malformed_signature")

    expected = sign_request(
        method=method,
        target=target,
        delivery_generation=int(generation_text),
        timestamp=timestamp,
        nonce=normalized["x-pwr-nonce"],
        raw_body=raw_body,
        key=key,
    )
    if not hmac.compare_digest(expected.signature, normalized["x-pwr-signature"]):
        raise SignatureError(401, "invalid_signature")
    return VerifiedSignature(
        key_id=key.key_id,
        timestamp=timestamp,
        nonce=normalized["x-pwr-nonce"],
        method=method,
        target=target,
        delivery_generation=int(generation_text),
        fingerprint=payload_fingerprint(raw_body),
    )
