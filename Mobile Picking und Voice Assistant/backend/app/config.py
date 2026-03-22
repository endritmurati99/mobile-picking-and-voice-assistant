from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env")

    odoo_url: str = "http://odoo:8069"
    odoo_db: str = "picking"
    odoo_user: str = "admin"
    odoo_api_key: str = ""

    whisper_url: str = "http://whisper:9000"

    n8n_webhook_base: str = "http://n8n:5678/webhook"
    n8n_webhook_secret: str = ""

    cors_origins: str = "https://localhost"
    log_level: str = "info"


settings = Settings()
