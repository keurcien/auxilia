import logging
from collections import defaultdict
from uuid import UUID

from fastapi import Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.agents.core.repository import AgentRepository
from app.agents.models import (
    AgentCreate,
    AgentDB,
    AgentMCPServerDB,
    AgentMCPServerRead,
    AgentPermissionWrite,
    AgentRead,
    AgentUpdate,
    AgentUserPermissionDB,
)
from app.agents.subagents.service import SubagentService
from app.database import get_db
from app.mcp.servers.models import MCPServerDB
from app.mcp.utils import check_mcp_server_connected
from app.users.models import WorkspaceRole


logger = logging.getLogger(__name__)


class AgentService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.repository = AgentRepository(db)
        self.subagent_service = SubagentService(db)

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

    async def create_agent(self, data: AgentCreate) -> AgentDB:
        return await self.repository.create(data)

    async def get_agent(
        self,
        agent_id: UUID,
        user_id: UUID | None = None,
        user_role: WorkspaceRole | None = None,
        include_archived: bool = False,
    ) -> AgentRead:
        query = (
            select(AgentDB, AgentMCPServerDB)
            .outerjoin(
                AgentMCPServerDB, AgentDB.id == AgentMCPServerDB.agent_id
            )
            .where(AgentDB.id == agent_id)
        )
        if not include_archived:
            query = query.where(AgentDB.is_archived == False)  # noqa: E712
        result = await self.db.execute(query)
        rows = result.all()

        if not rows:
            raise HTTPException(status_code=404, detail="Agent not found")

        agent = rows[0][0]
        mcp_servers = [
            AgentMCPServerRead.model_validate(link)
            for _, link in rows
            if link is not None
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

        subagents = await self.subagent_service.load_subagents(agent_id)
        is_subagent = await self.subagent_service.repository.is_subagent(agent_id)

        return AgentRead(
            **agent.model_dump(),
            mcp_servers=mcp_servers,
            subagents=subagents,
            is_subagent=is_subagent,
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
                select(
                    AgentDB, AgentMCPServerDB, AgentUserPermissionDB.permission
                )
                .outerjoin(
                    AgentMCPServerDB,
                    AgentDB.id == AgentMCPServerDB.agent_id,
                )
                .outerjoin(
                    AgentUserPermissionDB,
                    (AgentDB.id == AgentUserPermissionDB.agent_id)
                    & (AgentUserPermissionDB.user_id == user_id),
                )
                .where(AgentDB.is_archived == False)  # noqa: E712
                .order_by(AgentDB.created_at.asc())
            )
        else:
            query = (
                select(AgentDB, AgentMCPServerDB)
                .outerjoin(
                    AgentMCPServerDB,
                    AgentDB.id == AgentMCPServerDB.agent_id,
                )
                .where(AgentDB.is_archived == False)  # noqa: E712
                .order_by(AgentDB.created_at.asc())
            )

        result = await self.db.execute(query)
        rows = result.all()

        agents_map: dict[UUID, AgentDB] = {}
        mcp_map: dict[UUID, list[AgentMCPServerRead]] = defaultdict(list)
        permissions_map: dict[UUID, str] = {}

        for row in rows:
            agent = row[0]
            link = row[1]
            agents_map[agent.id] = agent

            if link is not None:
                mcp_map[agent.id].append(
                    AgentMCPServerRead.model_validate(link)
                )

            if user_id and agent.owner_id == user_id:
                permissions_map[agent.id] = "owner"
            elif is_workspace_admin:
                permissions_map[agent.id] = "admin"
            elif user_id:
                permission = row[2]
                if permission and agent.id not in permissions_map:
                    permissions_map[agent.id] = permission.value

        agent_ids = list(agents_map.keys())
        subagents_map, is_subagent_ids = (
            await self.subagent_service.load_all_subagent_data(agent_ids)
        )

        return [
            AgentRead(
                **agent.model_dump(),
                mcp_servers=mcp_map.get(agent.id, []),
                subagents=subagents_map.get(agent.id, []),
                is_subagent=agent.id in is_subagent_ids,
                current_user_permission=permissions_map.get(agent.id),
            )
            for agent in agents_map.values()
        ]

    async def update_agent(
        self,
        agent_id: UUID,
        data: AgentUpdate,
        user_id: UUID | None = None,
        user_role: WorkspaceRole | None = None,
    ) -> AgentRead:
        agent = await self.repository.get(agent_id)
        if not agent:
            raise HTTPException(status_code=404, detail="Agent not found")
        update_data = data.model_dump(exclude_unset=True)
        await self.repository.update(agent, update_data)
        return await self.get_agent(agent_id, user_id=user_id, user_role=user_role)

    async def delete_agent(self, agent_id: UUID) -> None:
        agent = await self.repository.get(agent_id)
        if not agent:
            raise HTTPException(status_code=404, detail="Agent not found")
        await self.subagent_service.delete_all_for_agent(agent_id)
        await self.repository.archive(agent)

    async def get_permissions(self, agent_id: UUID) -> list[AgentUserPermissionDB]:
        return await self.repository.get_permissions(agent_id)

    async def set_permissions(
        self, agent_id: UUID, permissions: list[AgentPermissionWrite]
    ) -> list[AgentUserPermissionDB]:
        return await self.repository.set_permissions(agent_id, permissions)

    async def check_ready(self, agent_id: UUID, user_id: str) -> dict:
        agent = await self.get_agent(agent_id, include_archived=True)

        if not agent.mcp_servers:
            return {"ready": True, "disconnected_servers": [], "status": "ready"}

        for mcp_server in agent.mcp_servers:
            if mcp_server.tools is None:
                return {
                    "ready": False,
                    "disconnected_servers": [],
                    "status": "not_configured",
                }

        server_ids = [s.mcp_server_id for s in agent.mcp_servers]
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
