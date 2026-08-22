from __future__ import annotations

from datetime import UTC, datetime
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
from app.mcp.servers import catalog as mcp_catalog
from app.mcp.servers.encryption import decrypt_value
from app.mcp.servers.models import MCPAuthType, MCPServerDB
from app.mcp.servers.repository import MCPServerRepository
from app.mcp.servers.schemas import (
    MCPCatalogSyncResponse,
    MCPServerAgentResponse,
    MCPServerConnectionResponse,
    MCPServerCreate,
    MCPServerPatch,
    MCPServerResponse,
    OAuthSecretHint,
    OfficialMCPServerResponse,
)
from app.service import BaseService
from app.users.repository import UserRepository


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
        await self.get_or_404(server_id)
        creds = await self.repository.get_oauth_credentials(server_id)
        if not creds:
            return OAuthSecretHint(is_set=False)
        secret = decrypt_value(creds.client_secret_encrypted)
        # Only reveal the last 4 for secrets long enough that it stays a small
        # fraction of the value; short secrets return length only.
        last4 = secret[-4:] if len(secret) >= 10 else None
        return OAuthSecretHint(is_set=True, last4=last4, length=len(secret))

    async def list_responses(self) -> list[MCPServerResponse]:
        rows = await self.repository.list_with_oauth_client_id()
        # Gate client_id on the current auth type (as to_response does): a server
        # switched away from OAuth2 may still have a stale credentials row.
        return [
            MCPServerResponse(
                **server.model_dump(),
                oauth_client_id=(
                    client_id if server.auth_type == MCPAuthType.oauth2 else None
                ),
            )
            for server, client_id in rows
        ]

    async def update(self, server_id: UUID, data: MCPServerPatch) -> MCPServerDB:
        server = await self.get_or_404(server_id)
        # Credential fields are excluded from serialization, so repository.update
        # only touches the mcp_servers row; secrets are persisted separately.
        updated = await self.repository.update(server, data)

        if data.api_key:
            await self.repository.create_or_update_api_key(server_id, data.api_key)

        # Partial: editing client_id (or the token-endpoint auth method) alone
        # patches it while a blank secret keeps the stored one (the client secret
        # is write-only in the UI).
        if (
            data.oauth_client_id
            or data.oauth_client_secret
            or data.oauth_token_endpoint_auth_method
        ):
            await self.repository.update_oauth_credentials(
                server_id,
                client_id=data.oauth_client_id or None,
                client_secret=data.oauth_client_secret or None,
                auth_method=data.oauth_token_endpoint_auth_method or None,
            )

        return updated

    async def list_agents(self, server_id: UUID) -> list[MCPServerAgentResponse]:
        """Agents currently bound to the server (delete-guard dialog)."""
        await self.get_or_404(server_id)
        # Function-level import: agents.mcp_servers imports mcp.servers, so
        # resolving it lazily keeps the modules cycle-free.
        from app.agents.mcp_servers.repository import AgentMCPServerRepository

        agents = await AgentMCPServerRepository(self.db).list_agents_for_server(
            server_id
        )
        return [
            MCPServerAgentResponse(
                id=agent.id, name=agent.name, emoji=agent.emoji, color=agent.color
            )
            for agent in agents
        ]

    async def delete(self, server_id: UUID, *, detach_agents: bool = False) -> None:
        """Refused while agents are bound, unless `detach_agents` — the
        dialog's explicit confirm — removes the bindings first. Previously a
        bound server's delete died on the FK instead of a clean 400."""
        server = await self.get_or_404(server_id)
        from app.agents.mcp_servers.repository import AgentMCPServerRepository

        bindings = AgentMCPServerRepository(self.db)
        if detach_agents:
            await bindings.delete_all_for_server(server_id)
        elif agents := await bindings.list_agents_for_server(server_id):
            raise DomainValidationError(
                f"MCP server is used by {len(agents)} agent(s) — detach it first"
            )
        await self.repository.delete(server)

    async def list_official(self) -> list[OfficialMCPServerResponse]:
        """The catalog (file order) with each entry flagged as installed or not.
        The match is on url — installing an entry copies it into a workspace
        server, so that is the only link between the two."""
        catalog = await mcp_catalog.get_catalog()
        installed = await self.repository.list_urls()
        return [
            OfficialMCPServerResponse(
                **entry.model_dump(), is_installed=entry.url in installed
            )
            for entry in catalog
        ]

    @staticmethod
    async def sync_catalog() -> MCPCatalogSyncResponse:
        return MCPCatalogSyncResponse(**await mcp_catalog.sync_catalog())

    async def reset(self, server_id: UUID) -> dict:
        await self.get(server_id)
        factory = TokenStorageFactory()
        deleted = await factory.clear_server_data(str(server_id))
        return {"deleted_keys": deleted}

    async def list_connections(
        self, server_id: UUID
    ) -> list[MCPServerConnectionResponse]:
        """Users holding a stored OAuth token for the server, with a coarse
        token status: ``expired`` when the access token is past its expiry and
        no refresh token can renew it, ``active`` otherwise."""
        await self.get(server_id)
        factory = TokenStorageFactory()

        user_ids: list[UUID] = []
        for raw_id in await factory.list_connected_user_ids(str(server_id)):
            try:
                user_ids.append(UUID(raw_id))
            except ValueError:
                continue

        users = await UserRepository(self.db).list_by_ids(user_ids)
        users_by_id = {user.id: user for user in users}

        connections: list[MCPServerConnectionResponse] = []
        for user_id in user_ids:
            stored = await factory.get_storage(
                str(user_id), str(server_id)
            ).get_stored_token()
            if not stored:
                continue
            expired = (
                stored.expires_at is not None
                and stored.expires_at <= datetime.now(UTC)
                and not stored.token_payload.refresh_token
            )
            # Deleted users may still hold tokens — keep them listed (name and
            # email None) so an admin can revoke the orphaned connection.
            user = users_by_id.get(user_id)
            connections.append(
                MCPServerConnectionResponse(
                    user_id=user_id,
                    name=user.name if user else None,
                    email=user.email if user else None,
                    status="expired" if expired else "active",
                )
            )

        connections.sort(key=lambda c: (c.name or c.email or str(c.user_id)).lower())
        return connections

    async def delete_connection(self, server_id: UUID, user_id: UUID) -> dict:
        """Revoke one user's connection: clear their stored tokens, client
        info and OAuth metadata for the server. The user re-authenticates on
        their next use."""
        await self.get(server_id)
        factory = TokenStorageFactory()
        deleted = await factory.clear_user_server_data(str(user_id), str(server_id))
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
