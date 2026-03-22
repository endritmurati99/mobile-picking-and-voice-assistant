"""Dependency Injection für FastAPI."""
from functools import lru_cache
from app.services.odoo_client import OdooClient
from app.services.picking_service import PickingService
from app.services.n8n_webhook import N8NWebhookClient
from app.config import settings


@lru_cache()
def get_odoo_client() -> OdooClient:
    return OdooClient()


@lru_cache()
def get_n8n_client() -> N8NWebhookClient:
    return N8NWebhookClient()


def get_picking_service() -> PickingService:
    return PickingService(get_odoo_client(), get_n8n_client())
