from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.agents.models import AgentMCPServerDB
from app.repository import BaseRepository


class AgentMCPServerRepository(BaseRepository[AgentMCPServerDB]):
    def __init__(self, db: AsyncSession):
        super().__init__(AgentMCPServerDB, db)

    async def get(
        self, agent_id: UUID, server_id: UUID
    ) -> AgentMCPServerDB | None:
        stmt = select(AgentMCPServerDB).where(
            AgentMCPServerDB.agent_id == agent_id,
            AgentMCPServerDB.mcp_server_id == server_id,
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def delete_all_for_agent(self, agent_id: UUID) -> None:
        stmt = select(AgentMCPServerDB).where(
            AgentMCPServerDB.agent_id == agent_id
        )
        result = await self.db.execute(stmt)
        links = result.scalars().all()
        for link in links:
            await self.db.delete(link)
        if links:
            await self.db.flush()
