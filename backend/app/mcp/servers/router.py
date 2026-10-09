from uuid import UUID

from fastapi import APIRouter, Depends, File, Header, Query, UploadFile
from fastapi.responses import JSONResponse, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.mcp_servers.service import (
    AgentMCPServerService,
    get_agent_mcp_server_service,
)
from app.auth.dependencies import get_current_user, require_admin
from app.database import get_db
from app.mcp.client.auth import oauth_callback_url
from app.mcp.client.connectivity import is_authorized, probe_candidate, test_connection
from app.mcp.servers.models import MCPServerDB
from app.mcp.servers.schemas import (
    AuthorizationRequired,
    ConnectionProbeRequest,
    ConnectionTestResult,
    ListToolsResult,
    MCPCatalogSyncResponse,
    MCPServerAgentResponse,
    MCPServerConnectionResponse,
    MCPServerCreate,
    MCPServerPatch,
    MCPServerResponse,
    OAuthCallbackInfo,
    OAuthSecretHint,
    OfficialMCPServerResponse,
    ToolsListed,
)
from app.mcp.servers.service import MCPServerService, get_mcp_server_service
from app.users.models import UserDB
from app.utils.images import image_response, process_uploaded_image


router = APIRouter(prefix="/mcp-servers", tags=["mcp-servers"])


async def get_mcp_server_dependency(
    server_id: UUID,
    current_user: UserDB = Depends(get_current_user),
    service: MCPServerService = Depends(get_mcp_server_service),
) -> MCPServerDB:
    return await service.get_visible(server_id, current_user)


@router.post("/", response_model=MCPServerResponse, status_code=201)
async def create_mcp_server(
    server: MCPServerCreate,
    current_user: UserDB = Depends(require_admin),
    service: MCPServerService = Depends(get_mcp_server_service),
) -> MCPServerResponse:
    created = await service.create(server, current_user.id)
    return await service.to_response(created)


@router.get("/", response_model=list[MCPServerResponse])
async def get_mcp_servers(
    current_user: UserDB = Depends(get_current_user),
    service: MCPServerService = Depends(get_mcp_server_service),
) -> list[MCPServerResponse]:
    return await service.list_responses(current_user)


@router.get("/official", response_model=list[OfficialMCPServerResponse])
async def get_official_mcp_servers(
    _current_user: UserDB = Depends(get_current_user),
    service: MCPServerService = Depends(get_mcp_server_service),
) -> list[OfficialMCPServerResponse]:
    return await service.list_official()


@router.post("/catalog/sync", response_model=MCPCatalogSyncResponse)
async def sync_official_catalog(
    _current_user: UserDB = Depends(require_admin),
    service: MCPServerService = Depends(get_mcp_server_service),
) -> MCPCatalogSyncResponse:
    """Force-fetch the CDN catalog now. Raises 400 (instead of silently falling
    back) when the fetch or validation fails — the admin pressed the button and
    needs to know."""
    return await service.sync_catalog()


@router.get("/oauth/callback-info", response_model=OAuthCallbackInfo)
async def get_oauth_callback_info(
    _current_user: UserDB = Depends(get_current_user),
) -> OAuthCallbackInfo:
    return OAuthCallbackInfo(callback_url=oauth_callback_url())


@router.get("/{server_id}", response_model=MCPServerResponse)
async def get_mcp_server(
    server_id: UUID,
    current_user: UserDB = Depends(get_current_user),
    service: MCPServerService = Depends(get_mcp_server_service),
) -> MCPServerResponse:
    server = await service.get_visible(server_id, current_user)
    return await service.to_response(server)


@router.get("/{server_id}/image", response_class=Response)
async def get_mcp_server_image(
    server_id: UUID,
    if_none_match: str | None = Header(default=None),
    current_user: UserDB = Depends(get_current_user),
    service: MCPServerService = Depends(get_mcp_server_service),
) -> Response:
    await service.get_visible(server_id, current_user)
    image = await service.get_image(server_id)
    return image_response(
        data=image.data,
        media_type=image.media_type,
        digest=image.sha256,
        if_none_match=if_none_match,
    )


