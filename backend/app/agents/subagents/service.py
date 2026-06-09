from collections import defaultdict
from uuid import UUID

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.agents.models import AgentDB, AgentSubagentDB
from app.agents.schemas import SubagentResponse
from app.agents.subagents.repository import SubagentRepository
from app.database import get_db
from app.exceptions import (
    DomainValidationError,
    NotFoundError,
    PermissionDeniedError,
)
from app.users.models import WorkspaceRole


def _to_response(agent: AgentDB) -> SubagentResponse:
    return SubagentResponse(
        id=agent.id,
        name=agent.name,
        emoji=agent.emoji,
        description=agent.description,
    )


class SubagentService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.repository = SubagentRepository(db)

    async def _list_agents(self, ids: list[UUID]) -> dict[UUID, AgentDB]:
        if not ids:
            return {}
        result = await self.db.execute(select(AgentDB).where(AgentDB.id.in_(ids)))
        return {agent.id: agent for agent in result.scalars().all()}

    async def list_subagents(self, agent_id: UUID) -> list[SubagentResponse]:
        links = await self.repository.list_for_supervisor(agent_id)
        sub_ids = [b.subagent_id for b in links]
        agents = await self._list_agents(sub_ids)
        return [_to_response(agents[sid]) for sid in sub_ids if sid in agents]

    async def list_all_subagent_data(
        self, agent_ids: list[UUID]
    ) -> tuple[dict[UUID, list[SubagentResponse]], set[UUID]]:
        if not agent_ids:
            return {}, set()

        result = await self.db.execute(
            select(AgentSubagentDB).where(
                AgentSubagentDB.supervisor_id.in_(agent_ids)
                | AgentSubagentDB.subagent_id.in_(agent_ids)
            )
        )
        all_links = list(result.scalars().all())

        referenced_ids = {b.supervisor_id for b in all_links} | {
            b.subagent_id for b in all_links
        }
        agent_lookup = await self._list_agents(list(referenced_ids))

        subagents_map: dict[UUID, list[SubagentResponse]] = defaultdict(list)
        is_subagent_ids: set[UUID] = set()
        agent_ids_set = set(agent_ids)

        for link in all_links:
            if link.supervisor_id in agent_ids_set:
                sub = agent_lookup.get(link.subagent_id)
                if sub:
                    subagents_map[link.supervisor_id].append(_to_response(sub))
            if link.subagent_id in agent_ids_set:
                is_subagent_ids.add(link.subagent_id)

        return subagents_map, is_subagent_ids

    async def create_or_update(
        self, supervisor_id: UUID, subagent_id: UUID
    ) -> AgentSubagentDB:
        if supervisor_id == subagent_id:
            raise DomainValidationError("Cannot add an agent as its own subagent")

        # Local import avoids AgentService → SubagentService circular import.
        from app.agents.core.repository import AgentRepository

        agent_repo = AgentRepository(self.db)

        supervisor = await agent_repo.get(supervisor_id)
        if not supervisor or supervisor.is_archived:
            raise NotFoundError("Supervisor agent not found")

        subagent = await agent_repo.get(subagent_id)
        if not subagent or subagent.is_archived:
            raise NotFoundError("Subagent not found")

        if await self.repository.has_subagents(subagent_id):
            raise DomainValidationError(
                "This agent already has subagents and cannot be used as a subagent"
            )

        if await self.repository.is_subagent(supervisor_id):
            raise DomainValidationError(
                "This agent is already used as a subagent and cannot have subagents"
            )

        return await self.repository.create_or_update(supervisor_id, subagent_id)

    async def set_for_supervisor(
        self,
        supervisor_id: UUID,
        subagent_ids: list[UUID],
        user_role: WorkspaceRole | None = None,
    ) -> None:
        """Bulk-replace the supervisor's subagents.

        Changing the set is admin-only (mirrors the granular endpoints);
        an unchanged set is a no-op so non-admins can still save configs
        that carry their agent's existing subagents.
        """
        current = {
            link.subagent_id
            for link in await self.repository.list_for_supervisor(supervisor_id)
        }
        wanted = set(subagent_ids)
        if current == wanted:
            return
        if user_role != WorkspaceRole.admin:
            raise PermissionDeniedError("Only admins can modify subagents")
        for subagent_id in wanted - current:
            await self.create_or_update(supervisor_id, subagent_id)
        for subagent_id in current - wanted:
            await self.delete(supervisor_id, subagent_id)

    async def delete(self, supervisor_id: UUID, subagent_id: UUID) -> None:
        link = await self.repository.get(supervisor_id, subagent_id)
        if not link:
            raise NotFoundError("Subagent not found")
        await self.repository.delete(link)

    async def delete_all_for_agent(self, agent_id: UUID) -> None:
        await self.repository.delete_all_for_agent(agent_id)


def get_subagent_service(db: AsyncSession = Depends(get_db)) -> SubagentService:
    return SubagentService(db)
