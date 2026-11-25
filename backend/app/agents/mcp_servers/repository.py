from uuid import UUID

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.agents.core.repository import visible_agent_clause
from app.agents.models import AgentDB, AgentMCPServerDB
from app.repository import BaseRepository


class AgentMCPServerRepository(BaseRepository[AgentMCPServerDB]):
    def __init__(self, db: AsyncSession):
        super().__init__(AgentMCPServerDB, db)

    async def get(self, agent_id: UUID, server_id: UUID) -> AgentMCPServerDB | None:
        stmt = select(AgentMCPServerDB).where(
            AgentMCPServerDB.agent_id == agent_id,
            AgentMCPServerDB.mcp_server_id == server_id,
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def list_for_agent(self, agent_id: UUID) -> list[AgentMCPServerDB]:
        stmt = select(AgentMCPServerDB).where(AgentMCPServerDB.agent_id == agent_id)
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def delete_all_for_agent(self, agent_id: UUID) -> None:
        stmt = delete(AgentMCPServerDB).where(AgentMCPServerDB.agent_id == agent_id)
        await self.db.execute(stmt)

    async def list_agents_for_server(
        self,
        server_id: UUID,
        *,
        visible_to: tuple[UUID, UUID | None] | None = None,
    ) -> list[AgentDB]:
        """Agents currently bound to the MCP server, by name. `visible_to`
        (user id, team id) keeps only the agents that user can see."""
        stmt = (
            select(AgentDB)
            .join(AgentMCPServerDB, AgentMCPServerDB.agent_id == AgentDB.id)
            .where(AgentMCPServerDB.mcp_server_id == server_id)
            .order_by(AgentDB.name)
        )
        if visible_to is not None:
            stmt = stmt.where(visible_agent_clause(*visible_to))
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def list_for_server(self, server_id: UUID) -> list[AgentMCPServerDB]:
        stmt = select(AgentMCPServerDB).where(
            AgentMCPServerDB.mcp_server_id == server_id
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def delete_all_for_server(self, server_id: UUID) -> None:
        stmt = delete(AgentMCPServerDB).where(
            AgentMCPServerDB.mcp_server_id == server_id
        )
        await self.db.execute(stmt)
