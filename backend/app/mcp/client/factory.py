from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.mcp.client.auth import WebOAuthClientProvider, build_oauth_client_metadata
from app.mcp.client.storage import TokenStorageFactory
from app.mcp.servers.models import MCPAuthType, MCPServerDB
from app.mcp.servers.repository import MCPServerRepository


class MCPClientConfigFactory:
    def __init__(self, db: AsyncSession, user_id: str):
        self._db = db
        self._user_id = user_id
        self._token_storage_factory = TokenStorageFactory()
        self._servers = MCPServerRepository(db)

    async def build(
        self, config: MCPServerDB, api_keys: dict[UUID, str | None] | None = None
    ) -> dict:
        """The client config for one server.

        ``api_keys`` is an optional caller-owned memo of decrypted keys, used
        when several agents in one run graph bind the same server — the key is
        the same for all of them, and decrypting it is a DB round-trip each
        time. Only the key is shared: the OAuth branch returns a fresh
        ``WebOAuthClientProvider`` per call, because it is stateful and the
        graph's sessions are opened concurrently.
        """
        base_config = {
            "transport": "http",
            "url": config.url,
        }

        if config.auth_type == MCPAuthType.none:
            return base_config

        if config.auth_type == MCPAuthType.api_key:
            if api_keys is None or config.id not in api_keys:
                key = await self._servers.get_api_key(config.id)
                if api_keys is not None:
                    api_keys[config.id] = key
            else:
                key = api_keys[config.id]
            return {**base_config, "headers": {"Authorization": f"Bearer {key}"}}

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
