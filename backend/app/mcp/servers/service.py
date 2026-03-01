from contextlib import asynccontextmanager
from uuid import UUID

from fastapi import Depends, HTTPException
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client
from mcp.shared.auth import OAuthClientInformationFull
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.mcp.client.auth import WebOAuthClientProvider, build_oauth_client_metadata
from app.mcp.client.storage import TokenStorageFactory
from app.mcp.servers.encryption import decrypt_api_key
from app.mcp.servers.models import (
    MCPAuthType,
    MCPServerCreate,
    MCPServerDB,
    MCPServerUpdate,
    OfficialMCPServerRead,
)
from app.mcp.servers.repository import MCPServerRepository
from app.mcp.utils import check_mcp_server_connected


class MCPServerService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.repository = MCPServerRepository(db)

    async def create_server(self, data: MCPServerCreate) -> MCPServerDB:
        if data.auth_type == MCPAuthType.api_key and not data.api_key:
            raise HTTPException(
                status_code=400,
                detail="API key is required when auth_type is 'api_key'",
            )

        db_server = await self.repository.create(data)

        if data.auth_type == MCPAuthType.api_key and data.api_key:
            await self.repository.save_api_key(db_server.id, data.api_key)

        if (
            data.auth_type == MCPAuthType.oauth2
            and data.oauth_client_id
            and data.oauth_client_secret
        ):
            await self.repository.save_oauth_credentials(
                db_server.id,
                data.oauth_client_id,
                data.oauth_client_secret,
                data.oauth_token_endpoint_auth_method,
            )

        await self.db.commit()
        await self.db.refresh(db_server)
        return db_server

    async def get_server(self, server_id: UUID) -> MCPServerDB:
        server = await self.repository.get(server_id)
        if not server:
            raise HTTPException(status_code=404, detail="MCP server not found")
        return server

    async def list_servers(self) -> list[MCPServerDB]:
        return await self.repository.list()

    async def update_server(self, server_id: UUID, data: MCPServerUpdate) -> MCPServerDB:
        server = await self.get_server(server_id)
        update_data = data.model_dump(exclude_unset=True)
        return await self.repository.update(server, update_data)

    async def delete_server(self, server_id: UUID) -> None:
        server = await self.get_server(server_id)
        await self.repository.delete(server)

    async def list_official_servers(self) -> list[OfficialMCPServerRead]:
        rows = await self.repository.list_official()
        return [
            OfficialMCPServerRead(**row[0].model_dump(), is_installed=row[1])
            for row in rows
        ]

    async def reset_server(self, server_id: UUID) -> dict:
        await self.get_server(server_id)
        factory = TokenStorageFactory()
        deleted = await factory.clear_server_data(str(server_id))
        return {"deleted_keys": deleted}

    async def handle_oauth_callback(self, code: str, state: str) -> dict:
        from app.mcp.client.storage import TokenStorageFactory

        storage_factory = TokenStorageFactory()
        result = await storage_factory.get_storage_from_state(state)

        if not result:
            raise HTTPException(
                status_code=400,
                detail="Invalid or expired OAuth state",
            )

        storage, state_data = result

        mcp_server = await self.repository.get(state_data.mcp_server_id)
        if not mcp_server:
            raise HTTPException(status_code=404, detail="MCP server not found")

        client_metadata = build_oauth_client_metadata(mcp_server)

        oauth_credentials = await self.repository.get_oauth_credentials(mcp_server.id)
        if oauth_credentials:
            client_metadata.token_endpoint_auth_method = (
                oauth_credentials.token_endpoint_auth_method or "client_secret_post"
            )

        provider = WebOAuthClientProvider(
            server_url=mcp_server.url,
            client_metadata=client_metadata,
            storage=storage,
        )

        await provider._initialize()

        if mcp_server.url == "https://mcp.supabase.com/mcp":
            provider.context.client_metadata.token_endpoint_auth_method = "client_secret_post"

        await provider.manual_exchange(code, state)

        return {
            "status": "success",
            "message": "Authorization code received and published",
        }

    async def check_connectivity(self, server: MCPServerDB, user_id: str) -> bool:
        if server.auth_type in [MCPAuthType.none, MCPAuthType.api_key]:
            return True

        storage = TokenStorageFactory().get_storage(user_id, str(server.id))
        client_metadata = build_oauth_client_metadata(server)

        provider = WebOAuthClientProvider(
            server_url=server.url,
            client_metadata=client_metadata,
            storage=storage,
        )

        await provider._initialize()
        tokens = await provider.context.storage.get_tokens()
        return tokens is not None

    async def check_connectivity_with_refresh(self, server: MCPServerDB, user_id: str) -> bool:
        return await check_mcp_server_connected(server, user_id)

    async def list_tools(self, server: MCPServerDB, user_id: str) -> list[dict]:
        async with connect_to_server(server, user_id, self.db) as (_, tools):
            return [{"name": tool.name, "description": tool.description} for tool in tools]


@asynccontextmanager
async def connect_to_server(mcp_server: MCPServerDB, user_id: str, db: AsyncSession):
    """Connect to an MCP server and initialize session.

    Similar to the pattern from https://modelcontextprotocol.info/docs/tutorials/building-a-client/
    but adapted for web API context with proper resource management.

    Args:
        mcp_server: MCP server configuration
        user_id: The current user's ID
        db: Database session

    Yields:
        tuple: (session, tools) - Initialized session and available tools

    Raises:
        OAuthAuthorizationRequired: If OAuth authorization is needed
    """
    repository = MCPServerRepository(db)
    storage = TokenStorageFactory().get_storage(user_id, str(mcp_server.id))

    if mcp_server.auth_type == MCPAuthType.oauth2:
        client_metadata = build_oauth_client_metadata(mcp_server)

        oauth_credentials = await repository.get_oauth_credentials(mcp_server.id)

        if oauth_credentials:
            client_id = oauth_credentials.client_id
            client_secret = decrypt_api_key(oauth_credentials.client_secret_encrypted)

            client_metadata.token_endpoint_auth_method = (
                oauth_credentials.token_endpoint_auth_method or "client_secret_post"
            )

            await storage.set_client_info(
                OAuthClientInformationFull(
                    client_id=client_id,
                    client_secret=client_secret,
                    **client_metadata.model_dump(),
                )
            )
        else:
            client_id = None
            client_secret = None

        provider = WebOAuthClientProvider(
            server_url=mcp_server.url,
            client_metadata=client_metadata,
            storage=storage,
            client_id=client_id,
            client_secret=client_secret,
        )

        client_args = {"url": mcp_server.url, "auth": provider}
    elif mcp_server.auth_type == MCPAuthType.api_key:
        api_key = await repository.get_api_key(mcp_server.id)
        client_args = {"url": mcp_server.url, "headers": {
            "Authorization": f"Bearer {api_key}"}}
    else:
        client_args = {"url": mcp_server.url}

    async with streamablehttp_client(**client_args) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()

            try:
                response = await session.list_tools()

                tools = response.tools

                if mcp_server.url == "https://bigquery.googleapis.com/mcp":
                    await session.call_tool("list_dataset_ids", {"project_id": "choose-data-dev"})

                yield session, tools
            except Exception as e:
                raise HTTPException(status_code=500, detail=str(e))


def get_mcp_server_service(db: AsyncSession = Depends(get_db)) -> MCPServerService:
    return MCPServerService(db)
