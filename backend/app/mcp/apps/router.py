import asyncio
import logging
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import SQLModel, select

from app.agents.models import AgentDB, AgentMCPServerBindingDB
from app.auth.dependencies import get_current_user
from app.database import AsyncSessionLocal, get_db
from app.mcp.servers.models import MCPServerDB
from app.mcp.servers.router import connect_to_server
from app.users.models import UserDB

logger = logging.getLogger(__name__)

router = APIRouter(tags=["mcp-apps"])


class MCPAppToolRead(SQLModel):
    server_name: str
    tool_name: str
    resource_uri: str
    server_id: UUID


class MCPAppReadResourceRequest(SQLModel):
    uri: str


class MCPAppCallToolRequest(SQLModel):
    tool_name: str
    arguments: dict[str, Any] | None = None


async def get_agent_or_404(agent_id: UUID, db: AsyncSession) -> AgentDB:
    result = await db.execute(select(AgentDB).where(AgentDB.id == agent_id))
    agent = result.scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    return agent


async def get_server_or_404(server_id: UUID, db: AsyncSession) -> MCPServerDB:
    result = await db.execute(select(MCPServerDB).where(MCPServerDB.id == server_id))
    server = result.scalar_one_or_none()
    if not server:
        raise HTTPException(status_code=404, detail="MCP server not found")
    return server


def get_tool_resource_uri(tool: Any) -> str | None:
    tool_meta = getattr(tool, "meta", None)
    if not isinstance(tool_meta, dict):
        return None

    ui_meta = tool_meta.get("ui")
    if not isinstance(ui_meta, dict):
        ui_meta = tool_meta.get("io.modelcontextprotocol/ui")
        if not isinstance(ui_meta, dict):
            return None

    resource_uri = ui_meta.get("resourceUri")
    if isinstance(resource_uri, str):
        cleaned_uri = resource_uri.strip()
        return cleaned_uri if cleaned_uri else None

    return None


async def list_server_mcp_app_tools(
    mcp_server: MCPServerDB,
    user_id: str,
) -> list[MCPAppToolRead]:
    try:
        async with AsyncSessionLocal() as server_db:
            async with connect_to_server(mcp_server, user_id, server_db) as (_, tools):
                mcp_app_tools: list[MCPAppToolRead] = []
                for tool in tools:
                    resource_uri = get_tool_resource_uri(tool)
                    if not resource_uri:
                        continue

                    mcp_app_tools.append(
                        MCPAppToolRead(
                            server_name=mcp_server.name,
                            tool_name=tool.name,
                            resource_uri=resource_uri,
                            server_id=mcp_server.id,
                        )
                    )

                return mcp_app_tools
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "Failed to list MCP app tools for server %s: %s", mcp_server.id, exc
        )
        return []


@router.get("/agents/{agent_id}/mcp-app-tools", response_model=list[MCPAppToolRead])
async def get_mcp_app_tools(
    agent_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: UserDB = Depends(get_current_user),
) -> list[MCPAppToolRead]:
    await get_agent_or_404(agent_id, db)

    result = await db.execute(
        select(MCPServerDB)
        .join(
            AgentMCPServerBindingDB,
            MCPServerDB.id == AgentMCPServerBindingDB.mcp_server_id,
        )
        .where(AgentMCPServerBindingDB.agent_id == agent_id)
        .order_by(MCPServerDB.created_at.asc())
    )
    servers = result.scalars().all()
    if not servers:
        return []

    discovered_tools = await asyncio.gather(
        *[
            list_server_mcp_app_tools(server, str(current_user.id))
            for server in servers
        ]
    )
    return [tool for server_tools in discovered_tools for tool in server_tools]


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
