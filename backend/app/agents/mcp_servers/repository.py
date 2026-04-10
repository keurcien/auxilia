from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.agents.models import AgentMCPServerDB
from app.repositories import BaseRepository


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
