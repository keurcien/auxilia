from collections import defaultdict
from uuid import UUID

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.agents.models import AgentDB, AgentSubagentDB
from app.agents.schemas import SubagentResponse
from app.agents.subagents.repository import SubagentRepository
from app.database import get_db
from app.exceptions import NotFoundError, ValidationError


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

    async def _load_agents(self, ids: list[UUID]) -> dict[UUID, AgentDB]:
        if not ids:
            return {}
        result = await self.db.execute(select(AgentDB).where(AgentDB.id.in_(ids)))
        return {agent.id: agent for agent in result.scalars().all()}

    async def load_subagents(self, agent_id: UUID) -> list[SubagentResponse]:
        links = await self.repository.get_for_coordinator(agent_id)
        sub_ids = [b.subagent_id for b in links]
        agents = await self._load_agents(sub_ids)
        return [_to_response(agents[sid]) for sid in sub_ids if sid in agents]

    async def load_all_subagent_data(
        self, agent_ids: list[UUID]
    ) -> tuple[dict[UUID, list[SubagentResponse]], set[UUID]]:
        if not agent_ids:
            return {}, set()

        result = await self.db.execute(
            select(AgentSubagentDB).where(
                AgentSubagentDB.coordinator_id.in_(agent_ids)
                | AgentSubagentDB.subagent_id.in_(agent_ids)
            )
        )
        all_links = list(result.scalars().all())

        referenced_ids = {b.coordinator_id for b in all_links} | {
            b.subagent_id for b in all_links
        }
        agent_lookup = await self._load_agents(list(referenced_ids))

        subagents_map: dict[UUID, list[SubagentResponse]] = defaultdict(list)
        is_subagent_ids: set[UUID] = set()
        agent_ids_set = set(agent_ids)

        for link in all_links:
            if link.coordinator_id in agent_ids_set:
                sub = agent_lookup.get(link.subagent_id)
                if sub:
                    subagents_map[link.coordinator_id].append(_to_response(sub))
            if link.subagent_id in agent_ids_set:
                is_subagent_ids.add(link.subagent_id)

        return subagents_map, is_subagent_ids

    async def create(
        self, coordinator_id: UUID, subagent_id: UUID
    ) -> AgentSubagentDB:
        if coordinator_id == subagent_id:
            raise ValidationError("Cannot add an agent as its own subagent")

        # Local import avoids AgentService → SubagentService circular import.
        from app.agents.core.repository import AgentRepository

        agent_repo = AgentRepository(self.db)

        coordinator = await agent_repo.get(coordinator_id)
        if not coordinator or coordinator.is_archived:
            raise NotFoundError("Coordinator agent not found")

        subagent = await agent_repo.get(subagent_id)
        if not subagent or subagent.is_archived:
            raise NotFoundError("Subagent not found")

        if await self.repository.has_subagents(subagent_id):
            raise ValidationError(
                "This agent already has subagents and cannot be used as a subagent"
            )

        if await self.repository.is_subagent(coordinator_id):
            raise ValidationError(
                "This agent is already used as a subagent and cannot have subagents"
            )

        existing = await self.repository.get(coordinator_id, subagent_id)
        if existing:
            return existing

        return await self.repository.create(coordinator_id, subagent_id)

    async def delete(self, coordinator_id: UUID, subagent_id: UUID) -> None:
        link = await self.repository.get(coordinator_id, subagent_id)
        if not link:
            raise NotFoundError("Subagent not found")
        await self.repository.delete(link)

    async def delete_all_for_agent(self, agent_id: UUID) -> None:
        await self.repository.delete_all_for_agent(agent_id)


def get_subagent_service(db: AsyncSession = Depends(get_db)) -> SubagentService:
    return SubagentService(db)
