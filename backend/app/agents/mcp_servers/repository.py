from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.agents.models import AgentMCPServerBindingDB


class MCPBindingRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_binding(
        self, agent_id: UUID, server_id: UUID
    ) -> AgentMCPServerBindingDB | None:
        result = await self.db.execute(
            select(AgentMCPServerBindingDB).where(
                AgentMCPServerBindingDB.agent_id == agent_id,
                AgentMCPServerBindingDB.mcp_server_id == server_id,
            )
        )
        return result.scalar_one_or_none()

    async def create_binding(
        self, agent_id: UUID, server_id: UUID
    ) -> AgentMCPServerBindingDB:
        db_binding = AgentMCPServerBindingDB(
            agent_id=agent_id,
            mcp_server_id=server_id,
            tools=None,
        )
        self.db.add(db_binding)
        await self.db.commit()
        await self.db.refresh(db_binding)
        return db_binding

    async def update_binding(
        self, binding: AgentMCPServerBindingDB, data: dict
    ) -> AgentMCPServerBindingDB:
        for key, value in data.items():
            setattr(binding, key, value)
        self.db.add(binding)
        await self.db.commit()
        await self.db.refresh(binding)
        return binding

    async def delete_binding(self, binding: AgentMCPServerBindingDB) -> None:
        await self.db.delete(binding)
        await self.db.commit()
