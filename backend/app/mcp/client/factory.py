from typing import Callable, Awaitable
from app.mcp.servers.models import MCPAuthType, MCPServerDB
from app.mcp.client.auth import WebOAuthClientProvider, build_oauth_client_metadata


class MCPClientConfigFactory:
    def __init__(
        self,
        resolve_api_key: Callable[[MCPServerDB], Awaitable[str]],
        resolve_storage: Callable[[MCPServerDB], object],
    ):
        self._resolve_api_key = resolve_api_key
        self._resolve_storage = resolve_storage

    async def build(self, config: MCPServerDB) -> dict:

        base_config = {
            "transport": "http",
            "url": config.url,
        }

        if config.auth_type == MCPAuthType.none:
            return base_config

        if config.auth_type == MCPAuthType.api_key:
            api_key = await self._resolve_api_key(config)
            return {**base_config, "headers": {"Authorization": f"Bearer {api_key}"}}

        if config.auth_type == MCPAuthType.oauth2:
            return {
                **base_config,
                "auth": WebOAuthClientProvider(
                    server_url=config.url,
                    client_metadata=build_oauth_client_metadata(config),
                    storage=self._resolve_storage(config),
                )
            }

        raise ValueError(f"Unsupported auth type: {config.auth_type}")
