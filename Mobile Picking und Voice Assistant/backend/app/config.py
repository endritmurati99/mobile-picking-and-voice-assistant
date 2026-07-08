import json
from dataclasses import dataclass
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


settings = Settings()
ODOO19_TRIAL_PROFILE_NAMES = {"o19", "odoo19", "o19-trial", "odoo19-trial"}
ODOO19_TRIAL_DB = "masterfischer_o19_trial"


def get_instance_registry() -> dict[str, OdooProfile]:
    """Register aller bekannten Odoo-Instanzen. `local` kommt immer kanonisch aus
    den odoo_*-Settings; weitere Profile aus ODOO_INSTANCES_JSON (Secrets .env-only)."""
    registry: dict[str, OdooProfile] = {
        "local": OdooProfile(
            name="local",
            display_name="Lokal",
            url=settings.odoo_url,
            db=settings.odoo_db,
            user=settings.odoo_user,
            api_key=settings.odoo_api_key,
            password=settings.odoo_password,
        )
    }
    raw = (settings.odoo_instances_json or "").strip()
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
        if key == "local":
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
