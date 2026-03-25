from uuid import UUID

from sqlalchemy import or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.agents.models import AgentSubagentBindingDB


class SubagentRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_binding(
        self, coordinator_id: UUID, subagent_id: UUID
    ) -> AgentSubagentBindingDB | None:
        result = await self.db.execute(
            select(AgentSubagentBindingDB).where(
                AgentSubagentBindingDB.coordinator_id == coordinator_id,
                AgentSubagentBindingDB.subagent_id == subagent_id,
            )
        )
        return result.scalar_one_or_none()

    async def get_bindings_for_coordinator(
        self, coordinator_id: UUID
    ) -> list[AgentSubagentBindingDB]:
        result = await self.db.execute(
            select(AgentSubagentBindingDB).where(
                AgentSubagentBindingDB.coordinator_id == coordinator_id
            )
        )
        return list(result.scalars().all())

    async def get_coordinator_binding(
        self, subagent_id: UUID
    ) -> AgentSubagentBindingDB | None:
        result = await self.db.execute(
            select(AgentSubagentBindingDB)
            .where(AgentSubagentBindingDB.subagent_id == subagent_id)
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def has_subagents(self, agent_id: UUID) -> bool:
        result = await self.db.execute(
            select(AgentSubagentBindingDB.id)
            .where(AgentSubagentBindingDB.coordinator_id == agent_id)
            .limit(1)
        )
        return result.scalar_one_or_none() is not None

    async def is_subagent(self, agent_id: UUID) -> bool:
        result = await self.db.execute(
            select(AgentSubagentBindingDB.id)
            .where(AgentSubagentBindingDB.subagent_id == agent_id)
            .limit(1)
        )
        return result.scalar_one_or_none() is not None

    async def create_binding(
        self, coordinator_id: UUID, subagent_id: UUID
    ) -> AgentSubagentBindingDB:
        binding = AgentSubagentBindingDB(
            coordinator_id=coordinator_id,
            subagent_id=subagent_id,
        )
        self.db.add(binding)
        await self.db.commit()
        await self.db.refresh(binding)
        return binding

    async def delete_binding(self, binding: AgentSubagentBindingDB) -> None:
        await self.db.delete(binding)
        await self.db.commit()

    async def delete_all_for_agent(self, agent_id: UUID) -> None:
        result = await self.db.execute(
            select(AgentSubagentBindingDB).where(
                or_(
                    AgentSubagentBindingDB.coordinator_id == agent_id,
                    AgentSubagentBindingDB.subagent_id == agent_id,
                )
            )
        )
        bindings = result.scalars().all()
        for binding in bindings:
            await self.db.delete(binding)
        if bindings:
            await self.db.commit()
