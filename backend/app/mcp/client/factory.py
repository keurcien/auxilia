from sqlalchemy.ext.asyncio import AsyncSession

from app.mcp.client.connectivity import CredentialCache, resolve_transport_auth
from app.mcp.servers.models import MCPServerDB
from app.mcp.servers.repository import MCPServerRepository


class MCPClientConfigFactory:
    """Builds the per-server config `MultiServerMCPClient` consumes."""

    def __init__(self, db: AsyncSession, user_id: str):
        self._db = db
        self._user_id = user_id
        self._servers = MCPServerRepository(db)

    async def build(
        self, config: MCPServerDB, credentials: CredentialCache | None = None
    ) -> dict:
        """The client config for one server.

        ``credentials`` is an optional caller-owned memo of this run graph's
        decrypted credentials, used when several agents bind the same server —
        see `CredentialCache`. The auth dispatch itself lives in
        `resolve_transport_auth`, shared with the handshake path so the two
        cannot drift.
        """
        transport_auth = await resolve_transport_auth(
            config, self._user_id, self._servers, credentials=credentials
        )
        return {
            "transport": "http",
            "url": config.url,
            **transport_auth.as_kwargs(),
        }
