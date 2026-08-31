"""`MCPClientConfigFactory` — the config `MultiServerMCPClient` consumes.

The auth dispatch itself lives in `resolve_transport_auth` and is tested in
`test_transport_auth.py`; what is left here is the config shape.
"""

from unittest.mock import AsyncMock, MagicMock, patch

from app.mcp.client.connectivity import TransportAuth
from app.mcp.client.factory import MCPClientConfigFactory
from app.mcp.servers.models import MCPAuthType


def _config(auth_type, id="s1", url="https://mcp.example.com"):
    c = MagicMock()
    c.auth_type = auth_type
    c.id = id
    c.url = url
    return c


async def test_carries_the_transport_and_url():
    factory = MCPClientConfigFactory(db=MagicMock(), user_id="u1")

    result = await factory.build(_config(MCPAuthType.none))

    assert result == {"transport": "http", "url": "https://mcp.example.com"}


async def test_merges_whatever_the_seam_resolved():
    factory = MCPClientConfigFactory(db=MagicMock(), user_id="u1")
    with patch(
        "app.mcp.client.factory.resolve_transport_auth",
        new=AsyncMock(
            return_value=TransportAuth(headers={"Authorization": "Bearer k"})
        ),
    ):
        result = await factory.build(_config(MCPAuthType.api_key))

    assert result["headers"] == {"Authorization": "Bearer k"}
    assert result["url"] == "https://mcp.example.com"


async def test_passes_the_callers_credential_memo_through():
    """The run graph's shared memo has to reach the seam, or every agent
    re-reads the same credential."""
    factory = MCPClientConfigFactory(db=MagicMock(), user_id="u1")
    memo = MagicMock()
    resolve = AsyncMock(return_value=TransportAuth())
    with patch("app.mcp.client.factory.resolve_transport_auth", new=resolve):
        await factory.build(_config(MCPAuthType.none), credentials=memo)

    assert resolve.await_args.kwargs["credentials"] is memo