@router.put("/{server_id}/image")
async def set_mcp_server_image(
    server_id: UUID,
    file: UploadFile = File(...),
    _current_user: UserDB = Depends(require_admin),
    service: MCPServerService = Depends(get_mcp_server_service),
) -> dict[str, UUID]:
    image = await process_uploaded_image(file)
    return {"image_revision": await service.set_image(server_id, image)}


@router.delete("/{server_id}/image", status_code=204)
async def delete_mcp_server_image(
    server_id: UUID,
    _current_user: UserDB = Depends(require_admin),
    service: MCPServerService = Depends(get_mcp_server_service),
) -> None:
    await service.delete_image(server_id)


@router.patch("/{server_id}", response_model=MCPServerResponse)
async def update_mcp_server(
    server_id: UUID,
    server_update: MCPServerPatch,
    _current_user: UserDB = Depends(require_admin),
    service: MCPServerService = Depends(get_mcp_server_service),
    db: AsyncSession = Depends(get_db),
) -> MCPServerResponse:
    before = await service.get_scoped_for_update(server_id)
    previous_auth_type = before.auth_type
    previous_url = before.url
    oauth_credentials_changed = bool(
        server_update.oauth_client_id
        or server_update.oauth_client_secret
        or server_update.oauth_token_endpoint_auth_method
    )
    updated = await service.update(server_id, server_update)
    # Commit before purging Redis: that side effect cannot be rolled back.
    await db.commit()
    await service.purge_invalidated_state(
        server_id,
        updated,
        previous_auth_type,
        previous_url,
        oauth_credentials_changed=oauth_credentials_changed,
    )
    return await service.to_response(updated)


@router.get("/{server_id}/oauth-secret-hint", response_model=OAuthSecretHint)
async def get_oauth_secret_hint(
    server_id: UUID,
    _current_user: UserDB = Depends(require_admin),
    service: MCPServerService = Depends(get_mcp_server_service),
) -> OAuthSecretHint:
    """Admin-only: a non-reversible hint (last 4 chars + length) about the
    stored OAuth client secret, so an admin editing the server can confirm which
    secret is set. The full secret is never returned."""
    return await service.get_oauth_secret_hint(server_id)


@router.get(
    "/{server_id}/agents",
    response_model=list[MCPServerAgentResponse],
    # In this order: the admin gate first, so a non-admin cannot tell an
    # existing server id from a missing one by 404 vs 403.
    dependencies=[Depends(require_admin), Depends(get_mcp_server_dependency)],
)
async def list_mcp_server_agents(
    server_id: UUID,
    bindings: AgentMCPServerService = Depends(get_agent_mcp_server_service),
) -> list[MCPServerAgentResponse]:
    return await bindings.list_agents_for_server(server_id)


