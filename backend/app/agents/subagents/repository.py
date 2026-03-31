from uuid import UUID

from sqlalchemy import or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.agents.models import AgentSubagentDB


class SubagentRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get(
        self, coordinator_id: UUID, subagent_id: UUID
    ) -> AgentSubagentDB | None:
        result = await self.db.execute(
            select(AgentSubagentDB).where(
                AgentSubagentDB.coordinator_id == coordinator_id,
                AgentSubagentDB.subagent_id == subagent_id,
            )
        )
        return result.scalar_one_or_none()

    async def get_for_coordinator(
        self, coordinator_id: UUID
    ) -> list[AgentSubagentDB]:
        result = await self.db.execute(
            select(AgentSubagentDB).where(
                AgentSubagentDB.coordinator_id == coordinator_id
            )
        )
        return list(result.scalars().all())

    async def get_coordinator(
        self, subagent_id: UUID
    ) -> AgentSubagentDB | None:
        result = await self.db.execute(
            select(AgentSubagentDB)
            .where(AgentSubagentDB.subagent_id == subagent_id)
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def has_subagents(self, agent_id: UUID) -> bool:
        result = await self.db.execute(
            select(AgentSubagentDB.id)
            .where(AgentSubagentDB.coordinator_id == agent_id)
            .limit(1)
        )
        return result.scalar_one_or_none() is not None

    async def is_subagent(self, agent_id: UUID) -> bool:
        result = await self.db.execute(
            select(AgentSubagentDB.id)
            .where(AgentSubagentDB.subagent_id == agent_id)
            .limit(1)
        )
        return result.scalar_one_or_none() is not None

    async def create(
        self, coordinator_id: UUID, subagent_id: UUID
    ) -> AgentSubagentDB:
        link = AgentSubagentDB(
            coordinator_id=coordinator_id,
            subagent_id=subagent_id,
        )
        self.db.add(link)
        await self.db.commit()
        await self.db.refresh(link)
        return link

    async def delete(self, link: AgentSubagentDB) -> None:
        await self.db.delete(link)
        await self.db.commit()

    async def delete_all_for_agent(self, agent_id: UUID) -> None:
        result = await self.db.execute(
            select(AgentSubagentDB).where(
                or_(
                    AgentSubagentDB.coordinator_id == agent_id,
                    AgentSubagentDB.subagent_id == agent_id,
                )
            )
        )
        links = result.scalars().all()
        for link in links:
            await self.db.delete(link)
        if links:
            await self.db.commit()
