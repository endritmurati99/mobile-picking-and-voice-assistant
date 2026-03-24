"""Tests für den Odoo-Client (Mocked)."""
import pytest
from unittest.mock import AsyncMock, patch
from app.services.odoo_client import OdooClient, OdooAPIError


class TestOdooClient:
    @pytest.fixture
    def client(self):
        with patch("app.services.odoo_client.settings") as mock_settings:
            mock_settings.odoo_url = "http://test:8069"
            mock_settings.odoo_db = "test"
            mock_settings.odoo_user = "admin"
            mock_settings.odoo_api_key = "test-key"
            return OdooClient()

    @pytest.mark.anyio
    async def test_authenticate_success(self, client):
        """Erfolgreiche Authentifizierung setzt UID."""
        with patch.object(client, "_json_rpc", new_callable=AsyncMock) as mock_rpc:
            mock_rpc.return_value = 2
            uid = await client.authenticate()
            assert uid == 2
            assert client._uid == 2

    @pytest.mark.anyio
    async def test_authenticate_failure(self, client):
        """Fehlgeschlagene Auth wirft OdooAPIError."""
        with patch.object(client, "_json_rpc", new_callable=AsyncMock) as mock_rpc:
            mock_rpc.return_value = False
            with pytest.raises(OdooAPIError):
                await client.authenticate()

    @pytest.mark.anyio
    async def test_search_read(self, client):
        """search_read gibt Liste von Dicts zurück."""
        client._uid = 2
        with patch.object(client, "_json_rpc", new_callable=AsyncMock) as mock_rpc:
            mock_rpc.return_value = [{"id": 1, "name": "Test"}]
            result = await client.search_read("res.partner", [], ["name"])
            assert len(result) == 1
            assert result[0]["name"] == "Test"
