"""Additional management tools exposed by auxilia's own MCP server."""

from __future__ import annotations

import logging
from typing import Any, Literal
from uuid import UUID

from mcp.server.mcpserver import Context, MCPServer
from mcp.types import ToolAnnotations
from pydantic import BaseModel, Field

from app.agents.core.service import AgentService
from app.agents.mcp_servers.service import AgentMCPServerService
from app.agents.models import EffectivePermission
from app.agents.schemas import AgentPermissionCreate
from app.appearance.schemas import InstanceAppearancePatch
from app.appearance.service import InstanceAppearanceService
from app.auth.configuration import WorkspaceAuthenticationService
from app.auth.schemas import WorkspaceAuthenticationUpdate
from app.database import get_checkpointer
from app.exceptions import DomainValidationError, NotFoundError, PermissionDeniedError
from app.integrations.slack.schemas import AgentSlackBotUpdate
from app.integrations.slack.service import AgentSlackBotService
from app.integrations.whatsapp.schemas import (
    WhatsAppConnectionUpdate,
    WhatsAppWorkspaceSettingsUpdate,
)
from app.integrations.whatsapp.service import (
    WhatsAppConnectionService,
    WhatsAppWorkspaceSettingsService,
)
from app.invites.schemas import InviteCreate
from app.invites.service import InviteService
from app.mcp.client.connectivity import test_connection
from app.mcp.client.storage import TokenStorageFactory
from app.mcp.context import to_json, tool_session
from app.mcp.servers.schemas import MCPServerCreate, MCPServerPatch
from app.mcp.servers.service import MCPServerService
from app.model_providers.service import ModelService
from app.notifications.schemas import SlackNotificationSettingsUpdate
from app.notifications.service import SlackNotificationSettingsService
from app.observability.schemas import WorkspaceObservabilityUpdate
from app.observability.service import WorkspaceObservabilityService
from app.pagination import PageParams
from app.runtime.hitl import load_interrupt_scopes, pending_approval_requests
from app.runtime.runs.schemas import RunResponse, queued_prompt_input
from app.runtime.runs.service import RunService
from app.sandbox.schemas import SandboxCreate, SandboxPatch
from app.sandbox.service import SandboxService
from app.skills.schemas import SkillSourceCreate, SkillSourcePatch
from app.skills.service import SkillService
from app.skills.sources.service import SkillSourceService
from app.teams.schemas import TeamCreate, TeamPatch
from app.teams.service import TeamService
from app.threads.models import ThreadSource
from app.threads.schemas import (
    ThreadCreate,
    ThreadModelUpdate,
    ThreadPatch,
    ThreadResourcesPatch,
)
from app.threads.service import ThreadService
from app.triggers.schemas import TriggerCreate, TriggerPatch
from app.triggers.service import TriggerService
from app.users.models import UserDB, WorkspaceRole
from app.users.schemas import UserPatch, UserRolePatch, UserTeamPatch
from app.users.service import UserService
from app.workspaces.schemas import WorkspacePatch
from app.workspaces.service import WorkspaceService


logger = logging.getLogger(__name__)


class MCPUserPatch(BaseModel):
    """Administrative user fields safe to change through an agent."""

    name: str | None = Field(default=None, max_length=255)
    email: str | None = Field(default=None, max_length=255)
    can_create_workspace: bool | None = None
    can_delete_threads: bool | None = None


class MCPApprovalDecision(BaseModel):
    """One explicit answer to a pending tool call."""

    tool_call_id: str
    type: Literal["approve", "reject"]


async def _require_agent(
    service: AgentService,
    user: UserDB,
    agent_id: UUID,
    permission: EffectivePermission,
    action: str,
    *,
    include_archived: bool = False,
) -> None:
    await service.require_permission(
        agent_id,
        at_least=permission,
        action=action,
        user_id=user.id,
        user_role=user.role,
        user_team_id=user.team_id,
        include_archived=include_archived,
    )


async def _authorize_conversation(ctx: Context, thread_id: str) -> tuple[UUID, UUID]:
    """Resolve an owned conversation and release its DB transaction."""
    async with tool_session(ctx) as (db, user, workspace_id):
        thread = await ThreadService(db, workspace_id).get(thread_id)
        if thread.user_id != user.id:
            raise NotFoundError("Thread not found")
        await _require_agent(
            AgentService(db, workspace_id),
            user,
            thread.agent_id,
            EffectivePermission.member,
            "use this agent",
            include_archived=True,
        )
        return workspace_id, user.id


def _apply_tool_annotations(mcp: MCPServer) -> None:
    """Attach safety hints after all tools are registered."""
    manager = getattr(mcp, "_tool_manager", None)
    tools = getattr(manager, "_tools", {})
    read_prefixes = (
        "list_",
        "get_",
        "search_",
        "preview_",
        "check_",
        "test_",
        "discover_",
        "is_",
    )
    destructive_prefixes = (
        "delete_",
        "remove_",
        "revoke_",
        "reset_",
        "clear_",
        "archive_",
        "disconnect_",
        "unlink_",
        "cancel_",
    )
    idempotent_prefixes = (
        "update_",
        "set_",
        "rename_",
        "enable_",
        "disable_",
        "restore_",
    )
    open_world_names = {
        "list_mcp_server_tools",
        "test_mcp_server",
        "preview_skill_source",
        "plan_skill_source_sync",
        "sync_skill_source",
    }
    read_only_names = {"plan_skill_source_sync"}
    destructive_names = {"permanently_delete_agent"}
    for name, tool in tools.items():
        read_only = name.startswith(read_prefixes) or name in read_only_names
        destructive = name.startswith(destructive_prefixes) or name in destructive_names
        tool.annotations = ToolAnnotations(
            readOnlyHint=read_only,
            destructiveHint=destructive,
            idempotentHint=read_only or name.startswith(idempotent_prefixes),
            openWorldHint=name in open_world_names,
        )


