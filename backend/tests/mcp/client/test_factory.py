from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import anyio
import pytest
from mcp import ClientSession
from mcp.shared.exceptions import McpError

from app.mcp.client.factory import MCP_REQUEST_TIMEOUT, MCPClientConfigFactory
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
async def test_api_key_auth():
    with patch("app.mcp.client.factory.MCPServerRepository") as mock_repo_cls:
        repo = MagicMock()
        repo.get_api_key = AsyncMock(return_value="secret")
        mock_repo_cls.return_value = repo

        factory = MCPClientConfigFactory(db=MagicMock(), user_id="u1")
        result = await factory.build(_config(MCPAuthType.api_key))
        assert result["headers"] == {"Authorization": "Bearer secret"}


@pytest.mark.asyncio
@patch("app.mcp.client.factory.WebOAuthClientProvider")
@patch(
    "app.mcp.client.factory.build_oauth_client_metadata",
    return_value={"client_id": "abc"},
)
@patch("app.mcp.client.factory.TokenStorageFactory")
async def test_oauth_auth(mock_storage_factory_cls, mock_metadata, mock_provider):
    storage = MagicMock()
    mock_storage_factory_cls.return_value.get_storage.return_value = storage

    factory = MCPClientConfigFactory(db=MagicMock(), user_id="u1")
    result = await factory.build(_config(MCPAuthType.oauth2))

    assert "auth" in result
    mock_metadata.assert_called_once_with()
    mock_provider.assert_called_once_with(
        server_url="https://mcp.example.com",
        client_metadata={"client_id": "abc"},
        storage=storage,
    )


@pytest.mark.asyncio
@patch("app.mcp.client.factory.WebOAuthClientProvider")
@patch(
    "app.mcp.client.factory.build_oauth_client_metadata",
    return_value={"client_id": "abc"},
)
@patch("app.mcp.client.factory.TokenStorageFactory")
async def test_oauth_passes_server_id_as_str(
    mock_storage_factory_cls, _mock_metadata, _mock_provider
):
    # Regression: config.id is a UUID; get_storage wants a str (pydantic v2
    # rejects UUID for OAuthStateData.mcp_server_id). The old test used id="s1"
    # (already a str) so it couldn't catch this.
    from uuid import uuid4

    get_storage = mock_storage_factory_cls.return_value.get_storage
    sid = uuid4()

    factory = MCPClientConfigFactory(db=MagicMock(), user_id="u1")
    await factory.build(_config(MCPAuthType.oauth2, id=sid))

    get_storage.assert_called_once_with("u1", str(sid))


@pytest.mark.asyncio
async def test_unsupported_auth_type_raises():
    factory = MCPClientConfigFactory(db=MagicMock(), user_id="u1")
    with pytest.raises(ValueError, match="Unsupported auth type"):
        await factory.build(_config("weird"))


@pytest.mark.asyncio
@patch("app.mcp.client.factory.WebOAuthClientProvider")
@patch("app.mcp.client.factory.build_oauth_client_metadata", return_value={})
@patch("app.mcp.client.factory.TokenStorageFactory")
async def test_every_auth_branch_carries_a_request_deadline(*_mocks):
    # Regression guard for the 2026-07-24 incident: without
    # read_timeout_seconds, mcp.shared.session awaits responses under
    # anyio.fail_after(None) and a dropped reply parks the run until Cloud
    # Run's 1800 s request timeout. Every branch spreads **base_config, so a
    # new branch that rebuilds the dict from scratch would silently lose this.
    with patch("app.mcp.client.factory.MCPServerRepository") as mock_repo_cls:
        mock_repo_cls.return_value.get_api_key = AsyncMock(return_value="secret")
        factory = MCPClientConfigFactory(db=MagicMock(), user_id="u1")

        for auth_type in (MCPAuthType.none, MCPAuthType.api_key, MCPAuthType.oauth2):
            result = await factory.build(_config(auth_type))
            assert result["session_kwargs"] == {
                "read_timeout_seconds": MCP_REQUEST_TIMEOUT
            }, auth_type


@pytest.mark.asyncio
async def test_read_timeout_turns_a_lost_reply_into_an_error():
    # The behaviour the config above buys: a peer that never answers raises
    # McpError instead of hanging forever. Drives ClientSession over in-memory
    # streams — no HTTP, no stub server — with a short deadline so the test is
    # fast; MCP_REQUEST_TIMEOUT is asserted separately above.
    _read_send, read_recv = anyio.create_memory_object_stream(10)
    write_send, _write_recv = anyio.create_memory_object_stream(10)

    async with ClientSession(
        read_recv, write_send, read_timeout_seconds=timedelta(milliseconds=100)
    ) as session:
        with pytest.raises(McpError, match="Timed out"):
            await session.list_tools()
