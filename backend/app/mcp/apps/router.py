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
        return await session.read_resource(body.uri)


@router.post("/mcp-servers/{server_id}/app/call-tool")
async def call_mcp_app_tool(
    server_id: UUID,
    body: MCPAppCallToolRequest,
    db: AsyncSession = Depends(get_db),
    current_user: UserDB = Depends(get_current_user),
):
    mcp_server = await get_server_or_404(server_id, db)
    async with connect_to_server(mcp_server, str(current_user.id), db) as (session, _):
        return await session.call_tool(body.tool_name, body.arguments)
