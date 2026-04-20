import logging
from collections import defaultdict
from uuid import UUID

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.agents.core.repository import AgentRepository
from app.agents.models import (
    AgentDB,
    AgentUserPermissionDB,
)
from app.agents.schemas import (
    AgentCreateDB,
    AgentMCPServerResponse,
    AgentPatch,
    AgentPermissionCreate,
    AgentResponse,
)
from app.agents.subagents.service import SubagentService
from app.database import get_db
from app.exceptions import NotFoundError
from app.mcp.servers.models import MCPServerDB
from app.mcp.utils import check_mcp_server_connected
from app.service import BaseService
from app.users.models import WorkspaceRole


logger = logging.getLogger(__name__)


class AgentService(BaseService[AgentDB, AgentRepository]):
    not_found_message = "Agent not found"

    def __init__(self, db: AsyncSession):
        super().__init__(db, AgentRepository(db))
        self.subagent_service = SubagentService(db)

    @staticmethod
    def _resolve_permission(
        agent: AgentDB,
        user_id: UUID | None,
        user_role: WorkspaceRole | None,
        granted: dict[UUID, str],
    ) -> str | None:
        if user_id and agent.owner_id == user_id:
            return "owner"
        if user_role == WorkspaceRole.admin:
            return "admin"
        return granted.get(agent.id)

    async def _assemble(
        self,
        agents: list[AgentDB],
        mcp_map: dict[UUID, list[AgentMCPServerResponse]],
        permissions_map: dict[UUID, str],
        user_id: UUID | None,
        user_role: WorkspaceRole | None,
    ) -> list[AgentResponse]:
        agent_ids = [a.id for a in agents]
        subagents_map, is_subagent_ids = (
            await self.subagent_service.load_all_subagent_data(agent_ids)
        )
        return [
            AgentResponse(
                **agent.model_dump(),
                mcp_servers=mcp_map.get(agent.id, []),
                subagents=subagents_map.get(agent.id, []),
                is_subagent=agent.id in is_subagent_ids,
                current_user_permission=self._resolve_permission(
                    agent, user_id, user_role, permissions_map
                ),
            )
            for agent in agents
        ]

    @staticmethod
    def _group_rows(
        rows: list,
        user_id: UUID | None,
    ) -> tuple[
        dict[UUID, AgentDB],
        dict[UUID, list[AgentMCPServerResponse]],
        dict[UUID, str],
    ]:
        agents_map: dict[UUID, AgentDB] = {}
        mcp_map: dict[UUID, list[AgentMCPServerResponse]] = defaultdict(list)
        permissions_map: dict[UUID, str] = {}
        for row in rows:
            agent = row[0]
            link = row[1]
            agents_map[agent.id] = agent
            if link is not None:
                mcp_map[agent.id].append(AgentMCPServerResponse.model_validate(link))
            if user_id and len(row) > 2:
                permission = row[2]
                if permission and agent.id not in permissions_map:
                    permissions_map[agent.id] = permission.value
        return agents_map, mcp_map, permissions_map

    async def create_agent(self, data: AgentCreateDB) -> AgentDB:
        return await self.repository.create(data)

    async def get_agent(
        self,
        agent_id: UUID,
        user_id: UUID | None = None,
        user_role: WorkspaceRole | None = None,
        include_archived: bool = False,
    ) -> AgentResponse:
        rows = await self.repository.list_with_permissions(
            user_id=user_id,
            user_role=user_role,
            agent_id=agent_id,
            include_archived=include_archived,
        )
        if not rows:
            raise NotFoundError(self.not_found_message)

        agents_map, mcp_map, permissions_map = self._group_rows(rows, user_id)
        responses = await self._assemble(
            list(agents_map.values()),
            mcp_map,
            permissions_map,
            user_id,
            user_role,
        )
        return responses[0]

    async def list_agents(
        self,
        user_id: UUID | None = None,
        user_role: WorkspaceRole | None = None,
    ) -> list[AgentResponse]:
        rows = await self.repository.list_with_permissions(
            user_id=user_id, user_role=user_role
        )
        agents_map, mcp_map, permissions_map = self._group_rows(rows, user_id)
        return await self._assemble(
            list(agents_map.values()),
            mcp_map,
            permissions_map,
            user_id,
            user_role,
        )

    async def update_agent(
        self,
        agent_id: UUID,
        data: AgentPatch,
        user_id: UUID | None = None,
        user_role: WorkspaceRole | None = None,
    ) -> AgentResponse:
        agent = await self.get_or_404(agent_id)
        await self.repository.update(agent, data)
        return await self.get_agent(agent_id, user_id=user_id, user_role=user_role)

    async def delete_agent(self, agent_id: UUID) -> None:
        agent = await self.get_or_404(agent_id)
        await self.subagent_service.delete_all_for_agent(agent_id)
        await self.repository.archive(agent)

    async def get_permissions(self, agent_id: UUID) -> list[AgentUserPermissionDB]:
        return await self.repository.get_permissions(agent_id)

    async def set_permissions(
        self, agent_id: UUID, permissions: list[AgentPermissionCreate]
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

        disconnected: list[str] = []
        for server in servers:
            if not await check_mcp_server_connected(server, user_id):
                disconnected.append(str(server.id))

        return {
            "ready": len(disconnected) == 0,
            "disconnected_servers": disconnected,
            "status": "disconnected",
        }


def get_agent_service(db: AsyncSession = Depends(get_db)) -> AgentService:
    return AgentService(db)
