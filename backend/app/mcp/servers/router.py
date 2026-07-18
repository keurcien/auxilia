from uuid import UUID

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user, require_admin
from app.database import get_db
from app.mcp.client.connectivity import is_authorized, probe_candidate, test_connection
from app.mcp.servers.models import MCPServerDB
from app.mcp.servers.schemas import (
    ConnectionProbeRequest,
    ConnectionTestResult,
    MCPServerCreate,
    MCPServerPatch,
    MCPServerResponse,
    OAuthSecretHint,
    OfficialMCPServerResponse,
)
from app.mcp.servers.service import MCPServerService, get_mcp_server_service
from app.users.models import UserDB


router = APIRouter(prefix="/mcp-servers", tags=["mcp-servers"])


async def get_mcp_server_dependency(
    server_id: UUID,
    service: MCPServerService = Depends(get_mcp_server_service),
) -> MCPServerDB:
    return await service.get(server_id)


@router.post("/", response_model=MCPServerResponse, status_code=201)
async def create_mcp_server(
    server: MCPServerCreate,
    _current_user: UserDB = Depends(require_admin),
    service: MCPServerService = Depends(get_mcp_server_service),
) -> MCPServerResponse:
    created = await service.create(server)
    return await service.to_response(created)


@router.get("/", response_model=list[MCPServerResponse])
async def get_mcp_servers(
    _current_user: UserDB = Depends(get_current_user),
    service: MCPServerService = Depends(get_mcp_server_service),
) -> list[MCPServerResponse]:
    return await service.list_responses()


@router.get("/official", response_model=list[OfficialMCPServerResponse])
async def get_official_mcp_servers(
    _current_user: UserDB = Depends(get_current_user),
    service: MCPServerService = Depends(get_mcp_server_service),
) -> list[OfficialMCPServerResponse]:
    return await service.list_official()


@router.get("/{server_id}", response_model=MCPServerResponse)
async def get_mcp_server(
    server_id: UUID,
    _current_user: UserDB = Depends(get_current_user),
    service: MCPServerService = Depends(get_mcp_server_service),
) -> MCPServerResponse:
    server = await service.get(server_id)
    return await service.to_response(server)


@router.patch("/{server_id}", response_model=MCPServerResponse)
async def update_mcp_server(
    server_id: UUID,
    server_update: MCPServerPatch,
    _current_user: UserDB = Depends(require_admin),
    service: MCPServerService = Depends(get_mcp_server_service),
) -> MCPServerResponse:
    updated = await service.update(server_id, server_update)
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


@router.delete("/{server_id}", status_code=204)
async def delete_mcp_server(
    server_id: UUID,
    _current_user: UserDB = Depends(require_admin),
    service: MCPServerService = Depends(get_mcp_server_service),
) -> None:
    await service.delete(server_id)


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


@router.get("/oauth/callback")
async def oauth_callback(
    code: str = Query(..., description="Authorization code from OAuth provider"),
    state: str = Query(..., description="State parameter from OAuth provider"),
    service: MCPServerService = Depends(get_mcp_server_service),
):
    result = await service.handle_oauth_callback(code, state)
    return JSONResponse(status_code=200, content=result)


@router.get("/{server_id}/list-tools")
async def list_tools(
    mcp_server: MCPServerDB = Depends(get_mcp_server_dependency),
    current_user: UserDB = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List available tools from an MCP server.

    Uses raw HTTP (no GET SSE stream) to avoid the 15-second deadlock on
    servers that return 202 Accepted for tools/list and only deliver the
    result once the GET stream is open.
    """
    return await MCPServerService(db).list_tools(mcp_server, str(current_user.id))


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
    connected = await is_authorized(mcp_server, str(current_user.id), refresh=refresh)
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
        payload.url, payload.auth_type, api_key=payload.api_key
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
    return await test_connection(mcp_server, str(current_user.id), db)