@router.delete("/{server_id}", status_code=204)
async def delete_mcp_server(
    server_id: UUID,
    detach_agents: bool = False,
    _current_user: UserDB = Depends(require_admin),
    service: MCPServerService = Depends(get_mcp_server_service),
    bindings: AgentMCPServerService = Depends(get_agent_mcp_server_service),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Composes the two modules in the right direction: bindings belong to
    agents, so they are detached there; the server row is deleted here. Both
    run in the one request transaction, so a refused delete (still bound,
    no `detach_agents`) rolls the whole thing back."""
    if detach_agents:
        await bindings.detach_server(server_id)
    await service.delete(server_id)
    # Commit before purging Redis: the server deletion is the source of truth.
    await db.commit()
    await service.purge_server_data(server_id)


@router.post("/{server_id}/reset", status_code=200)
async def reset_mcp_server(
    server_id: UUID,
    _current_user: UserDB = Depends(require_admin),
    service: MCPServerService = Depends(get_mcp_server_service),
):
    """Reset all user connections for an MCP server.

    Clears all per-user OAuth tokens, client info, and metadata from Redis.
    """
    return await service.reset(server_id)


@router.get(
    "/{server_id}/connections", response_model=list[MCPServerConnectionResponse]
)
async def list_mcp_server_connections(
    server_id: UUID,
    _current_user: UserDB = Depends(require_admin),
    service: MCPServerService = Depends(get_mcp_server_service),
) -> list[MCPServerConnectionResponse]:
    """Admin-only: users holding a stored OAuth connection to this server."""
    return await service.list_connections(server_id)


@router.delete("/{server_id}/connections/{user_id}", status_code=200)
async def revoke_mcp_server_connection(
    server_id: UUID,
    user_id: UUID,
    _current_user: UserDB = Depends(require_admin),
    service: MCPServerService = Depends(get_mcp_server_service),
):
    """Admin-only: revoke one user's connection to this server.

    Clears the user's OAuth tokens, client info, and metadata from Redis;
    they will need to re-authenticate to use the server again.
    """
    return await service.delete_connection(server_id, user_id)


@router.get("/oauth/callback")
async def oauth_callback(
    code: str = Query(..., description="Authorization code from OAuth provider"),
    state: str = Query(..., description="State parameter from OAuth provider"),
    current_user: UserDB = Depends(get_current_user),
    service: MCPServerService = Depends(get_mcp_server_service),
):
    result = await service.handle_oauth_callback(code, state, current_user.id)
    return JSONResponse(status_code=200, content=result)


@router.get("/{server_id}/list-tools", response_model=ListToolsResult)
async def list_tools(
    mcp_server: MCPServerDB = Depends(get_mcp_server_dependency),
    current_user: UserDB = Depends(get_current_user),
    service: MCPServerService = Depends(get_mcp_server_service),
) -> ToolsListed | AuthorizationRequired:
    """List available tools from an MCP server.

    Returns a discriminated union on `status`: `ok` with the tools, or
    `auth_required` with the URL the user must open first — a 200 either way.
    An unconnected OAuth server is an expected answer here, not an error, and
    this is one of the few endpoints allowed to start an OAuth flow at all
    (design review §2.4).

    Goes through the MCP SDK transport (`ClientSession`). The raw-HTTP bypass
    this docstring used to describe was removed; the upstream GET-SSE deadlock it
    worked around is still unfixed in every released `mcp` SDK, so a POST-only
    server that holds the standalone GET stream can still wedge this call for
    ~15s. See `mcp-streamable-http-deadlock.md`.
    """
    return await service.list_tools(mcp_server, str(current_user.id))


@router.get("/{server_id}/is-connected")
async def is_connected(
    refresh: bool = Query(
        True, description="Attempt a token refresh when the stored token is expired"
    ),
    mcp_server: MCPServerDB = Depends(get_mcp_server_dependency),
    current_user: UserDB = Depends(get_current_user),
):
    """Whether the current user holds a usable credential for the server.

    OAuth servers count as connected when a token exists; with ``refresh=true``
    (the default) an expired-but-refreshable token is refreshed first. This is a
    credential check, not a handshake — use ``/test-connection`` to probe the
    server itself.
    """
    connected = await is_authorized(
        mcp_server,
        str(current_user.id),
        mcp_server.workspace_id,
        refresh=refresh,
    )
    return {"connected": connected}


@router.post("/test-connection", response_model=ConnectionTestResult)
async def test_connection_candidate(
    payload: ConnectionProbeRequest,
    _current_user: UserDB = Depends(require_admin),
) -> ConnectionTestResult:
    """Test candidate credentials without saving (create/edit form).

    Performs a real MCP handshake for ``none``/``api_key`` servers; OAuth can't
    be validated before saving (it is per-user and interactive).
    """
    return await probe_candidate(
        payload.url,
        payload.auth_type,
        api_key=payload.api_key,
        service_credential_provider=payload.service_credential_provider,
        service_credentials_json=payload.service_credentials_json,
        service_credential_scopes=payload.service_credential_scopes,
    )


@router.post("/{server_id}/test-connection", response_model=ConnectionTestResult)
async def test_saved_connection(
    mcp_server: MCPServerDB = Depends(get_mcp_server_dependency),
    current_user: UserDB = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ConnectionTestResult:
    """Test connectivity to a saved server as the current user.

    Returns discovered tools on success; an unauthorized OAuth server is
    reported as ``oauth_required`` with the ``auth_url`` to open, not a 401.
    """
    return await test_connection(
        mcp_server, str(current_user.id), mcp_server.workspace_id, db
    )
