import logging
from uuid import UUID

from fastapi import Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.agents.mcp_servers.repository import MCPBindingRepository
from app.agents.models import (
    AgentMCPServerBindingCreate,
    AgentMCPServerBindingDB,
    AgentMCPServerBindingUpdate,
)
from app.database import get_db
from app.mcp.client.auth import WebOAuthClientProvider, build_oauth_client_metadata
from app.mcp.client.storage import TokenStorageFactory
from app.mcp.servers.models import MCPAuthType, MCPServerDB
from app.mcp.servers.service import connect_to_server


logger = logging.getLogger(__name__)


class MCPBindingService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.repository = MCPBindingRepository(db)

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
        db_binding: AgentMCPServerBindingDB,
        mcp_server: MCPServerDB,
        user_id: str,
    ) -> None:
        try:
            async with connect_to_server(mcp_server, user_id, self.db) as (_, tools):
                tools_dict = {tool.name: "always_allow" for tool in tools}
                db_binding.tools = tools_dict
                self.db.add(db_binding)
                await self.db.commit()
                await self.db.refresh(db_binding)
        except Exception as e:
            logger.warning(f"Failed to fetch tools for MCP server {mcp_server.id}: {e}")

    async def create_or_update_binding(
        self,
        agent_id: UUID,
        server_id: UUID,
        data: AgentMCPServerBindingCreate,
        user_id: str,
    ) -> AgentMCPServerBindingDB:
        result = await self.db.execute(
            select(MCPServerDB).where(MCPServerDB.id == server_id)
        )
        mcp_server = result.scalar_one_or_none()
        if not mcp_server:
            raise HTTPException(status_code=404, detail="MCP server not found")

        existing = await self.repository.get_binding(agent_id, server_id)

        if existing:
            if data.tools is not None:
                existing.tools = data.tools
                self.db.add(existing)
                await self.db.commit()
                await self.db.refresh(existing)
            return existing

        db_binding = await self.repository.create_binding(agent_id, server_id)

        if mcp_server.auth_type in [MCPAuthType.none, MCPAuthType.api_key]:
            await self._fetch_and_save_tools(db_binding, mcp_server, user_id)
        elif mcp_server.auth_type == MCPAuthType.oauth2:
            is_connected = await self._check_oauth_connected(mcp_server, user_id)
            if is_connected:
                await self._fetch_and_save_tools(db_binding, mcp_server, user_id)

        return db_binding

    async def update_binding(
        self, agent_id: UUID, server_id: UUID, data: AgentMCPServerBindingUpdate
    ) -> AgentMCPServerBindingDB:
        binding = await self.repository.get_binding(agent_id, server_id)
        if not binding:
            raise HTTPException(status_code=404, detail="Binding not found")

        update_data = data.model_dump(exclude_unset=True)

        if "tools" in update_data and update_data["tools"] is not None:
            existing_tools = binding.tools or {}
            merged_tools = {**existing_tools, **update_data["tools"]}
            update_data["tools"] = merged_tools

        return await self.repository.update_binding(binding, update_data)

    async def delete_binding(self, agent_id: UUID, server_id: UUID) -> None:
        binding = await self.repository.get_binding(agent_id, server_id)
        if not binding:
            raise HTTPException(status_code=404, detail="Binding not found")
        await self.repository.delete_binding(binding)

    async def sync_tools(
        self, agent_id: UUID, server_id: UUID, user_id: str
    ) -> AgentMCPServerBindingDB:
        result = await self.db.execute(
            select(MCPServerDB).where(MCPServerDB.id == server_id)
        )
        mcp_server = result.scalar_one_or_none()
        if not mcp_server:
            raise HTTPException(status_code=404, detail="MCP server not found")

        binding = await self.repository.get_binding(agent_id, server_id)
        if not binding:
            raise HTTPException(status_code=404, detail="Binding not found")

        await self._fetch_and_save_tools(binding, mcp_server, user_id)
        return binding


def get_mcp_binding_service(db: AsyncSession = Depends(get_db)) -> MCPBindingService:
    return MCPBindingService(db)
