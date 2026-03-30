from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.mcp.client.factory import MCPClientConfigFactory
from app.mcp.servers.models import MCPAuthType


def _config(auth_type, id="s1", url="https://mcp.example.com"):
    c = MagicMock()
    c.auth_type = auth_type
    c.id = id
    c.url = url
    return c


@pytest.mark.asyncio
async def test_no_auth():
    factory = MCPClientConfigFactory(db=MagicMock(), user_id="u1")
    result = await factory.build(_config(MCPAuthType.none))
    assert result["transport"] == "http"
    assert result["url"] == "https://mcp.example.com"


@pytest.mark.asyncio
@patch("app.mcp.client.factory.get_mcp_server_api_key", new_callable=AsyncMock, return_value="secret")
async def test_api_key_auth(mock_get_key):
    factory = MCPClientConfigFactory(db=MagicMock(), user_id="u1")
    result = await factory.build(_config(MCPAuthType.api_key))
    assert result["headers"] == {"Authorization": "Bearer secret"}


@pytest.mark.asyncio
@patch("app.mcp.client.factory.WebOAuthClientProvider")
@patch("app.mcp.client.factory.build_oauth_client_metadata", return_value={"client_id": "abc"})
@patch("app.mcp.client.factory.TokenStorageFactory")
async def test_oauth_auth(mock_storage_factory_cls, mock_metadata, mock_provider):
    storage = MagicMock()
    mock_storage_factory_cls.return_value.get_storage.return_value = storage

    factory = MCPClientConfigFactory(db=MagicMock(), user_id="u1")
    result = await factory.build(_config(MCPAuthType.oauth2))

    assert "auth" in result
    mock_provider.assert_called_once_with(
        server_url="https://mcp.example.com",
        client_metadata={"client_id": "abc"},
        storage=storage,
    )


@pytest.mark.asyncio
async def test_unsupported_auth_type_raises():
    factory = MCPClientConfigFactory(db=MagicMock(), user_id="u1")
    with pytest.raises(ValueError, match="Unsupported auth type"):
        await factory.build(_config("weird"))
