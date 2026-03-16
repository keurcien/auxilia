from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import SQLModel, select

from app.auth.dependencies import get_current_user
from app.database import get_db
from app.mcp.servers.models import MCPServerDB
from app.mcp.servers.service import connect_to_server
from app.users.models import UserDB


router = APIRouter(tags=["mcp-apps"])


class MCPAppReadResourceRequest(SQLModel):
    uri: str


class MCPAppCallToolRequest(SQLModel):
    tool_name: str
    arguments: dict[str, Any] | None = None


def _to_mcp_app_proxy_error(action: str, exc: Exception) -> HTTPException:
    message = str(exc).strip() or "Unknown MCP error"
    lowered_message = message.lower()

    client_error_markers = (
        "unknown tool",
        "tool not found",
        "unknown resource",
        "resource not found",
        "invalid params",
        "invalid argument",
    )
    status_code = (
        400
        if any(marker in lowered_message for marker in client_error_markers)
        else 502
    )
    return HTTPException(
        status_code=status_code,
        detail=f"MCP app {action} failed: {message}",
    )


async def get_server_or_404(server_id: UUID, db: AsyncSession) -> MCPServerDB:
    result = await db.execute(select(MCPServerDB).where(MCPServerDB.id == server_id))
    server = result.scalar_one_or_none()
    if not server:
        raise HTTPException(status_code=404, detail="MCP server not found")
    return server


@router.post("/mcp-servers/{server_id}/app/read-resource")
async def read_mcp_app_resource(
    server_id: UUID,
    body: MCPAppReadResourceRequest,
    db: AsyncSession = Depends(get_db),
    current_user: UserDB = Depends(get_current_user),
):
    mcp_server = await get_server_or_404(server_id, db)
    async with connect_to_server(mcp_server, str(current_user.id), db) as (session, _):
        try:
            return await session.read_resource(body.uri)
        except HTTPException:
            raise
        except Exception as exc:
            raise _to_mcp_app_proxy_error("read-resource", exc) from exc


@router.post("/mcp-servers/{server_id}/app/call-tool")
async def call_mcp_app_tool(
    server_id: UUID,
    body: MCPAppCallToolRequest,
    db: AsyncSession = Depends(get_db),
    current_user: UserDB = Depends(get_current_user),
):
    mcp_server = await get_server_or_404(server_id, db)
    async with connect_to_server(mcp_server, str(current_user.id), db) as (session, _):
        try:
            return await session.call_tool(body.tool_name, body.arguments)
        except HTTPException:
            raise
        except Exception as exc:
            raise _to_mcp_app_proxy_error("call-tool", exc) from exc
