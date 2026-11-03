"""auxilia's authenticated management MCP server."""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse
from uuid import UUID

from mcp.server.auth.settings import (
    AuthSettings,
    ClientRegistrationOptions,
    RevocationOptions,
)
from mcp.server.mcpserver import Context, MCPServer
from mcp.server.transport_security import TransportSecuritySettings

from app.agents.core.service import AgentService
from app.agents.schemas import AgentConfig
from app.exceptions import DomainValidationError, NotFoundError
from app.mcp.context import to_json, tool_session
from app.mcp.management import register_management_tools
from app.mcp.oauth.provider import auxilia_oauth_provider
from app.mcp.oauth.service import issuer_url, resource_url
from app.mcp.schemas import SkillDocumentCreate
from app.mcp.servers.service import MCPServerService
from app.model_providers.service import ModelService
from app.pagination import PageParams
from app.runtime.api.protocol_service import ProtocolService
from app.settings import app_settings
from app.skills.schemas import SkillSave
from app.skills.service import SkillService
from app.threads.schemas import ThreadPlacementFilter
from app.threads.service import ThreadService
from app.users.models import WorkspaceRole


def transport_security_settings() -> TransportSecuritySettings:
    public_origin = issuer_url()
    backend_origin = app_settings.backend_url.rstrip("/")
    return TransportSecuritySettings(
        allowed_hosts=[
            urlparse(public_origin).netloc,
            urlparse(backend_origin).netloc,
            "backend:8000",
            "127.0.0.1:*",
            "localhost:*",
            "[::1]:*",
        ],
        allowed_origins=[
            public_origin,
            "http://127.0.0.1:*",
            "http://localhost:*",
            "http://[::1]:*",
        ],
    )


auxilia_mcp = MCPServer(
    "Auxilia",
    description=(
        "Manage an Auxilia workspace: agents, conversations, projects, triggers, "
        "skills and sources, MCP servers, models, sandboxes, teams, users, "
        "invites, authentication, observability, appearance, and integrations."
    ),
    auth_server_provider=auxilia_oauth_provider,
    auth=AuthSettings(
        issuer_url=issuer_url(),
        resource_server_url=resource_url(),
        validate_token_resource=True,
        required_scopes=["auxilia"],
        client_registration_options=ClientRegistrationOptions(
            enabled=True,
            valid_scopes=["auxilia"],
            default_scopes=["auxilia"],
        ),
        revocation_options=RevocationOptions(enabled=True),
    ),
)


@auxilia_mcp.tool()
async def list_skills(ctx: Context) -> list[dict[str, Any]]:
    """List skills visible in the selected workspace."""
    async with tool_session(ctx) as (db, user, workspace_id):
        return to_json(await SkillService(db, workspace_id).list_summaries(user))


@auxilia_mcp.tool()
async def get_skill(skill_id: UUID, ctx: Context) -> dict[str, Any]:
    """Read one skill, including its SKILL.md content and metadata."""
    async with tool_session(ctx) as (db, user, workspace_id):
        return to_json(await SkillService(db, workspace_id).get(skill_id, user))


@auxilia_mcp.tool()
async def create_skill(data: SkillDocumentCreate, ctx: Context) -> dict[str, Any]:
    """Create a single-file skill from a complete valid SKILL.md document.

    Auxiliary files and scripts must come from a connected skill repository.
    Include small examples directly in the SKILL.md content.
    """
    async with tool_session(ctx, minimum_role=WorkspaceRole.editor) as (
        db,
        user,
        workspace_id,
    ):
        payload = SkillSave(**data.model_dump())
        return to_json(await SkillService(db, workspace_id).create(payload, user))


@auxilia_mcp.tool()
async def update_skill(skill_id: UUID, data: SkillSave, ctx: Context) -> dict[str, Any]:
    """Replace a skill using its current revision for optimistic concurrency."""
    async with tool_session(ctx) as (db, user, workspace_id):
        return to_json(
            await SkillService(db, workspace_id).update(skill_id, data, user)
        )


@auxilia_mcp.tool()
async def delete_skill(
    skill_id: UUID, ctx: Context, detach_agents: bool = False
) -> dict[str, bool]:
    """Delete a skill, optionally detaching it from every agent first."""
    async with tool_session(ctx) as (db, user, workspace_id):
        await SkillService(db, workspace_id).delete(
            skill_id, user, detach_agents=detach_agents
        )
        return {"deleted": True}


@auxilia_mcp.tool()
async def search_conversations(
    ctx: Context,
    query: str | None = None,
    limit: int = 50,
    offset: int = 0,
    project_id: UUID | None = None,
    folder_id: UUID | None = None,
    placement: ThreadPlacementFilter = "all",
) -> dict[str, Any]:
    """Search owned conversations by title, first message, agent, or placement."""
    if not 1 <= limit <= 200 or offset < 0:
        raise DomainValidationError(
            "limit must be 1..200 and offset must be non-negative"
        )
    async with tool_session(ctx) as (db, user, workspace_id):
        page = await ThreadService(db, workspace_id).list(
            user.id,
            PageParams(limit=limit, offset=offset),
            query=query,
            project_id=project_id,
            folder_id=folder_id,
            placement=placement,
            include_api=True,
        )
        return to_json(page)


