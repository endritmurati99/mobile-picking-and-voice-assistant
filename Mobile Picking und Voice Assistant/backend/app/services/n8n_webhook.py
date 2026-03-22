"""Fire-and-Forget Webhook Client für n8n."""
import logging
import httpx
from app.config import settings

logger = logging.getLogger(__name__)


class N8NWebhookClient:
    def __init__(self):
        self._base = settings.n8n_webhook_base
        self._secret = settings.n8n_webhook_secret
        self._client = httpx.AsyncClient(timeout=5.0)

    async def fire(self, path: str, data: dict) -> None:
        """Fire-and-forget: Fehler werden geloggt, nicht propagiert."""
        try:
            headers = {}
            if self._secret:
                headers["X-Webhook-Secret"] = self._secret
            await self._client.post(f"{self._base}/{path}", json=data, headers=headers)
        except Exception as e:
            logger.warning(f"n8n Webhook fehlgeschlagen ({path}): {e}")
