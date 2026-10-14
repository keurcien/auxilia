from collections import Counter
from urllib.parse import urlsplit
from uuid import UUID

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.core.service import AgentService
from app.agents.models import AgentDB, ToolStatus
from app.database import get_db
from app.exceptions import DomainValidationError
from app.integrations.langfuse import prompts
from app.integrations.langfuse.schemas import (
    LangfusePromptResponse,
    LangfusePromptVersion,
)
from app.mcp.servers.models import MCPServerDB


STATUS_META_KEY = "io.auxilia/tool_status"


def _same(a: str, b: str) -> bool:
    # Langfuse may trim surrounding whitespace on save; that is not a divergence.
    return a.strip() == b.strip()


def _tool_transforms(tools: dict[str, ToolStatus] | None) -> dict[str, dict]:
    """auxilia tool statuses as FastMCP tool transforms (`MCPConfig` `tools`).

    `disabled` hides the tool; `needs_approval` is carried in the tool's `_meta`
    for the consumer's HITL — FastMCP has no approval concept of its own.
    """
    transforms: dict[str, dict] = {}
    for tool, status in (tools or {}).items():
        if status == ToolStatus.disabled:
            transforms[tool] = {"enabled": False}
        elif status == ToolStatus.needs_approval:
            transforms[tool] = {
                "meta": {STATUS_META_KEY: ToolStatus.needs_approval.value}
            }
    return transforms


def _without_userinfo(url: str) -> str:
    # The config is readable by every Langfuse user; never publish user:password@.
    parts = urlsplit(url)
    return parts._replace(netloc=parts.netloc.rpartition("@")[2]).geturl()


def _mcp_servers(
    servers: list[MCPServerDB], tools: dict[UUID, dict[str, ToolStatus] | None]
) -> dict[str, dict]:
    """The agent's MCP servers in FastMCP's `MCPConfig` shape, without credentials."""
    counts = Counter(s.name for s in servers)
    return {
        # Server names aren't unique; the id keeps a duplicate from overwriting.
        (s.name if counts[s.name] == 1 else f"{s.name}-{s.id}"): {
            "url": _without_userinfo(s.url),
            "transport": "http",
            "tools": _tool_transforms(tools[s.id]),
        }
        for s in servers
    }


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
        self, agent_id: UUID, commit_message: str | None
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
        bindings = await self.agents.mcp_server_repository.list_for_agent(agent_id)
        servers = await self.agents.mcp_servers.list_by_ids(
            [b.mcp_server_id for b in bindings]
        )
        tools = {b.mcp_server_id: b.tools for b in bindings}
        return await prompts.create_production(
            name,
            text=agent.instructions,
            tags=[agent.name],
            # Marks auxilia releases in Langfuse's own history view.
            commit_message=f"{message} - Synced from auxilia",
            config={"mcpServers": _mcp_servers(servers, tools)},
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
