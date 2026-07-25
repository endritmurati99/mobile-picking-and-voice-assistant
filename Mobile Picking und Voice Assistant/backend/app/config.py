import base64
import binascii
import json
from dataclasses import dataclass
from urllib.parse import urlparse

from pydantic_settings import BaseSettings, SettingsConfigDict


@dataclass(frozen=True)
class OdooProfile:
    name: str
    display_name: str
    url: str
    db: str
    user: str
    api_key: str = ""
    password: str = ""


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    odoo_url: str = "http://odoo:8069"
    odoo_db: str = "picking"
    odoo_user: str = "admin"
    odoo_api_key: str = ""
    odoo_password: str = ""
    odoo_instances_json: str = ""

    whisper_url: str = "http://whisper:9000"
    piper_url: str = "http://piper:5500"

    # Lokales LLM (Ollama) fuer die KI-Qualitaetsbewertung. Laeuft offline auf dem
    # Lab-PC; kein Cloud-Zugriff noetig. Faellt bei Ausfall auf die n8n-Heuristik zurueck.
    llm_provider: str = "ollama"
    llm_endpoint: str = "http://ollama:11434"
    llm_model: str = "qwen2.5:7b"
    llm_timeout_ms: int = 30000
    # Kleines, schnelles Modell nur fuer den Voice-Intent-Fallback (nicht Qualitaet).
    llm_voice_model: str = "qwen2.5:1.5b"
    llm_voice_timeout_ms: int = 4000
    openai_api_key: str = ""

    n8n_webhook_base: str = "http://n8n:5678/webhook"
    n8n_webhook_path_quality_alert_created: str = "quality-alert-created"
    n8n_webhook_path_voice_exception_query: str = "voice-exception-query"
    n8n_webhook_path_shortage_reported: str = "shortage-reported"
    n8n_webhook_path_pick_confirmed: str = "pick-confirmed"
    n8n_webhook_secret: str = ""
    n8n_sync_timeout_ms: int = 7000
    n8n_callback_secret: str = ""
    n8n_connect_timeout_ms: int = 1000
    n8n_circuit_breaker_failures: int = 3
    n8n_circuit_breaker_open_seconds: int = 60

    cors_origins: str = "https://localhost"
    log_level: str = "info"
    mobile_claim_ttl_seconds: int = 120
    mobile_claim_heartbeat_seconds: int = 30
    mobile_idempotency_ttl_seconds: int = 86400
    mobile_header_grace_mode: bool = True
    demo_traceability_enabled: bool = False
    demo_traceability_allowed_dbs: str = "masterfischer_o19_trial"

    # Secure runtime / session / auth configuration (Task 1: Platform Security and
    # Event Contracts Foundation). See docs/superpowers/plans/
    # 2026-07-23-platform-security-event-contracts-foundation.md for rationale.
    runtime_profile: str = "development"
    pwa_origins: str = "https://localhost"
    trusted_caddy_peers: str = "127.0.0.1"
    session_cookie_name: str = "pwr_session"
    session_max_age_seconds: int = 28800
    session_role_revalidate_seconds: int = 300
    session_throttle_hmac_secret_b64: str = ""
    login_failure_limit: int = 5
    login_window_seconds: int = 900
    login_throttle_retention_seconds: int = 86400
    pwr_hmac_max_skew_seconds: int = 300
    pwr_nonce_ttl_seconds: int = 600
    pwr_backend_to_n8n_active_key_id: str = ""
    pwr_backend_to_n8n_active_secret_b64: str = ""
    pwr_backend_to_n8n_previous_key_id: str = ""
    pwr_backend_to_n8n_previous_secret_b64: str = ""
    pwr_n8n_to_backend_active_key_id: str = ""
    pwr_n8n_to_backend_active_secret_b64: str = ""
    pwr_n8n_to_backend_previous_key_id: str = ""
    pwr_n8n_to_backend_previous_secret_b64: str = ""
    workflow_registry_path: str = "../n8n/workflow-registry.json"
    dispatcher_enabled: bool = False
    dispatcher_poll_seconds: float = 2.0
    dispatcher_lease_seconds: int = 60
    dispatcher_batch_size: int = 50


settings = Settings()
ODOO19_TRIAL_PROFILE_NAMES = {"o19", "odoo19", "o19-trial", "odoo19-trial"}
ODOO19_TRIAL_DB = "masterfischer_o19_trial"