@auxilia_mcp.tool()
async def get_conversation(thread_id: str, ctx: Context) -> dict[str, Any]:
    """Read one owned conversation and its current message snapshot."""
    async with tool_session(ctx) as (db, user, workspace_id):
        service = ThreadService(db, workspace_id)
        thread = await service.get(thread_id)
        if thread.user_id != user.id:
            raise NotFoundError("Thread not found")
        metadata = await service.get_with_agent(thread_id)
        state = await ProtocolService().thread_state(workspace_id, thread_id)
        return {"thread": to_json(metadata), "state": state}


@auxilia_mcp.tool()
async def list_agents(ctx: Context, archived: bool = False) -> list[dict[str, Any]]:
    """List agents visible to the caller."""
    async with tool_session(ctx) as (db, user, workspace_id):
        agents = await AgentService(db, workspace_id).list(
            user_id=user.id,
            user_role=user.role,
            user_team_id=user.team_id,
            archived=archived,
        )
        return to_json(
            [agent for agent in agents if agent.current_user_permission is not None]
        )


@auxilia_mcp.tool()
async def get_agent(agent_id: UUID, ctx: Context) -> dict[str, Any]:
    """Read an agent's complete configuration."""
    async with tool_session(ctx) as (db, user, workspace_id):
        return to_json(
            await AgentService(db, workspace_id).get(
                agent_id,
                user_id=user.id,
                user_role=user.role,
                user_team_id=user.team_id,
            )
        )


@auxilia_mcp.tool()
async def get_agent_resources(agent_id: UUID, ctx: Context) -> dict[str, Any]:
    """List resources a trigger may activate for an agent graph.

    Returns MCP servers with their allowed tool names, plus skills, sandboxes
    and subagents. Use these IDs to build the disabled resource lists and the
    per-server disabled_mcp_tools map accepted by create_trigger and
    update_trigger. Trigger tools are binary: under an explicit server key,
    omitted tool names are accepted without approval and listed names are
    rejected. Omitted server keys retain safe agent defaults.
    """
    async with tool_session(ctx) as (db, user, workspace_id):
        service = AgentService(db, workspace_id)
        await service.get(
            agent_id,
            user_id=user.id,
            user_role=user.role,
            user_team_id=user.team_id,
        )
        return to_json(await service.get_resources(agent_id))


@auxilia_mcp.tool()
async def create_agent(config: AgentConfig, ctx: Context) -> dict[str, Any]:
    """Create an agent with its complete skills, MCP, sandbox, and subagent config."""
    async with tool_session(ctx, minimum_role=WorkspaceRole.editor) as (
        db,
        user,
        workspace_id,
    ):
        return to_json(
            await AgentService(db, workspace_id).create_from_config(
                config,
                owner_id=user.id,
                user_role=user.role,
                user_team_id=user.team_id,
            )
        )


@auxilia_mcp.tool()
async def update_agent(
    agent_id: UUID, config: AgentConfig, ctx: Context
) -> dict[str, Any]:
    """Replace an agent's complete configuration atomically."""
    async with tool_session(ctx) as (db, user, workspace_id):
        return to_json(
            await AgentService(db, workspace_id).set_config(
                agent_id,
                config,
                user_id=user.id,
                user_role=user.role,
                user_team_id=user.team_id,
            )
        )


@auxilia_mcp.tool()
async def archive_agent(agent_id: UUID, ctx: Context) -> dict[str, bool]:
    """Archive an agent."""
    async with tool_session(ctx) as (db, user, workspace_id):
        await AgentService(db, workspace_id).delete(
            agent_id, user_id=user.id, user_role=user.role
        )
        return {"archived": True}


@auxilia_mcp.tool()
async def restore_agent(agent_id: UUID, ctx: Context) -> dict[str, Any]:
    """Restore an archived agent."""
    async with tool_session(ctx) as (db, user, workspace_id):
        return to_json(
            await AgentService(db, workspace_id).restore(
                agent_id,
                user_id=user.id,
                user_role=user.role,
                user_team_id=user.team_id,
            )
        )


@auxilia_mcp.tool()
async def list_mcp_servers(ctx: Context) -> list[dict[str, Any]]:
    """List MCP servers available for agent configuration."""
    async with tool_session(ctx) as (db, user, workspace_id):
        return to_json(await MCPServerService(db, workspace_id).list_responses(user))


@auxilia_mcp.tool()
async def list_models(ctx: Context) -> list[dict[str, Any]]:
    """List models currently available for agent defaults and conversations."""
    async with tool_session(ctx) as (db, _user, workspace_id):
        return to_json(await ModelService(db, workspace_id).list_available())


register_management_tools(auxilia_mcp)
