"""Connectivity probes for MCP servers — pure functions of (server, user_id).

Kept separate from ``MCPServerService`` because they don't touch the database,
so forcing them through a service created a ``Service(None)`` pattern at the
call sites.
"""

from app.mcp.client.auth import WebOAuthClientProvider, build_oauth_client_metadata
from app.mcp.client.storage import TokenStorageFactory
from app.mcp.servers.models import MCPAuthType, MCPServerDB
from app.mcp.utils import probe_mcp_server


async def is_oauth_connected(server: MCPServerDB, user_id: str) -> bool:
    """Return True when an OAuth MCP server has stored tokens for the user.

    Does **not** attempt a refresh. Use :func:`probe_connectivity_with_refresh`
    for probes where an expired-but-refreshable token should still count as
    connected.
    """
    storage = TokenStorageFactory().get_storage(user_id, str(server.id))
    client_metadata = build_oauth_client_metadata()
    provider = WebOAuthClientProvider(
        server_url=server.url,
        client_metadata=client_metadata,
        storage=storage,
    )
    await provider._initialize()
    tokens = await provider.context.storage.get_tokens()
    return tokens is not None


async def probe_connectivity(server: MCPServerDB, user_id: str) -> bool:
    """Lightweight probe: servers without auth are always connected, OAuth
    servers count as connected if a token exists (no refresh attempted)."""
    if server.auth_type in (MCPAuthType.none, MCPAuthType.api_key):
        return True
    return await is_oauth_connected(server, user_id)


async def probe_connectivity_with_refresh(server: MCPServerDB, user_id: str) -> bool:
    """Probe that also attempts a token refresh when the stored token is
    expired. Delegates to :func:`app.mcp.utils.probe_mcp_server`."""
    return await probe_mcp_server(server, user_id)
