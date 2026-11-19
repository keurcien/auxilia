import json
from collections import Counter
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from typing import NoReturn
from urllib.parse import urlsplit
from uuid import UUID

from fastapi import Depends
from langfuse import Langfuse
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.core.service import AgentService
from app.agents.models import AgentDB, AgentMCPServerDB, ToolStatus
from app.database import get_db
from app.exceptions import DomainError, DomainValidationError, NotFoundError
from app.integrations.langfuse import prompts
from app.integrations.langfuse.callback import acquire_langfuse_callback_handler
from app.integrations.langfuse.schemas import (
    LangfusePromptResponse,
    LangfusePromptVersion,
    LangfusePublishDraft,
    LangfusePublishRequest,
)
from app.mcp.servers.models import MCPServerDB
from app.observability.service import WorkspaceObservabilityService
from app.users.models import UserDB
from app.workspaces.dependencies import get_active_workspace_id


STATUS_META_KEY = "io.auxilia/tool_status"
MAX_CONFIG_DEPTH = 50


def _same(a: str, b: str) -> bool:
    return a.strip() == b.strip()


def _tool_transforms(tools: dict[str, ToolStatus]) -> dict[str, dict]:
    """Represent the complete saved allowlist as FastMCP tool transforms."""
    transforms: dict[str, dict] = {}
    for tool, status in tools.items():
        if status == ToolStatus.always_allow:
            transforms[tool] = {"enabled": True}
        elif status == ToolStatus.disabled:
            transforms[tool] = {"enabled": False}
        elif status == ToolStatus.needs_approval:
            transforms[tool] = {
                "enabled": True,
                "meta": {STATUS_META_KEY: ToolStatus.needs_approval.value},
            }
    return transforms


def _has_enabled_tools(tools: dict[str, ToolStatus] | None) -> bool:
    return bool(
        tools and any(status != ToolStatus.disabled for status in tools.values())
    )


def _sanitized_url(url: str) -> str:
    """Keep the remote endpoint, never embedded credentials or query secrets."""
    parts = urlsplit(url)
    netloc = parts.netloc.rsplit("@", 1)[-1]
    return parts._replace(netloc=netloc, query="", fragment="").geturl()


def _mcp_servers(
    bindings: Sequence[AgentMCPServerDB],
    servers: Sequence[MCPServerDB],
) -> dict[str, dict]:
    """Build the default-enabled, configured MCP surface without credentials."""
    servers_by_id = {server.id: server for server in servers}
    selected = [
        (binding, server)
        for binding in bindings
        if binding.enabled_by_default
        and _has_enabled_tools(binding.tools)
        and (server := servers_by_id.get(binding.mcp_server_id)) is not None
    ]
    counts = Counter(server.name for _, server in selected)
    return {
        (server.name if counts[server.name] == 1 else f"{server.name}-{server.id}"): {
            "url": _sanitized_url(server.url),
            "transport": "http",
            "tools": _tool_transforms(binding.tools or {}),
        }
        for binding, server in selected
    }


def _reject_json_constant(name: str) -> NoReturn:
    raise ValueError(f"{name} is not valid JSON")


def _validate_config_depth(config: dict) -> None:
    stack: list[tuple[object, int]] = [(config, 1)]
    while stack:
        value, depth = stack.pop()
        if depth > MAX_CONFIG_DEPTH:
            raise DomainValidationError(
                f"Config must not exceed {MAX_CONFIG_DEPTH} levels of nesting"
            )
        if isinstance(value, dict):
            stack.extend((child, depth + 1) for child in value.values())
        elif isinstance(value, list):
            stack.extend((child, depth + 1) for child in value)


def _validate_config_urls(config: dict) -> None:
    servers = config.get("mcpServers")
    if not isinstance(servers, dict):
        return
    for server in servers.values():
        url = server.get("url") if isinstance(server, dict) else None
        if not isinstance(url, str):
            continue
        try:
            parts = urlsplit(url)
        except ValueError as err:
            raise DomainValidationError("Config contains an invalid URL") from err
        if "@" in parts.netloc or parts.query or parts.fragment:
            raise DomainValidationError(
                "Config URLs must not contain credentials, query parameters, or "
                "fragments because the config is visible to Langfuse users"
            )


def _public_config(config: dict) -> dict:
    return {key: value for key, value in config.items() if key != prompts.AUTHOR_KEY}


