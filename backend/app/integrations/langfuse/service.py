from uuid import UUID

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.core.service import AgentService
from app.agents.models import AgentDB
from app.database import get_db
from app.exceptions import DomainValidationError
from app.integrations.langfuse import prompts
from app.integrations.langfuse.schemas import (
    LangfusePromptResponse,
    LangfusePromptVersion,
)
from app.users.models import UserDB


def _same(a: str, b: str) -> bool:
    # Langfuse may trim surrounding whitespace on save; that is not a divergence.
    return a.strip() == b.strip()


class LangfusePromptService:
    """Agent instructions ↔ the Langfuse prompt named after the agent id.

    Langfuse is the release registry for external consumers; auxilia's saved
    instructions are what runs. Nothing about the link is stored here.
    """

    def __init__(self, db: AsyncSession):
        self.agents = AgentService(db)

    async def _agent(self, agent_id: UUID) -> AgentDB:
        return await self.agents.get_or_404(agent_id)

    async def get(self, agent_id: UUID) -> LangfusePromptResponse:
        agent = await self._agent(agent_id)
        production = await prompts.get_production(str(agent_id))
        return LangfusePromptResponse(
            production=production,
            diverged=production is not None
            and not _same(production.text, agent.instructions),
        )

    async def list_versions(self, agent_id: UUID) -> list[LangfusePromptVersion]:
        await self._agent(agent_id)
        return await prompts.list_versions(str(agent_id))

    async def publish(
        self, agent_id: UUID, commit_message: str | None, user: UserDB
    ) -> LangfusePromptVersion:
        """Release the saved instructions as a new production version."""
        agent = await self._agent(agent_id)
        name = str(agent_id)
        production = await prompts.get_production(name)
        if production is not None and _same(production.text, agent.instructions):
            return production
        message = (commit_message or "").strip() or (
            f"Publish first version of {agent.name}"
            if production is None
            else f"Publish {agent.name}"
        )
        # The Langfuse key is deployment-wide, so Langfuse alone can't say who.
        return await prompts.create_production(
            name,
            text=agent.instructions,
            tags=[agent.name],
            # Marks auxilia releases in Langfuse's own history view.
            commit_message=f"{message} - Synced from auxilia",
            author=user.email,
        )

    async def promote(self, agent_id: UUID, version: int) -> LangfusePromptVersion:
        """Label `version` production — only if it is what the agent now runs."""
        agent = await self._agent(agent_id)
        name = str(agent_id)
        candidate = await prompts.get_version(name, version)
        if not _same(candidate.text, agent.instructions):
            raise DomainValidationError(
                f"Version {version} does not match the saved agent instructions"
            )
        return await prompts.label_production(name, version)


def get_langfuse_prompt_service(
    db: AsyncSession = Depends(get_db),
) -> LangfusePromptService:
    return LangfusePromptService(db)
