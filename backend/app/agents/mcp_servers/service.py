import logging
from uuid import UUID

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.mcp_servers.repository import AgentMCPServerRepository
from app.agents.models import AgentMCPServerBase, AgentMCPServerDB
from app.agents.schemas import AgentMCPServerCreate, AgentMCPServerPatch
from app.database import get_db
from app.exceptions import NotFoundError
from app.mcp.client.connectivity import check_oauth_connected
from app.mcp.servers.models import MCPAuthType, MCPServerDB
from app.mcp.servers.repository import MCPServerRepository
from app.mcp.servers.service import connect_to_server
from app.service import BaseService


logger = logging.getLogger(__name__)


class AgentMCPServerService(
    BaseService[AgentMCPServerDB, AgentMCPServerRepository]
):
    not_found_message = "Agent MCP server not found"

    def __init__(self, db: AsyncSession):
        super().__init__(db, AgentMCPServerRepository(db))
        self._servers = MCPServerRepository(db)

    async def _require_server(self, server_id: UUID) -> MCPServerDB:
        server = await self._servers.get(server_id)
        if not server:
            raise NotFoundError("MCP server not found")
        return server

    async def _fetch_and_save_tools(
        self,
        db_link: AgentMCPServerDB,
        mcp_server: MCPServerDB,
        user_id: str,
    ) -> None:
        try:
            async with connect_to_server(mcp_server, user_id, self.db) as (_, tools):
                db_link.tools = {tool.name: "always_allow" for tool in tools}
                self.db.add(db_link)
                await self.db.flush()
                await self.db.refresh(db_link)
        except Exception as e:
            logger.warning(f"Failed to fetch tools for MCP server {mcp_server.id}: {e}")

    async def create_or_update(
        self,
        agent_id: UUID,
        server_id: UUID,
        data: AgentMCPServerCreate,
        user_id: str,
    ) -> AgentMCPServerDB:
        mcp_server = await self._require_server(server_id)

        existing = await self.repository.get(agent_id, server_id)
        if existing:
            if data.tools is not None:
                existing.tools = data.tools
                self.db.add(existing)
                await self.db.flush()
                await self.db.refresh(existing)
            return existing

        db_link = await self.repository.create(
            AgentMCPServerBase(
                agent_id=agent_id,
                mcp_server_id=server_id,
                tools=None,
            )
        )

        should_fetch = mcp_server.auth_type in (
            MCPAuthType.none,
            MCPAuthType.api_key,
        ) or (
            mcp_server.auth_type == MCPAuthType.oauth2
            and await check_oauth_connected(mcp_server, user_id)
        )
        if should_fetch:
            await self._fetch_and_save_tools(db_link, mcp_server, user_id)

        return db_link

    async def update(
        self, agent_id: UUID, server_id: UUID, data: AgentMCPServerPatch
    ) -> AgentMCPServerDB:
        link = await self.repository.get(agent_id, server_id)
        if not link:
            raise NotFoundError(self.not_found_message)

        if data.tools is not None:
            existing_tools = link.tools or {}
            data = AgentMCPServerPatch(tools={**existing_tools, **data.tools})

        return await self.repository.update(link, data)

    async def delete(self, agent_id: UUID, server_id: UUID) -> None:
        link = await self.repository.get(agent_id, server_id)
        if not link:
            raise NotFoundError(self.not_found_message)
        await self.repository.delete(link)

    async def sync_tools(
        self, agent_id: UUID, server_id: UUID, user_id: str
    ) -> AgentMCPServerDB:
        mcp_server = await self._require_server(server_id)
        link = await self.repository.get(agent_id, server_id)
        if not link:
            raise NotFoundError(self.not_found_message)
        await self._fetch_and_save_tools(link, mcp_server, user_id)
        return link


def get_agent_mcp_server_service(
    db: AsyncSession = Depends(get_db),
) -> AgentMCPServerService:
    return AgentMCPServerService(db)