def _parse_config(text: str) -> dict:
    try:
        parsed: object = json.loads(text, parse_constant=_reject_json_constant)
    except (ValueError, RecursionError) as err:
        raise DomainValidationError(f"Config is not valid JSON: {err}") from err
    if not isinstance(parsed, dict):
        raise DomainValidationError("Config must be a JSON object")
    _validate_config_depth(parsed)
    _validate_config_urls(parsed)
    return _public_config(parsed)


class LangfusePromptService:
    """Version an agent's saved instructions in its workspace's Langfuse project."""

    def __init__(self, db: AsyncSession, workspace_id: UUID):
        self.workspace_id = workspace_id
        self.agents = AgentService(db, workspace_id)
        self.observability = WorkspaceObservabilityService(db)

    async def _agent(self, agent_id: UUID) -> AgentDB:
        agent = await self.agents.repository.get_scoped(agent_id)
        if not isinstance(agent, AgentDB):
            raise NotFoundError("Agent not found")
        return agent

    @asynccontextmanager
    async def _client(self) -> AsyncIterator[Langfuse]:
        config = await self.observability.get_runtime_config(self.workspace_id)
        if config is None:
            raise NotFoundError("Langfuse is not configured")
        lease = acquire_langfuse_callback_handler(config)
        if lease is None or lease.client is None:
            raise DomainError("Could not initialize Langfuse")
        try:
            yield lease.client
        finally:
            lease.release()

    async def get(self, agent_id: UUID) -> LangfusePromptResponse:
        agent = await self._agent(agent_id)
        async with self._client() as client:
            production = await prompts.get_production(client, str(agent_id))
        return LangfusePromptResponse(
            production=production,
            diverged=production is not None
            and not _same(production.text, agent.instructions),
        )

    async def list_versions(self, agent_id: UUID) -> list[LangfusePromptVersion]:
        await self._agent(agent_id)
        async with self._client() as client:
            return await prompts.list_versions(client, str(agent_id))

    async def _config(self, agent_id: UUID) -> dict:
        bindings = await self.agents.mcp_server_repository.list_for_agent(agent_id)
        servers = await self.agents.mcp_servers.list_by_ids(
            [binding.mcp_server_id for binding in bindings]
        )
        return {"mcpServers": _mcp_servers(bindings, servers)}

    async def draft(self, agent_id: UUID) -> LangfusePublishDraft:
        await self._agent(agent_id)
        config = await self._config(agent_id)
        async with self._client() as client:
            labels = await prompts.list_labels(client, str(agent_id))
        return LangfusePublishDraft(
            config_json=json.dumps(config, indent=2),
            labels=sorted({*labels, prompts.PRODUCTION}),
        )

    async def publish(
        self,
        agent_id: UUID,
        data: LangfusePublishRequest,
        publisher: UserDB,
    ) -> LangfusePromptVersion:
        if data.label == "latest":
            raise DomainValidationError("The label `latest` is reserved by Langfuse")
        agent = await self._agent(agent_id)
        name = str(agent_id)
        public_config = (
            await self._config(agent_id)
            if data.config_json is None
            else _parse_config(data.config_json)
        )
        async with self._client() as client:
            production = await prompts.get_production(client, name)
            if (
                data.label == prompts.PRODUCTION
                and production is not None
                and _same(production.text, agent.instructions)
                and production.public_config == public_config
            ):
                return production

            message = (data.commit_message or "").strip() or (
                f"Publish first version of {agent.name}"
                if production is None
                else f"Publish {agent.name}"
            )
            published_by = publisher.email or publisher.name or str(publisher.id)
            return await prompts.create_version(
                client,
                name,
                text=agent.instructions,
                label=data.label,
                tags=[agent.name],
                commit_message=f"{message} - Synced from auxilia",
                config={
                    **public_config,
                    prompts.AUTHOR_KEY: published_by,
                },
            )

    async def promote(self, agent_id: UUID, version: int) -> LangfusePromptVersion:
        agent = await self._agent(agent_id)
        name = str(agent_id)
        async with self._client() as client:
            candidate = await prompts.get_version(client, name, version)
            if not _same(candidate.text, agent.instructions):
                raise DomainValidationError(
                    f"Version {version} does not match the saved agent instructions"
                )
            return await prompts.label_production(client, name, version)


def get_langfuse_prompt_service(
    db: AsyncSession = Depends(get_db),
    workspace_id: UUID = Depends(get_active_workspace_id),
) -> LangfusePromptService:
    return LangfusePromptService(db, workspace_id)
