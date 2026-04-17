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

    async def build(self, config: MCPServerDB) -> dict:

        base_config = {
            "transport": "http",
            "url": config.url,
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
                    client_metadata=build_oauth_client_metadata(config),
                    storage=self._token_storage_factory.get_storage(
                        self._user_id, config.id
                    ),
                ),
            }

        raise ValueError(f"Unsupported auth type: {config.auth_type}")
