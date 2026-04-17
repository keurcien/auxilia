from uuid import UUID

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user, require_admin
from app.database import get_db
from app.mcp.client.connectivity import (
    check_connectivity,
    check_connectivity_with_refresh,
)
from app.mcp.servers.models import MCPServerDB
from app.mcp.servers.schemas import (
    MCPServerCreate,
    MCPServerPatch,
    MCPServerResponse,
    OfficialMCPServerResponse,
)
from app.mcp.servers.service import MCPServerService, get_mcp_server_service
from app.users.models import UserDB


router = APIRouter(prefix="/mcp-servers", tags=["mcp-servers"])


async def get_mcp_server_dependency(
    mcp_server_id: UUID,
    service: MCPServerService = Depends(get_mcp_server_service),
) -> MCPServerDB:
    return await service.get_server(mcp_server_id)


@router.post("/", response_model=MCPServerResponse, status_code=201)
async def create_mcp_server(
    server: MCPServerCreate,
    _current_user: UserDB = Depends(require_admin),
    service: MCPServerService = Depends(get_mcp_server_service),
) -> MCPServerResponse:
    return await service.create_server(server)


@router.get("/", response_model=list[MCPServerResponse])
async def get_mcp_servers(
    _current_user: UserDB = Depends(get_current_user),
    service: MCPServerService = Depends(get_mcp_server_service),
) -> list[MCPServerResponse]:
    return await service.list_servers()


@router.get("/official", response_model=list[OfficialMCPServerResponse])
async def get_official_mcp_servers(
    _current_user: UserDB = Depends(get_current_user),
    service: MCPServerService = Depends(get_mcp_server_service),
) -> list[OfficialMCPServerResponse]:
    return await service.list_official_servers()


@router.get("/{server_id}", response_model=MCPServerResponse)
async def get_mcp_server(
    server_id: UUID,
    _current_user: UserDB = Depends(get_current_user),
    service: MCPServerService = Depends(get_mcp_server_service),
) -> MCPServerResponse:
    return await service.get_server(server_id)


@router.patch("/{server_id}", response_model=MCPServerResponse)
async def update_mcp_server(
    server_id: UUID,
    server_update: MCPServerPatch,
    _current_user: UserDB = Depends(require_admin),
    service: MCPServerService = Depends(get_mcp_server_service),
) -> MCPServerResponse:
    return await service.update_server(server_id, server_update)


@router.delete("/{server_id}", status_code=204)
async def delete_mcp_server(
    server_id: UUID,
    _current_user: UserDB = Depends(require_admin),
    service: MCPServerService = Depends(get_mcp_server_service),
) -> None:
    await service.delete_server(server_id)


@router.post("/{server_id}/reset", status_code=200)
async def reset_mcp_server(
    server_id: UUID,
    _current_user: UserDB = Depends(require_admin),
    service: MCPServerService = Depends(get_mcp_server_service),
):
    """Reset all user connections for an MCP server.

    Clears all per-user OAuth tokens, client info, and metadata from Redis.
    """
    return await service.reset_server(server_id)


@router.get("/oauth/callback")
async def oauth_callback(
    code: str = Query(..., description="Authorization code from OAuth provider"),
    state: str = Query(..., description="State parameter from OAuth provider"),
    service: MCPServerService = Depends(get_mcp_server_service),
):
    result = await service.handle_oauth_callback(code, state)
    return JSONResponse(status_code=200, content=result)


@router.get("/{mcp_server_id}/list-tools")
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


@router.get("/{mcp_server_id}/is-connected")
async def is_connected(
    mcp_server: MCPServerDB = Depends(get_mcp_server_dependency),
    current_user: UserDB = Depends(get_current_user),
):
    connected = await check_connectivity(mcp_server, str(current_user.id))
    return {"connected": connected}


@router.get("/{mcp_server_id}/is-connected-v2")
async def is_connected_v2(
    mcp_server: MCPServerDB = Depends(get_mcp_server_dependency),
    current_user: UserDB = Depends(get_current_user),
):
    connected = await check_connectivity_with_refresh(
        mcp_server, str(current_user.id)
    )
    return {"connected": connected}
