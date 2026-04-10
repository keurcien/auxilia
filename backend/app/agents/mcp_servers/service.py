import logging
from uuid import UUID

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.agents.mcp_servers.repository import AgentMCPServerRepository
from app.agents.models import AgentMCPServerBase, AgentMCPServerDB
from app.agents.schemas import AgentMCPServerCreate, AgentMCPServerPatch
from app.database import get_db
from app.exceptions import NotFoundError
from app.mcp.client.auth import WebOAuthClientProvider, build_oauth_client_metadata
from app.mcp.client.storage import TokenStorageFactory
from app.mcp.servers.models import MCPAuthType, MCPServerDB
from app.mcp.servers.service import connect_to_server


logger = logging.getLogger(__name__)


class AgentMCPServerService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.repository = AgentMCPServerRepository(db)

    async def _check_oauth_connected(
        self, mcp_server: MCPServerDB, user_id: str
    ) -> bool:
        storage = TokenStorageFactory().get_storage(user_id, str(mcp_server.id))
        client_metadata = build_oauth_client_metadata(mcp_server)
        provider = WebOAuthClientProvider(
            server_url=mcp_server.url,
            client_metadata=client_metadata,
            storage=storage,
        )
        await provider._initialize()
        tokens = await provider.context.storage.get_tokens()
        return tokens is not None

    async def _fetch_and_save_tools(
        self,
        db_link: AgentMCPServerDB,
        mcp_server: MCPServerDB,
        user_id: str,
    ) -> None:
        try:
            async with connect_to_server(mcp_server, user_id, self.db) as (_, tools):
                tools_dict = {tool.name: "always_allow" for tool in tools}
                db_link.tools = tools_dict
                self.db.add(db_link)
                await self.db.commit()
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
        result = await self.db.execute(
            select(MCPServerDB).where(MCPServerDB.id == server_id)
        )
        mcp_server = result.scalar_one_or_none()
        if not mcp_server:
            raise NotFoundError("MCP server not found")

        existing = await self.repository.get(agent_id, server_id)

        if existing:
            if data.tools is not None:
                existing.tools = data.tools
                self.db.add(existing)
                await self.db.commit()
                await self.db.refresh(existing)
            return existing

        link_data = AgentMCPServerBase(
            agent_id=agent_id,
            mcp_server_id=server_id,
            tools=None,
        )
        db_link = await self.repository.create(link_data)
        await self.db.commit()

        if mcp_server.auth_type in [MCPAuthType.none, MCPAuthType.api_key]:
            await self._fetch_and_save_tools(db_link, mcp_server, user_id)
        elif mcp_server.auth_type == MCPAuthType.oauth2:
            is_connected = await self._check_oauth_connected(mcp_server, user_id)
            if is_connected:
                await self._fetch_and_save_tools(db_link, mcp_server, user_id)

        return db_link

    async def update(
        self, agent_id: UUID, server_id: UUID, data: AgentMCPServerPatch
    ) -> AgentMCPServerDB:
        link = await self.repository.get(agent_id, server_id)
        if not link:
            raise NotFoundError("Agent MCP server not found")

        if data.tools is not None:
            existing_tools = link.tools or {}
            merged_data = AgentMCPServerPatch(tools={**existing_tools, **data.tools})
        else:
            merged_data = data

        result = await self.repository.update(link, merged_data)
        await self.db.commit()
        return result

    async def delete(self, agent_id: UUID, server_id: UUID) -> None:
        link = await self.repository.get(agent_id, server_id)
        if not link:
            raise NotFoundError("Agent MCP server not found")
        await self.repository.delete(link)
        await self.db.commit()

    async def sync_tools(
        self, agent_id: UUID, server_id: UUID, user_id: str
    ) -> AgentMCPServerDB:
        result = await self.db.execute(
            select(MCPServerDB).where(MCPServerDB.id == server_id)
        )
        mcp_server = result.scalar_one_or_none()
        if not mcp_server:
            raise NotFoundError("MCP server not found")

        link = await self.repository.get(agent_id, server_id)
        if not link:
            raise NotFoundError("Agent MCP server not found")

        await self._fetch_and_save_tools(link, mcp_server, user_id)
        return link


def get_agent_mcp_server_service(db: AsyncSession = Depends(get_db)) -> AgentMCPServerService:
    return AgentMCPServerService(db)
