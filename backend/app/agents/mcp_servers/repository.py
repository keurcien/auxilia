from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.agents.models import AgentMCPServerDB


class MCPServerRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get(
        self, agent_id: UUID, server_id: UUID
    ) -> AgentMCPServerDB | None:
        result = await self.db.execute(
            select(AgentMCPServerDB).where(
                AgentMCPServerDB.agent_id == agent_id,
                AgentMCPServerDB.mcp_server_id == server_id,
            )
        )
        return result.scalar_one_or_none()

    async def create(
        self, agent_id: UUID, server_id: UUID
    ) -> AgentMCPServerDB:
        db_link = AgentMCPServerDB(
            agent_id=agent_id,
            mcp_server_id=server_id,
            tools=None,
        )
        self.db.add(db_link)
        await self.db.commit()
        await self.db.refresh(db_link)
        return db_link

    async def update(
        self, link: AgentMCPServerDB, data: dict
    ) -> AgentMCPServerDB:
        for key, value in data.items():
            setattr(link, key, value)
        self.db.add(link)
        await self.db.commit()
        await self.db.refresh(link)
        return link

    async def delete(self, link: AgentMCPServerDB) -> None:
        await self.db.delete(link)
        await self.db.commit()
