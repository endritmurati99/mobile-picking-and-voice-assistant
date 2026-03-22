from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    odoo_url: str = "http://odoo:8069"
    odoo_db: str = "picking"
    odoo_user: str = "admin"
    odoo_api_key: str = ""

    vosk_url: str = "ws://vosk:2700"

    n8n_webhook_base: str = "http://n8n:5678/webhook"
    n8n_webhook_secret: str = ""

    cors_origins: str = "https://localhost"
    log_level: str = "info"

    class Config:
        env_file = ".env"


settings = Settings()
