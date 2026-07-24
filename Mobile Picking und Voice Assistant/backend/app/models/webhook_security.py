from dataclasses import dataclass, field


@dataclass(frozen=True)
class HmacKey:
    key_id: str
    secret: bytes = field(repr=False)

    def __post_init__(self) -> None:
        if not self.key_id or len(self.secret) < 32:
            raise ValueError("HMAC keys require an ID and at least 32 secret bytes")


@dataclass(frozen=True)
class HmacKeyring:
    active: HmacKey
    previous: HmacKey | None = None

    def resolve(self, key_id: str) -> HmacKey | None:
        for key in (self.active, self.previous):
            if key is not None and key.key_id == key_id:
                return key
        return None


@dataclass(frozen=True)
class SignedHeaders:
    key_id: str
    timestamp: int
    nonce: str
    signed_method: str
    signed_target: str
    delivery_generation: int
    signature: str

    def as_http_headers(self) -> dict[str, str]:
        return {
            "X-PWR-Key-Id": self.key_id,
            "X-PWR-Timestamp": str(self.timestamp),
            "X-PWR-Nonce": self.nonce,
            "X-PWR-Signed-Method": self.signed_method,
            "X-PWR-Signed-Target": self.signed_target,
            "X-PWR-Delivery-Generation": str(self.delivery_generation),
            "X-PWR-Signature": self.signature,
        }


@dataclass(frozen=True)
class VerifiedSignature:
    key_id: str
    timestamp: int
    nonce: str
    method: str
    target: str
    delivery_generation: int
    fingerprint: str
