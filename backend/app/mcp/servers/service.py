from __future__ import annotations

from uuid import UUID

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.exceptions import (
    AlreadyExistsError,
    DomainValidationError,
    NotFoundError,
)
from app.mcp.client.connectivity import (
    build_oauth_provider,
    connect_to_server,
    initiate_oauth,
    is_authorized,
)
from app.mcp.client.storage import TokenStorageFactory
from app.mcp.servers.encryption import decrypt_value
from app.mcp.servers.models import MCPAuthType, MCPServerDB
from app.mcp.servers.repository import MCPServerRepository
from app.mcp.servers.schemas import (
    MCPServerCreate,
    MCPServerPatch,
    MCPServerResponse,
    OAuthSecretHint,
    OfficialMCPServerResponse,
)
from app.service import BaseService


class MCPServerService(BaseService[MCPServerDB, MCPServerRepository]):
    not_found_message = "MCP server not found"

    def __init__(self, db: AsyncSession):
        super().__init__(db, MCPServerRepository(db))

    async def create(self, data: MCPServerCreate) -> MCPServerDB:
        if await self.repository.get_by_url(data.url):
            raise AlreadyExistsError("An MCP server with this URL already exists")

        if data.auth_type == MCPAuthType.api_key and not data.api_key:
            raise DomainValidationError(
                "API key is required when auth_type is 'api_key'"
            )

        db_server = await self.repository.create(data)

        if data.auth_type == MCPAuthType.api_key and data.api_key:
            await self.repository.create_or_update_api_key(db_server.id, data.api_key)

        if (
            data.auth_type == MCPAuthType.oauth2
            and data.oauth_client_id
            and data.oauth_client_secret
        ):
            await self.repository.create_or_update_oauth_credentials(
                db_server.id,
                data.oauth_client_id,
                data.oauth_client_secret,
                data.oauth_token_endpoint_auth_method,
            )

        return db_server

    async def get(self, server_id: UUID) -> MCPServerDB:
        return await self.get_or_404(server_id)

    async def to_response(self, server: MCPServerDB) -> MCPServerResponse:
        """Project a server to its API response, enriching OAuth2 servers with
        their static client_id (the client secret is never exposed)."""
        oauth_client_id = None
        if server.auth_type == MCPAuthType.oauth2:
            creds = await self.repository.get_oauth_credentials(server.id)
            oauth_client_id = creds.client_id if creds else None
        return MCPServerResponse(**server.model_dump(), oauth_client_id=oauth_client_id)

    async def get_oauth_secret_hint(self, server_id: UUID) -> OAuthSecretHint:
        """Return a non-reversible hint (last 4 chars + length) about the stored
        OAuth client secret. Requires decrypting the secret, so the endpoint that
        exposes this is admin-gated."""
        creds = await self.repository.get_oauth_credentials(server_id)
        if not creds:
            return OAuthSecretHint(is_set=False)
        secret = decrypt_value(creds.client_secret_encrypted)
        return OAuthSecretHint(is_set=True, last4=secret[-4:], length=len(secret))

    async def list_responses(self) -> list[MCPServerResponse]:
        rows = await self.repository.list_with_oauth_client_id()
        return [
            MCPServerResponse(**server.model_dump(), oauth_client_id=client_id)
            for server, client_id in rows
        ]

    async def update(self, server_id: UUID, data: MCPServerPatch) -> MCPServerDB:
        server = await self.get_or_404(server_id)
        # Credential fields are excluded from serialization, so repository.update
        # only touches the mcp_servers row; secrets are persisted separately.
        updated = await self.repository.update(server, data)

        if data.api_key:
            await self.repository.create_or_update_api_key(server_id, data.api_key)

        # Partial: editing client_id alone patches it while a blank secret keeps
        # the stored one (client secret is write-only in the UI).
        if data.oauth_client_id or data.oauth_client_secret:
            await self.repository.update_oauth_credentials(
                server_id,
                client_id=data.oauth_client_id or None,
                client_secret=data.oauth_client_secret or None,
                auth_method=data.oauth_token_endpoint_auth_method or None,
            )

        return updated

    async def delete(self, server_id: UUID) -> None:
        server = await self.get_or_404(server_id)
        await self.repository.delete(server)

    async def list_official(self) -> list[OfficialMCPServerResponse]:
        rows = await self.repository.list_official()
        return [
            OfficialMCPServerResponse(**row[0].model_dump(), is_installed=row[1])
            for row in rows
        ]

    async def reset(self, server_id: UUID) -> dict:
        await self.get(server_id)
        factory = TokenStorageFactory()
        deleted = await factory.clear_server_data(str(server_id))
        return {"deleted_keys": deleted}

    async def handle_oauth_callback(self, code: str, state: str) -> dict:
        storage_factory = TokenStorageFactory()
        result = await storage_factory.get_storage_from_state(state)

        if not result:
            raise DomainValidationError("Invalid or expired OAuth state")

        storage, state_data = result

        mcp_server = await self.repository.get(state_data.mcp_server_id)
        if not mcp_server:
            raise NotFoundError("MCP server not found")

        provider = await build_oauth_provider(mcp_server, storage, self.repository)

        await provider._initialize()

        if mcp_server.url == "https://mcp.supabase.com/mcp":
            provider.context.client_metadata.token_endpoint_auth_method = (
                "client_secret_post"
            )

        await provider.manual_exchange(code, state)

        return {
            "status": "success",
            "message": "Authorization code received and published",
        }

    async def list_tools(self, server: MCPServerDB, user_id: str) -> list[dict]:
        if server.auth_type == MCPAuthType.oauth2 and not await is_authorized(
            server, user_id
        ):
            # Not connected: discover OAuth metadata and raise
            # OAuthAuthorizationRequired (translated globally to
            # 401 {oauth_required, auth_url}). No business tool is called.
            await initiate_oauth(server, user_id, self.db)

        async with connect_to_server(server, user_id, self.db) as (_, tools):
            return [
                {"name": tool.name, "description": tool.description} for tool in tools
            ]


def get_mcp_server_service(db: AsyncSession = Depends(get_db)) -> MCPServerService:
    return MCPServerService(db)
