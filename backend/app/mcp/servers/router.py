from uuid import UUID

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user, require_admin
from app.database import get_db
from app.mcp.servers.models import (
    MCPServerCreate,
    MCPServerDB,
    MCPServerRead,
    MCPServerUpdate,
    OfficialMCPServerRead,
)
from app.mcp.servers.repository import MCPServerRepository
from app.mcp.servers.service import MCPServerService
from app.users.models import UserDB

router = APIRouter(prefix="/mcp-servers", tags=["mcp-servers"])


async def get_mcp_server_dependency(
    mcp_server_id: str, db: AsyncSession = Depends(get_db)
) -> MCPServerDB:
    return await MCPServerRepository(db).get(mcp_server_id)


@router.post("/", response_model=MCPServerRead, status_code=201)
async def create_mcp_server(
    server: MCPServerCreate,
    _current_user: UserDB = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> MCPServerRead:
    return await MCPServerService(db).create_server(server)


@router.get("/", response_model=list[MCPServerRead])
async def get_mcp_servers(
    _current_user: UserDB = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[MCPServerRead]:
    return await MCPServerService(db).list_servers()


@router.get("/official", response_model=list[OfficialMCPServerRead])
async def get_official_mcp_servers(
    _current_user: UserDB = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[OfficialMCPServerRead]:
    return await MCPServerService(db).list_official_servers()


@router.get("/{server_id}", response_model=MCPServerRead)
async def get_mcp_server(
    server_id: UUID,
    _current_user: UserDB = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> MCPServerRead:
    return await MCPServerService(db).get_server(server_id)


@router.patch("/{server_id}", response_model=MCPServerRead)
async def update_mcp_server(
    server_id: UUID,
    server_update: MCPServerUpdate,
    _current_user: UserDB = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> MCPServerRead:
    return await MCPServerService(db).update_server(server_id, server_update)


@router.delete("/{server_id}", status_code=204)
async def delete_mcp_server(
    server_id: UUID,
    _current_user: UserDB = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> None:
    await MCPServerService(db).delete_server(server_id)


@router.post("/{server_id}/reset", status_code=200)
async def reset_mcp_server(
    server_id: UUID,
    _current_user: UserDB = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Reset all user connections for an MCP server.

    Clears all per-user OAuth tokens, client info, and metadata from Redis.
    """
    return await MCPServerService(db).reset_server(server_id)


@router.get("/oauth/callback")
async def oauth_callback(
    code: str = Query(..., description="Authorization code from OAuth provider"),
    state: str = Query(..., description="State parameter from OAuth provider"),
    db: AsyncSession = Depends(get_db),
):
    result = await MCPServerService(db).handle_oauth_callback(code, state)
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
    """Check if an MCP server is connected.

    Returns True if:
    - The MCP server does not require OAuth, OR
    - The MCP server requires OAuth and a valid token is available in storage

    Returns False if:
    - The MCP server requires OAuth but no token is available
    """
    connected = await MCPServerService(None).check_connectivity(mcp_server, str(current_user.id))
    return {"connected": connected}


@router.get("/{mcp_server_id}/is-connected-v2")
async def is_connected_v2(
    mcp_server: MCPServerDB = Depends(get_mcp_server_dependency),
    current_user: UserDB = Depends(get_current_user),
):
    """Check if an MCP server is connected, with token validation and refresh.

    Returns True if:
    - The MCP server does not require OAuth, OR
    - The MCP server requires OAuth and the token is not expired, OR
    - The MCP server requires OAuth, the token is expired, but refresh succeeds

    Returns False if:
    - No tokens are available
    - Token is expired and refresh fails
    """
    connected = await MCPServerService(None).check_connectivity_with_refresh(
        mcp_server, str(current_user.id)
    )
    return {"connected": connected}