def register_management_tools(mcp: MCPServer) -> None:
    # Conversations

    @mcp.tool()
    async def create_conversation(data: ThreadCreate, ctx: Context) -> dict[str, Any]:
        """Create a conversation owned by the caller."""
        async with tool_session(ctx) as (db, user, workspace_id):
            agents = AgentService(db, workspace_id)
            await _require_agent(
                agents,
                user,
                data.agent_id,
                EffectivePermission.member,
                "use this agent",
            )
            return to_json(
                await ThreadService(db, workspace_id).create(
                    data, user.id, ThreadSource.api
                )
            )

    @mcp.tool()
    async def rename_conversation(
        thread_id: str, data: ThreadPatch, ctx: Context
    ) -> dict[str, Any]:
        """Rename one conversation owned by the caller."""
        async with tool_session(ctx) as (db, user, workspace_id):
            service = ThreadService(db, workspace_id)
            thread = await service.get(thread_id)
            if thread.user_id != user.id:
                raise NotFoundError("Thread not found")
            return to_json(await service.update(thread_id, data))

    @mcp.tool()
    async def set_conversation_model(
        thread_id: str, data: ThreadModelUpdate, ctx: Context
    ) -> dict[str, Any]:
        """Change the model used by one conversation owned by the caller."""
        async with tool_session(ctx) as (db, user, workspace_id):
            service = ThreadService(db, workspace_id)
            thread = await service.get(thread_id)
            if thread.user_id != user.id:
                raise NotFoundError("Thread not found")
            return to_json(await service.update_model(thread_id, data))

    @mcp.tool()
    async def set_conversation_resources(
        thread_id: str, data: ThreadResourcesPatch, ctx: Context
    ) -> dict[str, Any]:
        """Enable or disable this conversation's agent resources."""
        async with tool_session(ctx) as (db, user, workspace_id):
            service = ThreadService(db, workspace_id)
            thread = await service.get(thread_id)
            if thread.user_id != user.id:
                raise NotFoundError("Thread not found")
            return to_json(await service.update_resources(thread_id, data))

    @mcp.tool()
    async def delete_conversation(thread_id: str, ctx: Context) -> dict[str, bool]:
        """Permanently delete one conversation owned by the caller."""
        async with tool_session(ctx) as (db, user, workspace_id):
            service = ThreadService(db, workspace_id)
            thread = await service.get(thread_id)
            if thread.user_id != user.id:
                raise NotFoundError("Thread not found")
            await service.delete(thread_id)
            # Checkpoints are an external side effect: commit the row first.
            await db.commit()
            try:
                await service.purge_checkpoints([thread_id])
            except Exception:  # noqa: BLE001
                logger.warning(
                    "Conversation %s was deleted but its checkpoints remain",
                    thread_id,
                    exc_info=True,
                )
            return {"deleted": True}

    @mcp.tool()
    async def send_conversation_message(
        thread_id: str, message: str, ctx: Context
    ) -> dict[str, Any]:
        """Start a durable conversation run and return immediately with its run id."""
        message = message.strip()
        if not message:
            raise DomainValidationError("A conversation message cannot be empty.")
        if len(message) > 100_000:
            raise DomainValidationError(
                "A conversation message cannot exceed 100000 characters."
            )
        workspace_id, user_id = await _authorize_conversation(ctx, thread_id)
        record = await RunService().create(
            thread_id=thread_id,
            user_id=str(user_id),
            input=queued_prompt_input(message),
        )
        if record.workspace_id != workspace_id:
            raise NotFoundError("Run not found")
        return to_json(RunResponse.from_record(record))

    @mcp.tool()
    async def list_conversation_runs(
        thread_id: str, ctx: Context
    ) -> list[dict[str, Any]]:
        """List durable runs for a conversation owned by the caller."""
        workspace_id, _ = await _authorize_conversation(ctx, thread_id)
        records = await RunService().list_for_thread(thread_id, workspace_id)
        return to_json([RunResponse.from_record(record) for record in records])

    @mcp.tool()
    async def get_conversation_run(
        thread_id: str, run_id: str, ctx: Context
    ) -> dict[str, Any]:
        """Read the operational status of one conversation run."""
        workspace_id, _ = await _authorize_conversation(ctx, thread_id)
        record = await RunService().get(run_id, workspace_id)
        if record.thread_id != thread_id:
            raise NotFoundError("Run not found")
        return to_json(RunResponse.from_record(record))

    @mcp.tool()
    async def list_active_conversation_runs(ctx: Context) -> list[dict[str, Any]]:
        """List the caller's currently pending or running conversation runs."""
        async with tool_session(ctx) as (db, user, workspace_id):
            user_id = str(user.id)
            await db.commit()
            records = await RunService().list_active_for_user(user_id, workspace_id)
        return to_json([RunResponse.from_record(record) for record in records])

    @mcp.tool()
    async def cancel_conversation_run(
        thread_id: str, run_id: str, ctx: Context
    ) -> dict[str, Any]:
        """Cancel one pending or running conversation run."""
        workspace_id, _ = await _authorize_conversation(ctx, thread_id)
        runs = RunService()
        record = await runs.get(run_id, workspace_id)
        if record.thread_id != thread_id:
            raise NotFoundError("Run not found")
        return to_json(RunResponse.from_record(await runs.cancel(run_id)))

    @mcp.tool()
    async def list_pending_conversation_approvals(
        thread_id: str, ctx: Context
    ) -> list[dict[str, Any]]:
        """List every pending tool-approval batch for a conversation."""
        await _authorize_conversation(ctx, thread_id)
        async with get_checkpointer() as checkpointer:
            scopes = await load_interrupt_scopes(checkpointer, thread_id)
        return [
            {
                "interrupt_id": scope.interrupt.id,
                "namespace": scope.namespace_path,
                "subagent_type": scope.subagent_type,
                "requests": pending_approval_requests(
                    scope.root,
                    scope.state,
                    interrupt_id=scope.interrupt.id,
                ),
            }
            for scope in scopes
        ]

    @mcp.tool()
    async def respond_to_conversation_approvals(
        thread_id: str,
        decisions: list[MCPApprovalDecision],
        ctx: Context,
        interrupt_id: str | None = None,
    ) -> dict[str, Any]:
        """Approve or reject all tool calls in one pending approval batch."""
        workspace_id, user_id = await _authorize_conversation(ctx, thread_id)
        serialized = [decision.model_dump() for decision in decisions]
        response = {
            "decisions": (
                serialized
                if interrupt_id is not None
                else [{"type": decision.type} for decision in decisions]
            )
        }
        resume = (
            {"interrupt_id": interrupt_id, **response}
            if interrupt_id is not None
            else response
        )
        record = await RunService().create(
            thread_id=thread_id,
            user_id=str(user_id),
            command={"resume": resume},
            multitask_strategy="enqueue",
        )
        if record.workspace_id != workspace_id:
            raise NotFoundError("Run not found")
        return to_json(RunResponse.from_record(record))

    # Triggers

    @mcp.tool()
    async def list_triggers(ctx: Context) -> list[dict[str, Any]]:
        """List scheduled and webhook triggers visible to the caller."""
        async with tool_session(ctx) as (db, user, workspace_id):
            return to_json(await TriggerService(db, workspace_id).list(user))

    @mcp.tool()
    async def get_trigger(trigger_id: UUID, ctx: Context) -> dict[str, Any]:
        """Read a trigger and its current schedule or webhook configuration."""
        async with tool_session(ctx) as (db, user, workspace_id):
            return to_json(await TriggerService(db, workspace_id).get(trigger_id, user))

    @mcp.tool()
    async def create_trigger(data: TriggerCreate, ctx: Context) -> dict[str, Any]:
        """Create a scheduled or webhook trigger for an agent.

        Call get_agent_resources first when choosing resources. Put every
        unchosen resource ID in its matching disabled list and every rejected
        tool name in disabled_mcp_tools under its MCP server ID. Trigger tools
        are binary: tools not rejected under an explicit server key run without
        approval. A null map or omitted server key rejects tools whose agent
        setting requires approval.
        """
        async with tool_session(ctx, minimum_role=WorkspaceRole.editor) as (
            db,
            user,
            workspace_id,
        ):
            return to_json(
                await TriggerService(db, workspace_id).create(data, owner=user)
            )

    @mcp.tool()
    async def update_trigger(
        trigger_id: UUID, data: TriggerPatch, ctx: Context
    ) -> dict[str, Any]:
        """Update, pause, resume, or change resource selection for a trigger."""
        async with tool_session(ctx) as (db, user, workspace_id):
            return to_json(
                await TriggerService(db, workspace_id).update(trigger_id, data, user)
            )

    @mcp.tool()
    async def delete_trigger(trigger_id: UUID, ctx: Context) -> dict[str, bool]:
        """Permanently delete a trigger managed by the caller."""
        async with tool_session(ctx) as (db, user, workspace_id):
            await TriggerService(db, workspace_id).delete(trigger_id, user)
            return {"deleted": True}

    @mcp.tool()
    async def run_trigger_now(trigger_id: UUID, ctx: Context) -> dict[str, Any]:
        """Run a trigger immediately without changing its schedule."""
        async with tool_session(ctx) as (db, user, workspace_id):
            return to_json(
                await TriggerService(db, workspace_id).run_now(trigger_id, user)
            )

    @mcp.tool()
    async def list_trigger_runs(trigger_id: UUID, ctx: Context) -> list[dict[str, Any]]:
        """List the last 30 days of runs for a trigger."""
        async with tool_session(ctx) as (db, user, workspace_id):
            return to_json(
                await TriggerService(db, workspace_id).list_threads(trigger_id, user)
            )

    # Agent permissions and readiness

    @mcp.tool()
    async def get_agent_permissions(
        agent_id: UUID, ctx: Context
    ) -> list[dict[str, Any]]:
        """List explicit user permissions for an agent."""
        async with tool_session(ctx) as (db, user, workspace_id):
            service = AgentService(db, workspace_id)
            await _require_agent(
                service,
                user,
                agent_id,
                EffectivePermission.admin,
                "view this agent's permissions",
            )
            return to_json(await service.get_permissions(agent_id))

    @mcp.tool()
    async def set_agent_permissions(
        agent_id: UUID,
        permissions: list[AgentPermissionCreate],
        ctx: Context,
    ) -> list[dict[str, Any]]:
        """Replace all explicit user permissions for an agent."""
        async with tool_session(ctx) as (db, user, workspace_id):
            service = AgentService(db, workspace_id)
            await _require_agent(
                service,
                user,
                agent_id,
                EffectivePermission.admin,
                "manage this agent's permissions",
            )
            return to_json(await service.set_permissions(agent_id, permissions))

    @mcp.tool()
    async def check_agent_readiness(agent_id: UUID, ctx: Context) -> dict[str, Any]:
        """Check whether the caller can run an agent and what needs attention."""
        async with tool_session(ctx) as (db, user, workspace_id):
            service = AgentService(db, workspace_id)
            await _require_agent(
                service,
                user,
                agent_id,
                EffectivePermission.member,
                "use this agent",
            )
            return await service.describe_readiness(agent_id, str(user.id))

    # MCP servers

    @mcp.tool()
    async def list_official_mcp_servers(
        ctx: Context,
    ) -> list[dict[str, Any]]:
        """List templates from the official MCP server catalog."""
        async with tool_session(ctx) as (db, _user, workspace_id):
            return to_json(await MCPServerService(db, workspace_id).list_official())

    @mcp.tool()
    async def get_mcp_server(server_id: UUID, ctx: Context) -> dict[str, Any]:
        """Read one MCP server visible to the caller."""
        async with tool_session(ctx) as (db, user, workspace_id):
            service = MCPServerService(db, workspace_id)
            server = await service.get_visible(server_id, user)
            return to_json(await service.to_response(server))

    @mcp.tool()
    async def create_mcp_server(data: MCPServerCreate, ctx: Context) -> dict[str, Any]:
        """Create and configure an MCP server in the selected workspace."""
        async with tool_session(ctx, minimum_role=WorkspaceRole.admin) as (
            db,
            user,
            workspace_id,
        ):
            service = MCPServerService(db, workspace_id)
            return to_json(
                await service.to_response(await service.create(data, user.id))
            )

    @mcp.tool()
    async def update_mcp_server(
        server_id: UUID, data: MCPServerPatch, ctx: Context
    ) -> dict[str, Any]:
        """Update an MCP server, including write-only credentials."""
        async with tool_session(ctx, minimum_role=WorkspaceRole.admin) as (
            db,
            _user,
            workspace_id,
        ):
            service = MCPServerService(db, workspace_id)
            before = await service.get_scoped_for_update(server_id)
            previous_auth_type = before.auth_type
            previous_url = before.url
            oauth_credentials_changed = data.changes_oauth_credentials
            updated = await service.update(server_id, data)
            # Redis OAuth state cannot roll back, so persist the row first.
            await db.commit()
            await service.purge_invalidated_state(
                server_id,
                updated,
                previous_auth_type,
                previous_url,
                oauth_credentials_changed=oauth_credentials_changed,
            )
            return to_json(await service.to_response(updated))

    @mcp.tool()
    async def delete_mcp_server(
        server_id: UUID,
        ctx: Context,
        detach_agents: bool = False,
    ) -> dict[str, bool]:
        """Delete an MCP server, optionally detaching it from every agent."""
        async with tool_session(ctx, minimum_role=WorkspaceRole.admin) as (
            db,
            _user,
            workspace_id,
        ):
            service = MCPServerService(db, workspace_id)
            if detach_agents:
                await AgentMCPServerService(db, workspace_id).detach_server(server_id)
            await service.delete(server_id)
            await db.commit()
            await service.purge_server_data(server_id)
            return {"deleted": True}

    @mcp.tool()
    async def list_mcp_server_tools(server_id: UUID, ctx: Context) -> dict[str, Any]:
        """Discover a server's tools or return an OAuth authorization URL."""
        async with tool_session(ctx) as (db, user, workspace_id):
            service = MCPServerService(db, workspace_id)
            server = await service.get_visible(server_id, user)
            return to_json(await service.list_tools(server, str(user.id)))

    @mcp.tool()
    async def test_mcp_server(server_id: UUID, ctx: Context) -> dict[str, Any]:
        """Test a saved MCP server connection as the caller."""
        async with tool_session(ctx) as (db, user, workspace_id):
            service = MCPServerService(db, workspace_id)
            server = await service.get_visible(server_id, user)
            return to_json(
                await test_connection(server, str(user.id), workspace_id, db)
            )

    @mcp.tool()
    async def reset_mcp_server_connections(
        server_id: UUID, ctx: Context
    ) -> dict[str, Any]:
        """Revoke every user's OAuth connection to an MCP server."""
        async with tool_session(ctx, minimum_role=WorkspaceRole.admin) as (
            db,
            _user,
            workspace_id,
        ):
            return await MCPServerService(db, workspace_id).reset(server_id)

    # Models and providers

    @mcp.tool()
    async def list_model_configuration(
        ctx: Context,
    ) -> dict[str, Any]:
        """List all managed models and provider credential status."""
        async with tool_session(ctx, minimum_role=WorkspaceRole.admin) as (
            db,
            _user,
            workspace_id,
        ):
            service = ModelService(db, workspace_id)
            return {
                "providers": to_json(await service.list_provider_configs()),
                "models": to_json(await service.list_manage()),
            }

    @mcp.tool()
    async def set_model_provider_api_key(
        provider: str, api_key: str, ctx: Context
    ) -> dict[str, Any]:
        """Set a workspace model-provider API key. The value is write-only."""
        async with tool_session(ctx, minimum_role=WorkspaceRole.admin) as (
            db,
            _user,
            workspace_id,
        ):
            return to_json(
                await ModelService(db, workspace_id).set_provider_api_key(
                    provider, api_key
                )
            )

    @mcp.tool()
    async def delete_model_provider_api_key(
        provider: str, ctx: Context
    ) -> dict[str, Any]:
        """Delete a workspace model-provider API key."""
        async with tool_session(ctx, minimum_role=WorkspaceRole.admin) as (
            db,
            _user,
            workspace_id,
        ):
            return to_json(
                await ModelService(db, workspace_id).delete_provider_api_key(provider)
            )

    @mcp.tool()
    async def set_model_enabled(
        provider: str,
        model_id: str,
        is_enabled: bool,
        ctx: Context,
    ) -> dict[str, Any]:
        """Enable or disable one model for the workspace."""
        async with tool_session(ctx, minimum_role=WorkspaceRole.admin) as (
            db,
            _user,
            workspace_id,
        ):
            return to_json(
                await ModelService(db, workspace_id).set_enabled(
                    provider, model_id, is_enabled
                )
            )

    @mcp.tool()
    async def set_default_model(
        provider: str, model_id: str, ctx: Context
    ) -> dict[str, Any]:
        """Set the workspace default model."""
        async with tool_session(ctx, minimum_role=WorkspaceRole.admin) as (
            db,
            _user,
            workspace_id,
        ):
            return to_json(
                await ModelService(db, workspace_id).set_default(provider, model_id)
            )

    @mcp.tool()
    async def clear_default_model(ctx: Context) -> dict[str, bool]:
        """Return workspace model selection to automatic mode."""
        async with tool_session(ctx, minimum_role=WorkspaceRole.admin) as (
            db,
            _user,
            workspace_id,
        ):
            await ModelService(db, workspace_id).clear_default()
            return {"cleared": True}

    # Sandboxes

    @mcp.tool()
    async def list_sandboxes(ctx: Context) -> list[dict[str, Any]]:
        """List code-execution sandboxes in the workspace."""
        async with tool_session(ctx) as (db, _user, workspace_id):
            return to_json(await SandboxService(db, workspace_id).list_responses())

    @mcp.tool()
    async def get_sandbox(sandbox_id: UUID, ctx: Context) -> dict[str, Any]:
        """Read one sandbox configuration without exposing its secret."""
        async with tool_session(ctx, minimum_role=WorkspaceRole.admin) as (
            db,
            _user,
            workspace_id,
        ):
            return to_json(
                await SandboxService(db, workspace_id).get_response(sandbox_id)
            )

    @mcp.tool()
    async def create_sandbox(data: SandboxCreate, ctx: Context) -> dict[str, Any]:
        """Create a code-execution sandbox with a write-only secret."""
        async with tool_session(ctx, minimum_role=WorkspaceRole.admin) as (
            db,
            _user,
            workspace_id,
        ):
            return to_json(await SandboxService(db, workspace_id).create(data))

    @mcp.tool()
    async def update_sandbox(
        sandbox_id: UUID, data: SandboxPatch, ctx: Context
    ) -> dict[str, Any]:
        """Update a sandbox; an omitted secret preserves the stored value."""
        async with tool_session(ctx, minimum_role=WorkspaceRole.admin) as (
            db,
            _user,
            workspace_id,
        ):
            return to_json(
                await SandboxService(db, workspace_id).update(sandbox_id, data)
            )

    @mcp.tool()
    async def delete_sandbox(
        sandbox_id: UUID,
        ctx: Context,
        detach_agents: bool = False,
    ) -> dict[str, bool]:
        """Delete a sandbox, optionally detaching all bound agents."""
        async with tool_session(ctx, minimum_role=WorkspaceRole.admin) as (
            db,
            _user,
            workspace_id,
        ):
            if detach_agents:
                await AgentService(db, workspace_id).detach_sandbox(sandbox_id)
            await ThreadService(db, workspace_id).clear_sandbox(sandbox_id)
            await SandboxService(db, workspace_id).delete(sandbox_id)
            return {"deleted": True}

    # Teams and workspace membership

    @mcp.tool()
    async def list_teams(ctx: Context) -> list[dict[str, Any]]:
        """List teams in the selected workspace."""
        async with tool_session(ctx) as (db, _user, workspace_id):
            return to_json(await TeamService(db).list(workspace_id))

    @mcp.tool()
    async def create_team(data: TeamCreate, ctx: Context) -> dict[str, Any]:
        """Create a workspace team."""
        async with tool_session(ctx, minimum_role=WorkspaceRole.admin) as (
            db,
            _user,
            workspace_id,
        ):
            return to_json(await TeamService(db).create(data, workspace_id))

    @mcp.tool()
    async def update_team(
        team_id: UUID, data: TeamPatch, ctx: Context
    ) -> dict[str, Any]:
        """Update a workspace team."""
        async with tool_session(ctx, minimum_role=WorkspaceRole.admin) as (
            db,
            _user,
            workspace_id,
        ):
            return to_json(await TeamService(db).update(team_id, workspace_id, data))

    @mcp.tool()
    async def delete_team(team_id: UUID, ctx: Context) -> dict[str, bool]:
        """Delete a workspace team."""
        async with tool_session(ctx, minimum_role=WorkspaceRole.admin) as (
            db,
            _user,
            workspace_id,
        ):
            await TeamService(db).delete(team_id, workspace_id)
            return {"deleted": True}

    @mcp.tool()
    async def list_users(
        ctx: Context,
        role: WorkspaceRole | None = None,
        search: str | None = None,
        team_id: UUID | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        """List and search members of the selected workspace."""
        async with tool_session(ctx) as (db, _user, workspace_id):
            return to_json(
                await UserService(db).list(
                    workspace_id,
                    PageParams(limit=limit, offset=offset),
                    role=role,
                    search=search,
                    team_id=team_id,
                )
            )

    @mcp.tool()
    async def update_user(
        user_id: UUID, data: MCPUserPatch, ctx: Context
    ) -> dict[str, Any]:
        """Update a workspace user's administrative profile fields."""
        async with tool_session(ctx, minimum_role=WorkspaceRole.admin) as (
            db,
            _user,
            workspace_id,
        ):
            patch = UserPatch.model_validate(data.model_dump(exclude_unset=True))
            return to_json(await UserService(db).update(user_id, workspace_id, patch))

    @mcp.tool()
    async def set_user_role(
        user_id: UUID, data: UserRolePatch, ctx: Context
    ) -> dict[str, Any]:
        """Change a user's role in the selected workspace."""
        async with tool_session(ctx, minimum_role=WorkspaceRole.admin) as (
            db,
            _user,
            workspace_id,
        ):
            return to_json(
                await UserService(db).update_role(user_id, workspace_id, data)
            )

    @mcp.tool()
    async def set_user_team(
        user_id: UUID, data: UserTeamPatch, ctx: Context
    ) -> dict[str, Any]:
        """Assign or remove a user's team in the selected workspace."""
        async with tool_session(ctx, minimum_role=WorkspaceRole.admin) as (
            db,
            _user,
            workspace_id,
        ):
            return to_json(
                await UserService(db).update_team(user_id, workspace_id, data)
            )

    @mcp.tool()
    async def remove_user_from_workspace(
        user_id: UUID, ctx: Context
    ) -> dict[str, bool]:
        """Remove a user from the selected workspace."""
        async with tool_session(ctx, minimum_role=WorkspaceRole.admin) as (
            db,
            _user,
            workspace_id,
        ):
            await UserService(db).delete(user_id, workspace_id)
            await db.commit()
            try:
                await TokenStorageFactory().clear_user_data(
                    str(workspace_id), str(user_id)
                )
            except Exception:  # noqa: BLE001
                logger.warning(
                    "Could not purge MCP state for removed workspace user %s",
                    user_id,
                    exc_info=True,
                )
            return {"removed": True}

    @mcp.tool()
    async def list_invites(ctx: Context) -> list[dict[str, Any]]:
        """List pending invitations for the selected workspace."""
        async with tool_session(ctx, minimum_role=WorkspaceRole.admin) as (
            db,
            _user,
            workspace_id,
        ):
            service = InviteService(db)
            rows = await service.list_pending_with_inviters(workspace_id)
            return [
                to_json(
                    service._to_response(
                        invite,
                        include_url=True,
                        invited_by_name=inviter_name,
                    )
                )
                for invite, inviter_name in rows
            ]

    @mcp.tool()
    async def create_invite(data: InviteCreate, ctx: Context) -> dict[str, Any]:
        """Invite a user to the selected workspace."""
        async with tool_session(ctx, minimum_role=WorkspaceRole.admin) as (
            db,
            user,
            workspace_id,
        ):
            if data.workspace_id not in (None, workspace_id):
                raise PermissionDeniedError(
                    "OAuth tokens can only manage their selected workspace"
                )
            service = InviteService(db)
            invite = await service.create(
                email=str(data.email),
                role=data.role.value,
                invited_by=user.id,
                workspace_id=workspace_id,
                team_id=data.team_id,
            )
            return to_json(service._to_response(invite, include_url=True))

    @mcp.tool()
    async def revoke_invite(invite_id: UUID, ctx: Context) -> dict[str, bool]:
        """Revoke a pending workspace invitation."""
        async with tool_session(ctx, minimum_role=WorkspaceRole.admin) as (
            db,
            _user,
            workspace_id,
        ):
            invite = await InviteService(db).revoke(invite_id, workspace_id)
            if invite is None:
                raise NotFoundError("Invite not found")
            return {"revoked": True}

    # Skill repository sources

    @mcp.tool()
    async def list_skill_sources(ctx: Context) -> list[dict[str, Any]]:
        """List repositories connected to the workspace skill library."""
        async with tool_session(ctx) as (db, user, workspace_id):
            return to_json(await SkillSourceService(db, workspace_id).list(user))

    @mcp.tool()
    async def get_skill_source(source_id: UUID, ctx: Context) -> dict[str, Any]:
        """Read a skill repository and its last synchronization report."""
        async with tool_session(ctx) as (db, user, workspace_id):
            return to_json(
                await SkillSourceService(db, workspace_id).get(source_id, user)
            )

    @mcp.tool()
    async def preview_skill_source(
        data: SkillSourceCreate, ctx: Context
    ) -> dict[str, Any]:
        """Inspect and validate a skill repository before connecting it."""
        async with tool_session(ctx, minimum_role=WorkspaceRole.admin) as (
            db,
            _user,
            workspace_id,
        ):
            return to_json(await SkillSourceService(db, workspace_id).preview(data))

    @mcp.tool()
    async def create_skill_source(
        data: SkillSourceCreate, ctx: Context
    ) -> dict[str, Any]:
        """Connect a GitHub or GitLab skill repository."""
        async with tool_session(ctx, minimum_role=WorkspaceRole.admin) as (
            db,
            user,
            workspace_id,
        ):
            return to_json(
                await SkillSourceService(db, workspace_id).create(data, user)
            )

    @mcp.tool()
    async def update_skill_source(
        source_id: UUID, data: SkillSourcePatch, ctx: Context
    ) -> dict[str, Any]:
        """Update a skill repository reference, path, or write-only token."""
        async with tool_session(ctx, minimum_role=WorkspaceRole.admin) as (
            db,
            user,
            workspace_id,
        ):
            return to_json(
                await SkillSourceService(db, workspace_id).update(source_id, data, user)
            )

    @mcp.tool()
    async def plan_skill_source_sync(source_id: UUID, ctx: Context) -> dict[str, Any]:
        """Preview the changes that syncing a skill repository would make."""
        async with tool_session(ctx, minimum_role=WorkspaceRole.admin) as (
            db,
            user,
            workspace_id,
        ):
            return to_json(
                await SkillSourceService(db, workspace_id).plan(source_id, user)
            )

    @mcp.tool()
    async def sync_skill_source(source_id: UUID, ctx: Context) -> dict[str, Any]:
        """Fetch and synchronize a connected skill repository."""
        async with tool_session(ctx, minimum_role=WorkspaceRole.admin) as (
            db,
            user,
            workspace_id,
        ):
            return to_json(
                await SkillSourceService(db, workspace_id).sync(source_id, user)
            )

    @mcp.tool()
    async def delete_skill_source(source_id: UUID, ctx: Context) -> dict[str, bool]:
        """Disconnect a skill repository without deleting adopted skills."""
        async with tool_session(ctx, minimum_role=WorkspaceRole.admin) as (
            db,
            user,
            workspace_id,
        ):
            await SkillSourceService(db, workspace_id).delete(source_id, user)
            return {"deleted": True}

    # Workspace-wide integrations and settings

    @mcp.tool()
    async def get_workspace_authentication(ctx: Context) -> dict[str, Any]:
        """Read Google and password authentication settings for the workspace."""
        async with tool_session(ctx, minimum_role=WorkspaceRole.admin) as (
            db,
            _user,
            workspace_id,
        ):
            return to_json(
                await WorkspaceAuthenticationService(db).get_response(workspace_id)
            )

    @mcp.tool()
    async def set_workspace_authentication(
        data: WorkspaceAuthenticationUpdate, ctx: Context
    ) -> dict[str, Any]:
        """Configure Google authentication with write-only client credentials."""
        async with tool_session(ctx, minimum_role=WorkspaceRole.admin) as (
            db,
            _user,
            workspace_id,
        ):
            return to_json(
                await WorkspaceAuthenticationService(db).update(workspace_id, data)
            )

    @mcp.tool()
    async def clear_workspace_authentication(ctx: Context) -> dict[str, Any]:
        """Remove the workspace's Google authentication configuration."""
        async with tool_session(ctx, minimum_role=WorkspaceRole.admin) as (
            db,
            _user,
            workspace_id,
        ):
            return to_json(await WorkspaceAuthenticationService(db).clear(workspace_id))

    @mcp.tool()
    async def get_observability_settings(ctx: Context) -> dict[str, Any]:
        """Read the workspace's Langfuse observability settings."""
        async with tool_session(ctx, minimum_role=WorkspaceRole.admin) as (
            db,
            _user,
            workspace_id,
        ):
            return to_json(
                await WorkspaceObservabilityService(db).get_response(workspace_id)
            )

    @mcp.tool()
    async def set_observability_settings(
        data: WorkspaceObservabilityUpdate, ctx: Context
    ) -> dict[str, Any]:
        """Configure Langfuse with write-only credentials."""
        async with tool_session(ctx, minimum_role=WorkspaceRole.admin) as (
            db,
            _user,
            workspace_id,
        ):
            return to_json(
                await WorkspaceObservabilityService(db).update(workspace_id, data)
            )

    @mcp.tool()
    async def clear_observability_settings(ctx: Context) -> dict[str, Any]:
        """Remove the workspace's Langfuse configuration."""
        async with tool_session(ctx, minimum_role=WorkspaceRole.admin) as (
            db,
            _user,
            workspace_id,
        ):
            return to_json(await WorkspaceObservabilityService(db).clear(workspace_id))

    @mcp.tool()
    async def get_slack_notification_settings(ctx: Context) -> dict[str, Any]:
        """Read whether agent-specific Slack bots are enabled in the workspace."""
        async with tool_session(ctx, minimum_role=WorkspaceRole.admin) as (
            db,
            _user,
            workspace_id,
        ):
            return to_json(
                await SlackNotificationSettingsService(db).get_response(workspace_id)
            )

    @mcp.tool()
    async def set_slack_notification_settings(
        data: SlackNotificationSettingsUpdate, ctx: Context
    ) -> dict[str, Any]:
        """Enable or disable all agent-specific Slack bots in the workspace."""
        async with tool_session(ctx, minimum_role=WorkspaceRole.admin) as (
            db,
            _user,
            workspace_id,
        ):
            return to_json(
                await SlackNotificationSettingsService(db).update(workspace_id, data)
            )

    @mcp.tool()
    async def get_whatsapp_notification_settings(ctx: Context) -> dict[str, Any]:
        """Read whether agent-specific WhatsApp numbers are enabled."""
        async with tool_session(ctx, minimum_role=WorkspaceRole.admin) as (
            db,
            _user,
            workspace_id,
        ):
            return to_json(
                await WhatsAppWorkspaceSettingsService(db, workspace_id).get_response()
            )

    @mcp.tool()
    async def set_whatsapp_notification_settings(
        data: WhatsAppWorkspaceSettingsUpdate, ctx: Context
    ) -> dict[str, Any]:
        """Enable or disable all agent-specific WhatsApp numbers."""
        async with tool_session(ctx, minimum_role=WorkspaceRole.admin) as (
            db,
            _user,
            workspace_id,
        ):
            return to_json(
                await WhatsAppWorkspaceSettingsService(db, workspace_id).update(
                    data.enabled
                )
            )

    @mcp.tool()
    async def get_instance_appearance(ctx: Context) -> dict[str, Any]:
        """Read the application name and logo revision."""
        async with tool_session(ctx) as (db, _user, _workspace_id):
            return to_json(await InstanceAppearanceService(db).get_settings())

    @mcp.tool()
    async def set_instance_appearance(
        data: InstanceAppearancePatch, ctx: Context
    ) -> dict[str, Any]:
        """Change the application display name."""
        async with tool_session(ctx, minimum_role=WorkspaceRole.admin) as (
            db,
            _user,
            _workspace_id,
        ):
            return to_json(
                await InstanceAppearanceService(db).update_name(data.app_name)
            )

    # Per-agent Slack apps

    @mcp.tool()
    async def list_agent_slack_bots(
        agent_id: UUID, ctx: Context
    ) -> list[dict[str, Any]]:
        """List Slack apps connected to an agent."""
        async with tool_session(ctx) as (db, user, workspace_id):
            agents = AgentService(db, workspace_id)
            await _require_agent(
                agents,
                user,
                agent_id,
                EffectivePermission.member,
                "view this agent's Slack bots",
            )
            return to_json(
                await AgentSlackBotService(db, workspace_id).list_connections(agent_id)
            )

    @mcp.tool()
    async def create_agent_slack_bot(
        agent_id: UUID, data: AgentSlackBotUpdate, ctx: Context
    ) -> dict[str, Any]:
        """Connect a Slack app to an agent using write-only credentials."""
        async with tool_session(ctx) as (db, user, workspace_id):
            agents = AgentService(db, workspace_id)
            await _require_agent(
                agents,
                user,
                agent_id,
                EffectivePermission.admin,
                "configure this agent's Slack bots",
            )
            return to_json(
                await AgentSlackBotService(db, workspace_id).create(agent_id, data)
            )

    @mcp.tool()
    async def update_agent_slack_bot(
        agent_id: UUID,
        bot_id: UUID,
        data: AgentSlackBotUpdate,
        ctx: Context,
    ) -> dict[str, Any]:
        """Update an agent's Slack app configuration."""
        async with tool_session(ctx) as (db, user, workspace_id):
            agents = AgentService(db, workspace_id)
            await _require_agent(
                agents,
                user,
                agent_id,
                EffectivePermission.admin,
                "configure this agent's Slack bots",
            )
            return to_json(
                await AgentSlackBotService(db, workspace_id).update(
                    agent_id, bot_id, data
                )
            )

    @mcp.tool()
    async def delete_agent_slack_bot(
        agent_id: UUID, bot_id: UUID, ctx: Context
    ) -> dict[str, bool]:
        """Disconnect a Slack app from an agent."""
        async with tool_session(ctx) as (db, user, workspace_id):
            agents = AgentService(db, workspace_id)
            await _require_agent(
                agents,
                user,
                agent_id,
                EffectivePermission.admin,
                "configure this agent's Slack bots",
            )
            await AgentSlackBotService(db, workspace_id).delete(agent_id, bot_id)
            return {"deleted": True}

    # Per-agent WhatsApp connections

    @mcp.tool()
    async def list_agent_whatsapp_connections(
        agent_id: UUID, ctx: Context
    ) -> list[dict[str, Any]]:
        """List WhatsApp Cloud API connections for an agent."""
        async with tool_session(ctx) as (db, user, workspace_id):
            await _require_agent(
                AgentService(db, workspace_id),
                user,
                agent_id,
                EffectivePermission.member,
                "view this agent's WhatsApp connections",
            )
            return to_json(
                await WhatsAppConnectionService(db, workspace_id).list_connections(
                    agent_id
                )
            )

    @mcp.tool()
    async def create_agent_whatsapp_connection(
        agent_id: UUID, data: WhatsAppConnectionUpdate, ctx: Context
    ) -> dict[str, Any]:
        """Connect a WhatsApp Cloud API number to an agent."""
        async with tool_session(ctx) as (db, user, workspace_id):
            await _require_agent(
                AgentService(db, workspace_id),
                user,
                agent_id,
                EffectivePermission.admin,
                "configure this agent's WhatsApp connections",
            )
            return to_json(
                await WhatsAppConnectionService(db, workspace_id).create(agent_id, data)
            )

    @mcp.tool()
    async def update_agent_whatsapp_connection(
        agent_id: UUID,
        connection_id: UUID,
        data: WhatsAppConnectionUpdate,
        ctx: Context,
    ) -> dict[str, Any]:
        """Update an agent's WhatsApp Cloud API connection."""
        async with tool_session(ctx) as (db, user, workspace_id):
            await _require_agent(
                AgentService(db, workspace_id),
                user,
                agent_id,
                EffectivePermission.admin,
                "configure this agent's WhatsApp connections",
            )
            return to_json(
                await WhatsAppConnectionService(db, workspace_id).update(
                    agent_id, connection_id, data
                )
            )

    @mcp.tool()
    async def delete_agent_whatsapp_connection(
        agent_id: UUID, connection_id: UUID, ctx: Context
    ) -> dict[str, bool]:
        """Disconnect a WhatsApp Cloud API number from an agent."""
        async with tool_session(ctx) as (db, user, workspace_id):
            await _require_agent(
                AgentService(db, workspace_id),
                user,
                agent_id,
                EffectivePermission.admin,
                "configure this agent's WhatsApp connections",
            )
            await WhatsAppConnectionService(db, workspace_id).delete(
                agent_id, connection_id
            )
            return {"deleted": True}

    # Remaining skill and workspace operations

    @mcp.tool()
    async def list_skill_agents(skill_id: UUID, ctx: Context) -> list[dict[str, Any]]:
        """List visible agents currently using a skill."""
        async with tool_session(ctx) as (db, user, workspace_id):
            return to_json(
                await SkillService(db, workspace_id).list_bound_agents(skill_id, user)
            )

    @mcp.tool()
    async def get_current_workspace(ctx: Context) -> dict[str, Any]:
        """Read the workspace selected when this OAuth grant was approved."""
        async with tool_session(ctx) as (db, user, workspace_id):
            workspaces = await WorkspaceService(db).list_for_user(user.id)
            workspace = next(
                (item for item in workspaces if item.id == workspace_id), None
            )
            if workspace is None:
                raise NotFoundError("Workspace not found")
            return to_json(workspace)

    @mcp.tool()
    async def update_current_workspace(
        data: WorkspacePatch, ctx: Context
    ) -> dict[str, Any]:
        """Update the name, emoji, or color of the selected workspace."""
        async with tool_session(ctx) as (db, user, workspace_id):
            return to_json(
                await WorkspaceService(db).update(workspace_id, user.id, data)
            )

    @mcp.tool()
    async def list_agent_conversations(
        agent_id: UUID,
        ctx: Context,
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        """List conversations across users for an agent owner or admin."""
        async with tool_session(ctx) as (db, user, workspace_id):
            agents = AgentService(db, workspace_id)
            await _require_agent(
                agents,
                user,
                agent_id,
                EffectivePermission.admin,
                "view this agent's conversations",
            )
            return to_json(
                await ThreadService(db, workspace_id).list_for_agent(
                    agent_id, PageParams(limit=limit, offset=offset)
                )
            )

    @mcp.tool()
    async def permanently_delete_agent(agent_id: UUID, ctx: Context) -> dict[str, bool]:
        """Permanently delete an archived agent and all of its conversations."""
        async with tool_session(ctx) as (db, user, workspace_id):
            agents = AgentService(db, workspace_id)
            await _require_agent(
                agents,
                user,
                agent_id,
                EffectivePermission.admin,
                "permanently delete this agent",
                include_archived=True,
            )
            threads = ThreadService(db, workspace_id)
            thread_ids = await threads.delete_rows_for_agent(agent_id)
            await agents.delete_permanently(agent_id)
            await db.commit()
            try:
                await threads.purge_checkpoints(thread_ids)
            except Exception:  # noqa: BLE001
                logger.warning(
                    "Agent %s was deleted but its checkpoints remain",
                    agent_id,
                    exc_info=True,
                )
            return {"deleted": True}

    _apply_tool_annotations(mcp)
