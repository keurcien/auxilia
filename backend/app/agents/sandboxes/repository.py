from uuid import UUID

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.agents.models import AgentDB, AgentSandboxDB
from app.repository import BaseRepository
from app.sandbox.models import SandboxDB


class AgentSandboxRepository(BaseRepository[AgentSandboxDB]):
    def __init__(self, db: AsyncSession):
        super().__init__(AgentSandboxDB, db)

    async def get_for_agent(self, agent_id: UUID) -> AgentSandboxDB | None:
        stmt = select(AgentSandboxDB).where(AgentSandboxDB.agent_id == agent_id)
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def list_for_agents(
        self, agent_ids: list[UUID]
    ) -> list[tuple[AgentSandboxDB, SandboxDB]]:
        """Bindings joined with their sandbox rows, for response hydration."""
        if not agent_ids:
            return []
        stmt = (
            select(AgentSandboxDB, SandboxDB)
            .join(SandboxDB, SandboxDB.id == AgentSandboxDB.sandbox_id)
            .where(AgentSandboxDB.agent_id.in_(agent_ids))
        )
        result = await self.db.execute(stmt)
        return [(row[0], row[1]) for row in result.all()]

    async def list_agents_for_sandbox(self, sandbox_id: UUID) -> list[AgentDB]:
        """Agents currently bound to the sandbox (for the delete-guard UI)."""
        stmt = (
            select(AgentDB)
            .join(AgentSandboxDB, AgentSandboxDB.agent_id == AgentDB.id)
            .where(AgentSandboxDB.sandbox_id == sandbox_id)
            .order_by(AgentDB.name)
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def delete_all_for_sandbox(self, sandbox_id: UUID) -> None:
        stmt = delete(AgentSandboxDB).where(AgentSandboxDB.sandbox_id == sandbox_id)
        await self.db.execute(stmt)
