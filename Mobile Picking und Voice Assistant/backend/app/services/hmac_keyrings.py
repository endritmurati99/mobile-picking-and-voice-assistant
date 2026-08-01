"""Bau der HMAC-Keyrings aus einer Settings-Instanz.

Eigene Datei, weil `app.dependencies` sonst der einzige Ort waere, an dem der
Keyring gebaut werden kann -- und `app.runtime` importiert `app.dependencies`
nicht (die Abhaengigkeit laeuft in die andere Richtung).

Beide Richtungen sind fail closed: `decode_secret_b64` verlangt >= 32
entschluesselte Bytes und wirft bei fehlender oder ungueltiger Konfiguration
`ValueError`. Es gibt keinen Pfad zu einem leeren oder Default-Secret.
"""
from app.config import Settings, decode_secret_b64, read_secret
from app.models.webhook_security import HmacKey, HmacKeyring


def build_n8n_to_backend_keyring(candidate: Settings) -> HmacKeyring:
    """Keyring fuer die Richtung n8n -> Backend aus der uebergebenen
    Settings-Instanz -- niemals aus einem globalen Settings-Objekt."""
    active = HmacKey(
        candidate.pwr_n8n_to_backend_active_key_id,
        decode_secret_b64(
            "PWR_N8N_TO_BACKEND_ACTIVE_SECRET_B64",
            read_secret(
                candidate.pwr_n8n_to_backend_active_secret_b64,
                candidate.pwr_n8n_to_backend_active_secret_file,
            ),
        ),
    )
    previous = None
    if candidate.pwr_n8n_to_backend_previous_key_id:
        previous = HmacKey(
            candidate.pwr_n8n_to_backend_previous_key_id,
            decode_secret_b64(
                "PWR_N8N_TO_BACKEND_PREVIOUS_SECRET_B64",
                read_secret(
                    candidate.pwr_n8n_to_backend_previous_secret_b64,
                    candidate.pwr_n8n_to_backend_previous_secret_file,
                ),
            ),
        )
    return HmacKeyring(active=active, previous=previous)