def get_instance_registry(candidate: Settings = settings) -> dict[str, OdooProfile]:
    """Register aller bekannten Odoo-Instanzen fuer die uebergebene `candidate`
    Settings-Instanz (niemals ein anderes globales Settings-Objekt).

    `local` kommt kanonisch aus den odoo_*-Settings; weitere Profile aus
    ODOO_INSTANCES_JSON (Secrets .env-only). Ausnahme: in production ist ein
    nicht-leeres ODOO_INSTANCES_JSON autoritativ — das Register startet leer und
    ein explizit gelistetes `local`-Profil wird wie jedes andere behandelt statt
    des impliziten Legacy-`local`-Profils.
    """
    raw = (candidate.odoo_instances_json or "").strip()
    production_authoritative = candidate.runtime_profile == "production" and bool(raw)

    registry: dict[str, OdooProfile] = {}
    if not production_authoritative:
        registry["local"] = OdooProfile(
            name="local",
            display_name="Lokal",
            url=candidate.odoo_url,
            db=candidate.odoo_db,
            user=candidate.odoo_user,
            api_key=candidate.odoo_api_key,
            password=candidate.odoo_password,
        )

    if not raw:
        return registry
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"ODOO_INSTANCES_JSON ist kein gueltiges JSON: {exc}") from exc
    if not isinstance(parsed, dict):
        raise ValueError("ODOO_INSTANCES_JSON muss ein JSON-Objekt sein.")
    for name, cfg in parsed.items():
        key = str(name).strip().lower()
        if key == "local" and not production_authoritative:
            continue  # local ist kanonisch aus odoo_* — JSON-local wird ignoriert
        if not isinstance(cfg, dict):
            raise ValueError(f"ODOO_INSTANCES_JSON['{name}'] muss ein Objekt sein.")
        if "url" not in cfg or "db" not in cfg:
            raise ValueError(f"ODOO_INSTANCES_JSON['{name}'] braucht 'url' und 'db'.")
        db_name = str(cfg["db"])
        if key in ODOO19_TRIAL_PROFILE_NAMES and db_name != ODOO19_TRIAL_DB:
            raise ValueError(
                f"ODOO_INSTANCES_JSON['{name}'] muss fuer Odoo-19-Trial die DB "
                f"'{ODOO19_TRIAL_DB}' nutzen, nicht '{db_name}'."
            )
        registry[key] = OdooProfile(
            name=key,
            display_name=str(cfg.get("display_name") or key),
            url=str(cfg["url"]),
            db=db_name,
            user=str(cfg.get("user") or "admin"),
            api_key=str(cfg.get("api_key") or ""),
            password=str(cfg.get("password") or ""),
        )
    return registry


def decode_secret_b64(name: str, value: str) -> bytes:
    try:
        decoded = base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError(f"{name} must be valid base64") from exc
    if len(decoded) < 32:
        raise ValueError(f"{name} must decode to at least 32 bytes")
    return decoded


def parse_origins(value: str) -> tuple[str, ...]:
    return tuple(item.strip() for item in value.split(",") if item.strip())


def validate_runtime_security(candidate: Settings) -> None:
    if candidate.runtime_profile != "production":
        return

    origins = parse_origins(candidate.pwa_origins)
    if not origins or "*" in origins:
        raise ValueError("Wildcard or empty PWA origins are forbidden in production")
    if any(urlparse(origin).scheme != "https" for origin in origins):
        raise ValueError("Production PWA origins must use HTTPS")
    if candidate.mobile_header_grace_mode:
        raise ValueError("mobile header grace mode is forbidden in production")
    profiles = get_instance_registry(candidate)
    if not profiles or any(
        not (profile.api_key or profile.password) for profile in profiles.values()
    ):
        raise ValueError(
            "Every production Odoo profile requires an Odoo service credential"
        )
    if len(candidate.n8n_webhook_secret.encode("utf-8")) < 32:
        raise ValueError("native n8n webhook credential must be at least 32 bytes")
    if len(candidate.n8n_callback_secret.encode("utf-8")) < 32:
        raise ValueError("legacy callback credential must be at least 32 bytes")

    required_b64 = {
        "SESSION_THROTTLE_HMAC_SECRET_B64": candidate.session_throttle_hmac_secret_b64,
        "PWR_BACKEND_TO_N8N_ACTIVE_SECRET_B64": candidate.pwr_backend_to_n8n_active_secret_b64,
        "PWR_N8N_TO_BACKEND_ACTIVE_SECRET_B64": candidate.pwr_n8n_to_backend_active_secret_b64,
    }
    for name, value in required_b64.items():
        decode_secret_b64(name, value)

    if not candidate.pwr_backend_to_n8n_active_key_id:
        raise ValueError("backend-to-n8n active key ID is required")
    if not candidate.pwr_n8n_to_backend_active_key_id:
        raise ValueError("n8n-to-backend active key ID is required")

    previous_pairs = (
        (
            candidate.pwr_backend_to_n8n_previous_key_id,
            candidate.pwr_backend_to_n8n_previous_secret_b64,
            "PWR_BACKEND_TO_N8N_PREVIOUS_SECRET_B64",
        ),
        (
            candidate.pwr_n8n_to_backend_previous_key_id,
            candidate.pwr_n8n_to_backend_previous_secret_b64,
            "PWR_N8N_TO_BACKEND_PREVIOUS_SECRET_B64",
        ),
    )
    for key_id, secret, name in previous_pairs:
        if bool(key_id) != bool(secret):
            raise ValueError(f"{name} and its key ID must be configured together")
        if secret:
            decode_secret_b64(name, secret)


validate_runtime_security(settings)
