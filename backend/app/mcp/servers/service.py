from __future__ import annotations

from contextlib import asynccontextmanager
from uuid import UUID

from fastapi import Depends
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.exceptions import (
    AlreadyExistsError,
    DomainError,
    DomainValidationError,
    NotFoundError,
)
from app.mcp.client.auth import WebOAuthClientProvider, build_oauth_client_metadata
from app.mcp.client.storage import RedisTokenStorage, TokenStorageFactory
from app.mcp.servers.encryption import decrypt_value as decrypt_api_key
from app.mcp.servers.models import MCPAuthType, MCPServerDB
from app.mcp.servers.repository import MCPServerRepository
from app.mcp.servers.schemas import (
    MCPServerCreate,
    MCPServerPatch,
    OfficialMCPServerResponse,
)
from app.mcp.utils import probe_mcp_server
from app.service import BaseService


async def _build_oauth_provider(
    mcp_server: MCPServerDB,
    storage: RedisTokenStorage,
    repository: MCPServerRepository,
) -> WebOAuthClientProvider:
    """Build a WebOAuthClientProvider for an OAuth2 MCP server, loading and
    decrypting any stored static client credentials. Servers without stored
    credentials register dynamically (DCR) during the authorization flow."""
    client_metadata = build_oauth_client_metadata()
    oauth_credentials = await repository.get_oauth_credentials(mcp_server.id)
    client_id = client_secret = None
    if oauth_credentials:
        client_id = oauth_credentials.client_id
        client_secret = decrypt_api_key(oauth_credentials.client_secret_encrypted)
        client_metadata.token_endpoint_auth_method = (
            oauth_credentials.token_endpoint_auth_method or "client_secret_post"
        )
    return WebOAuthClientProvider(
        server_url=mcp_server.url,
        client_metadata=client_metadata,
        storage=storage,
        client_id=client_id,
        client_secret=client_secret,
    )


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

    async def list(self) -> list[MCPServerDB]:
        return await self.repository.list()

    async def update(self, server_id: UUID, data: MCPServerPatch) -> MCPServerDB:
        server = await self.get_or_404(server_id)
        return await self.repository.update(server, data)

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

        provider = await _build_oauth_provider(mcp_server, storage, self.repository)

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
        if server.auth_type == MCPAuthType.oauth2 and not await probe_mcp_server(
            server, user_id
        ):
            # Not connected: discover OAuth metadata and raise
            # OAuthAuthorizationRequired (translated globally to
            # 401 {oauth_required, auth_url}). No business tool is called.
            await self.initiate_oauth(server, user_id)

        async with connect_to_server(server, user_id, self.db) as (_, tools):
            return [
                {"name": tool.name, "description": tool.description} for tool in tools
            ]

    async def initiate_oauth(self, server: MCPServerDB, user_id: str) -> None:
        """Build the OAuth provider and start authorization via metadata
        discovery. Raises OAuthAuthorizationRequired with the authorize URL.

        Public: the run-start gate (`RunService`) calls this to surface an
        agent's (or subagent's) unauthorized server as a 401 before launching."""
        storage = TokenStorageFactory().get_storage(user_id, str(server.id))
        provider = await _build_oauth_provider(server, storage, self.repository)
        await provider.initiate_authorization()


# Safety bound for tools/list pagination. A well-behaved server eventually returns
# a falsy nextCursor; this caps a misbehaving one that emits endless new cursors.
MAX_TOOL_LIST_PAGES = 1000


async def _list_all_tools(session: ClientSession) -> list:
    """Page through ``tools/list``, guarding against a server that never ends
    pagination. A repeated or cyclic ``nextCursor`` is detected and a runaway page
    count is capped — otherwise the loop would spin forever, accumulating tools.
    """
    tools = []
    cursor: str | None = None
    seen_cursors: set[str] = set()
    for _ in range(MAX_TOOL_LIST_PAGES):
        response = await session.list_tools(cursor=cursor)
        tools.extend(response.tools)
        cursor = response.nextCursor
        if not cursor:
            return tools
        if cursor in seen_cursors:
            raise DomainError(
                "MCP server returned a repeated tools/list cursor; "
                "aborting to avoid an infinite pagination loop."
            )
        seen_cursors.add(cursor)
    raise DomainError(
        f"MCP server exceeded {MAX_TOOL_LIST_PAGES} tools/list pages; "
        "aborting to avoid an unbounded pagination loop."
    )


@asynccontextmanager
async def connect_to_server(
    mcp_server: MCPServerDB,
    user_id: str,
    db: AsyncSession,
    *,
    terminate_on_close: bool = True,
):
    """Connect to an MCP server and initialize session.

    Similar to the pattern from https://modelcontextprotocol.info/docs/tutorials/building-a-client/
    but adapted for web API context with proper resource management.

    Args:
        mcp_server: MCP server configuration
        user_id: The current user's ID
        db: Database session
        terminate_on_close: When False, the session is NOT DELETEd on exit and is
            left to expire by the server's TTL. MCP App paths need this because
            Metabase binds artifacts (the embedded ``sessionToken``) to the MCP
            session — DELETEing it kills the token before the browser uses it.

    Yields:
        tuple: (session, tools) - Initialized session and available tools

    Raises:
        OAuthAuthorizationRequired: If OAuth authorization is needed
    """
    repository = MCPServerRepository(db)
    storage = TokenStorageFactory().get_storage(user_id, str(mcp_server.id))

    if mcp_server.auth_type == MCPAuthType.oauth2:
        provider = await _build_oauth_provider(mcp_server, storage, repository)
        await provider.persist_client_info()
        client_args = {"url": mcp_server.url, "auth": provider}
    elif mcp_server.auth_type == MCPAuthType.api_key:
        api_key = await repository.get_api_key(mcp_server.id)
        client_args = {
            "url": mcp_server.url,
            "headers": {"Authorization": f"Bearer {api_key}"},
        }
    else:
        client_args = {"url": mcp_server.url}

    async with streamablehttp_client(
        **client_args, terminate_on_close=terminate_on_close
    ) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()

            try:
                tools = await _list_all_tools(session)
                yield session, tools
            except Exception as e:
                raise DomainError(str(e)) from e


def get_mcp_server_service(db: AsyncSession = Depends(get_db)) -> MCPServerService:
    return MCPServerService(db)
