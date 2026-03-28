from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    odoo_url: str = "http://odoo:8069"
    odoo_db: str = "picking"
    odoo_user: str = "admin"
    odoo_api_key: str = ""

    whisper_url: str = "http://whisper:9000"

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


settings = Settings()
