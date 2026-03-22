"""
Odoo JSON-RPC Client.

Odoo 18 Community: JSON-RPC (nicht JSON-2).
Feldnamen Odoo 18:
  - stock.move.line: quantity (NICHT qty_done)
  - stock.picking: move_ids (NICHT move_lines)
"""
import httpx
from typing import Any
from app.config import settings


class OdooClient:
    def __init__(self):
        self._url = settings.odoo_url
        self._db = settings.odoo_db
        self._uid = None
        self._client = httpx.AsyncClient(timeout=30.0)

    async def _json_rpc(self, service: str, method: str, args: list) -> Any:
        payload = {
            "jsonrpc": "2.0",
            "method": "call",
            "params": {"service": service, "method": method, "args": args},
            "id": 1,
        }
        resp = await self._client.post(f"{self._url}/jsonrpc", json=payload)
        resp.raise_for_status()
        result = resp.json()
        if result.get("error"):
            raise OdooAPIError(result["error"])
        return result.get("result")

    async def authenticate(self) -> int:
        self._uid = await self._json_rpc(
            "common", "authenticate",
            [self._db, settings.odoo_user, settings.odoo_api_key, {}]
        )
        if not self._uid:
            raise OdooAPIError("Authentifizierung fehlgeschlagen")
        return self._uid

    async def execute_kw(self, model: str, method: str, args: list, kwargs: dict | None = None) -> Any:
        if not self._uid:
            await self.authenticate()
        return await self._json_rpc(
            "object", "execute_kw",
            [self._db, self._uid, settings.odoo_api_key, model, method, args, kwargs or {}]
        )

    async def search_read(self, model: str, domain: list, fields: list, limit: int = 100) -> list[dict]:
        return await self.execute_kw(model, "search_read", [domain], {"fields": fields, "limit": limit})

    async def create(self, model: str, vals: dict) -> int:
        return await self.execute_kw(model, "create", [vals])

    async def write(self, model: str, ids: list[int], vals: dict) -> bool:
        return await self.execute_kw(model, "write", [ids, vals])

    async def call_method(self, model: str, method: str, ids: list[int], args=None, context=None):
        call_args = [ids] + (args or [])
        kw = {"context": context} if context else {}
        return await self.execute_kw(model, method, call_args, kw)


class OdooAPIError(Exception):
    def __init__(self, error_data):
        if isinstance(error_data, dict):
            self.message = error_data.get("data", {}).get("message", str(error_data))
        else:
            self.message = str(error_data)
        super().__init__(self.message)
