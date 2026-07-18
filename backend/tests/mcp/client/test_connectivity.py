"""Behavioural tests for app/mcp/client/connectivity.py that don't need a live
MCP server: the authorized-vs-reachable split and the stateless probe's OAuth
guard. The provider-construction tests live in tests/mcp/servers/test_service.py;
pagination guards in tests/mcp/servers/test_connect_to_server.py.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.mcp.client import connectivity
from app.mcp.servers.models import MCPAuthType


def _server(auth_type):
    return SimpleNamespace(
        id="s1", url="https://mcp.example.com/mcp", auth_type=auth_type
    )


async def test_is_authorized_true_for_non_oauth_without_touching_network():
    # none/api_key hold no per-user credential, so authorization is a no-op:
    # no provider is built and no token lookup happens.
    with patch.object(connectivity, "build_oauth_provider") as build:
        assert await connectivity.is_authorized(_server(MCPAuthType.none), "u1") is True
        assert (
            await connectivity.is_authorized(_server(MCPAuthType.api_key), "u1") is True
        )
    build.assert_not_called()


async def test_is_authorized_oauth_refresh_uses_ensure_valid_token():
    provider = SimpleNamespace(ensure_valid_token=AsyncMock(return_value=True))
    with patch.object(
        connectivity, "build_oauth_provider", AsyncMock(return_value=provider)
    ):
        assert (
            await connectivity.is_authorized(_server(MCPAuthType.oauth2), "u1") is True
        )
    provider.ensure_valid_token.assert_awaited_once()


async def test_is_authorized_oauth_no_refresh_checks_stored_token_only():
    storage = SimpleNamespace(get_tokens=AsyncMock(return_value=None))
    provider = SimpleNamespace(
        _initialize=AsyncMock(),
        context=SimpleNamespace(storage=storage),
        ensure_valid_token=AsyncMock(),  # must NOT be used when refresh=False
    )
    with patch.object(
        connectivity, "build_oauth_provider", AsyncMock(return_value=provider)
    ):
        result = await connectivity.is_authorized(
            _server(MCPAuthType.oauth2), "u1", refresh=False
        )
    assert result is False
    provider.ensure_valid_token.assert_not_awaited()
    provider._initialize.assert_awaited_once()


async def test_probe_candidate_rejects_oauth_before_saving():
    result = await connectivity.probe_candidate(
        "https://mcp.example.com/mcp", MCPAuthType.oauth2
    )
    assert result.reachable is False
    assert result.oauth_required is False
    assert "saved" in (result.error or "")
