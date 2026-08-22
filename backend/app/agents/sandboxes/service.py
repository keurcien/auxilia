from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.models import AgentSandboxBase, AgentSandboxDB
from app.agents.sandboxes.repository import AgentSandboxRepository
from app.agents.schemas import AgentSandboxConfig
from app.exceptions import NotFoundError
from app.sandbox.repository import SandboxRepository
from app.service import BaseService


class AgentSandboxService(BaseService[AgentSandboxDB, AgentSandboxRepository]):
    not_found_message = "Agent sandbox not found"

    def __init__(self, db: AsyncSession):
        super().__init__(db, AgentSandboxRepository(db))
        self._sandboxes = SandboxRepository(db)

    async def set_for_agent(
        self, agent_id: UUID, configs: list[AgentSandboxConfig]
    ) -> None:
        """Whole-set replace of an agent's sandbox binding (≤1 for now):
        upsert the wanted link and delete the rest. Same semantics as
        AgentMCPServerService.set_for_agent, minus tool discovery — the
        sandbox tool surface is static."""
        existing = await self.repository.get_for_agent(agent_id)
        wanted = configs[0] if configs else None

        if wanted is None:
            if existing:
                await self.repository.delete(existing)
            return

        if not await self._sandboxes.get(wanted.sandbox_id):
            raise NotFoundError("Sandbox not found")

        if existing:
            if existing.sandbox_id != wanted.sandbox_id:
                # Replace, don't mutate: the unique constraint is on agent_id,
                # so delete-then-create keeps the history unambiguous.
                await self.repository.delete(existing)
            else:
                if existing.tools != wanted.tools:
                    existing.tools = wanted.tools
                    self.db.add(existing)
                    await self.db.flush()
                return

        await self.repository.create(
            AgentSandboxBase(
                agent_id=agent_id,
                sandbox_id=wanted.sandbox_id,
                tools=wanted.tools,
            )
        )
