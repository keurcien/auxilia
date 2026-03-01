import logging
from collections import defaultdict
from uuid import UUID

from fastapi import Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.agents.models import (
    AgentCreate,
    AgentDB,
    AgentMCPServer,
    AgentMCPServerBindingCreate,
    AgentMCPServerBindingDB,
    AgentMCPServerBindingUpdate,
    AgentPermissionWrite,
    AgentRead,
    AgentUpdate,
    AgentUserPermissionDB,
)
from app.agents.repository import AgentRepository
from app.database import get_db
from app.mcp.client.auth import WebOAuthClientProvider, build_oauth_client_metadata
from app.mcp.client.storage import TokenStorageFactory
from app.mcp.servers.models import MCPAuthType, MCPServerDB
from app.mcp.servers.service import connect_to_server
from app.mcp.utils import check_mcp_server_connected
from app.users.models import WorkspaceRole

logger = logging.getLogger(__name__)


class AgentService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.repository = AgentRepository(db)

    def _resolve_permission(
        self,
        agent: AgentDB,
        user_id: UUID | None,
        user_role: WorkspaceRole | None,
        granted_permissions: dict[UUID, str],
    ) -> str | None:
        if user_id and agent.owner_id == user_id:
            return "owner"
        if user_role == WorkspaceRole.admin:
            return "admin"
        return granted_permissions.get(agent.id)

    async def _check_oauth_connected(self, mcp_server: MCPServerDB, user_id: str) -> bool:
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

    async def create_agent(self, data: AgentCreate) -> AgentDB:
        return await self.repository.create(data)

    async def get_agent(
        self,
        agent_id: UUID,
        user_id: UUID | None = None,
        user_role: WorkspaceRole | None = None,
    ) -> AgentRead:
        result = await self.db.execute(
            select(AgentDB, AgentMCPServerBindingDB)
            .outerjoin(AgentMCPServerBindingDB, AgentDB.id == AgentMCPServerBindingDB.agent_id)
            .where(AgentDB.id == agent_id)
        )
        rows = result.all()

        if not rows:
            raise HTTPException(status_code=404, detail="Agent not found")

        agent = rows[0][0]
        mcp_servers = [
            AgentMCPServer(id=binding.mcp_server_id, tools=binding.tools)
            for _, binding in rows
            if binding is not None
        ]

        current_user_permission = None
        if user_id and agent.owner_id == user_id:
            current_user_permission = "owner"
        elif user_role == WorkspaceRole.admin:
            current_user_permission = "admin"
        elif user_id:
            perm_result = await self.db.execute(
                select(AgentUserPermissionDB.permission).where(
                    AgentUserPermissionDB.agent_id == agent_id,
                    AgentUserPermissionDB.user_id == user_id,
                )
            )
            perm = perm_result.scalar_one_or_none()
            if perm:
                current_user_permission = perm.value

        return AgentRead(
            **agent.model_dump(),
            mcp_servers=mcp_servers,
            current_user_permission=current_user_permission,
        )

    async def list_agents(
        self,
        user_id: UUID | None = None,
        user_role: WorkspaceRole | None = None,
    ) -> list[AgentRead]:
        is_workspace_admin = user_role == WorkspaceRole.admin

        if user_id and not is_workspace_admin:
            query = (
                select(AgentDB, AgentMCPServerBindingDB, AgentUserPermissionDB.permission)
                .outerjoin(
                    AgentMCPServerBindingDB, AgentDB.id == AgentMCPServerBindingDB.agent_id
                )
                .outerjoin(
                    AgentUserPermissionDB,
                    (AgentDB.id == AgentUserPermissionDB.agent_id)
                    & (AgentUserPermissionDB.user_id == user_id),
                )
                .order_by(AgentDB.created_at.asc())
            )
        else:
            query = (
                select(AgentDB, AgentMCPServerBindingDB)
                .outerjoin(
                    AgentMCPServerBindingDB, AgentDB.id == AgentMCPServerBindingDB.agent_id
                )
                .order_by(AgentDB.created_at.asc())
            )

        result = await self.db.execute(query)
        rows = result.all()

        agents_map: dict[UUID, AgentDB] = {}
        bindings_map: dict[UUID, list[AgentMCPServer]] = defaultdict(list)
        permissions_map: dict[UUID, str] = {}

        for row in rows:
            agent = row[0]
            binding = row[1]
            agents_map[agent.id] = agent

            if binding is not None:
                bindings_map[agent.id].append(
                    AgentMCPServer(id=binding.mcp_server_id, tools=binding.tools)
                )

            if user_id and agent.owner_id == user_id:
                permissions_map[agent.id] = "owner"
            elif is_workspace_admin:
                permissions_map[agent.id] = "admin"
            elif user_id:
                permission = row[2]
                if permission and agent.id not in permissions_map:
                    permissions_map[agent.id] = permission.value

        return [
            AgentRead(
                **agent.model_dump(),
                mcp_servers=bindings_map.get(agent.id, []),
                current_user_permission=permissions_map.get(agent.id),
            )
            for agent in agents_map.values()
        ]

    async def update_agent(self, agent_id: UUID, data: AgentUpdate) -> AgentDB:
        agent = await self.repository.get(agent_id)
        if not agent:
            raise HTTPException(status_code=404, detail="Agent not found")
        update_data = data.model_dump(exclude_unset=True)
        return await self.repository.update(agent, update_data)

    async def delete_agent(self, agent_id: UUID) -> None:
        agent = await self.repository.get(agent_id)
        if not agent:
            raise HTTPException(status_code=404, detail="Agent not found")
        await self.repository.delete(agent)

    async def get_permissions(self, agent_id: UUID) -> list[AgentUserPermissionDB]:
        return await self.repository.get_permissions(agent_id)

    async def set_permissions(
        self, agent_id: UUID, permissions: list[AgentPermissionWrite]
    ) -> list[AgentUserPermissionDB]:
        return await self.repository.set_permissions(agent_id, permissions)

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

    async def check_ready(self, agent_id: UUID, user_id: str) -> dict:
        agent = await self.get_agent(agent_id)

        if not agent.mcp_servers:
            return {"ready": True, "disconnected_servers": [], "status": "ready"}

        for mcp_server in agent.mcp_servers:
            if mcp_server.tools is None:
                return {"ready": False, "disconnected_servers": [], "status": "not_configured"}

        server_ids = [s.id for s in agent.mcp_servers]
        result = await self.db.execute(
            select(MCPServerDB).where(MCPServerDB.id.in_(server_ids))
        )
        servers = list(result.scalars().all())

        disconnected = []
        for server in servers:
            connected = await check_mcp_server_connected(server, user_id)
            if not connected:
                disconnected.append(str(server.id))

        return {
            "ready": len(disconnected) == 0,
            "disconnected_servers": disconnected,
            "status": "disconnected",
        }


def get_agent_service(db: AsyncSession = Depends(get_db)) -> AgentService:
    return AgentService(db)
