from datetime import timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.mcp.client.auth import WebOAuthClientProvider, build_oauth_client_metadata
from app.mcp.client.storage import TokenStorageFactory
from app.mcp.servers.models import MCPAuthType, MCPServerDB
from app.mcp.servers.repository import MCPServerRepository


# Deadline for every MCP JSON-RPC request (tools/call, tools/list). Without it
# ``mcp.shared.session`` awaits the response under ``anyio.fail_after(None)`` —
# a literally unbounded wait. On 2026-07-24 an MCP server was OOM-killed after
# it had already streamed its 200 headers; the transport break was swallowed,
# no response ever arrived, and two runs parked for 29.5 min until Cloud Run's
# 1800 s request timeout turned them into 504s.
#
# 120 s is the largest value that can still fire: it matches the MCP servers'
# own Cloud Run ``timeoutSeconds``, so nothing server-side can legitimately
# outlive it. Observed tool calls run 0.1–11.5 s (p95 14.1 s).
MCP_REQUEST_TIMEOUT = timedelta(seconds=120)


class MCPClientConfigFactory:
    def __init__(self, db: AsyncSession, user_id: str):
        self._db = db
        self._user_id = user_id
        self._token_storage_factory = TokenStorageFactory()
        self._servers = MCPServerRepository(db)

    async def build(self, config: MCPServerDB) -> dict:
        base_config = {
            "transport": "http",
            "url": config.url,
            "session_kwargs": {"read_timeout_seconds": MCP_REQUEST_TIMEOUT},
        }

        if config.auth_type == MCPAuthType.none:
            return base_config

        if config.auth_type == MCPAuthType.api_key:
            api_key = await self._servers.get_api_key(config.id)
            return {**base_config, "headers": {"Authorization": f"Bearer {api_key}"}}

        if config.auth_type == MCPAuthType.oauth2:
            return {
                **base_config,
                "auth": WebOAuthClientProvider(
                    server_url=config.url,
                    client_metadata=build_oauth_client_metadata(),
                    storage=self._token_storage_factory.get_storage(
                        self._user_id, str(config.id)
                    ),
                ),
            }

        raise ValueError(f"Unsupported auth type: {config.auth_type}")
