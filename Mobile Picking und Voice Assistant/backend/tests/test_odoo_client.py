"""Tests für den Odoo-Client (Mocked)."""
import pytest
from unittest.mock import AsyncMock, patch
from app.services.odoo_client import OdooClient, OdooAPIError
from app.config import OdooProfile


class TestOdooClient:
    @pytest.fixture
    def client(self):
        with patch("app.services.odoo_client.settings") as mock_settings:
            mock_settings.odoo_url = "http://test:8069"
            mock_settings.odoo_db = "test"
            mock_settings.odoo_user = "admin"
            mock_settings.odoo_api_key = "test-key"
            mock_settings.odoo_password = "test-password"
            yield OdooClient()

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
    async def test_authenticate_falls_back_to_password(self, client):
        """Wenn der API-Key ungültig ist, wird das Passwort verwendet."""
        with patch.object(client, "_json_rpc", new_callable=AsyncMock) as mock_rpc:
            mock_rpc.side_effect = [False, 7]
            uid = await client.authenticate()

        assert uid == 7
        assert client._uid == 7
        assert client._secret == "test-password"
        assert mock_rpc.await_count == 2

    @pytest.mark.anyio
    async def test_search_read(self, client):
        """search_read gibt Liste von Dicts zurück."""
        client._uid = 2
        client._secret = "test-key"
        with patch.object(client, "_json_rpc", new_callable=AsyncMock) as mock_rpc:
            mock_rpc.return_value = [{"id": 1, "name": "Test"}]
            result = await client.search_read("res.partner", [], ["name"])
            assert len(result) == 1
            assert result[0]["name"] == "Test"


def test_client_uses_explicit_profile():
    profile = OdooProfile(
        name="logilab", display_name="LogILab",
        url="https://logilab:8069", db="logilab", user="bot",
        api_key="abc", password="",
    )
    client = OdooClient(profile)
    assert client._url == "https://logilab:8069"
    assert client._db == "logilab"
    assert client._auth_secrets() == ["abc"]


@pytest.mark.anyio
async def test_authenticate_uses_profile_user_and_secret():
    profile = OdooProfile(
        name="logilab", display_name="LogILab",
        url="https://logilab:8069", db="logilab", user="bot",
        api_key="abc", password="",
    )
    client = OdooClient(profile)
    with patch.object(client, "_json_rpc", new_callable=AsyncMock) as mock_rpc:
        mock_rpc.return_value = 11
        uid = await client.authenticate()
    assert uid == 11
    # erstes Positional-Arg-Tupel: (service, method, args)
    args = mock_rpc.await_args.args[2]
    assert args == ["logilab", "bot", "abc", {}]
