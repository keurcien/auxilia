from __future__ import annotations

import logging
from collections import defaultdict
from typing import Literal, overload
from uuid import UUID, uuid4

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.core.repository import AgentRepository
from app.agents.mcp_servers.repository import AgentMCPServerRepository
from app.agents.mcp_servers.service import AgentMCPServerService
from app.agents.models import (
    AgentDB,
    AgentImageDB,
    AgentMCPServerDB,
    AgentSubagentDB,
    AgentUserPermissionDB,
    EffectivePermission,
    PermissionLevel,
    ToolDiscoveryMode,
    ToolStatus,
)
from app.agents.schemas import (
    AgentConfig,
    AgentCreateDB,
    AgentListResponse,
    AgentMCPServerListResponse,
    AgentMCPServerResponse,
    AgentOwnerInfo,
    AgentPatch,
    AgentPermissionCreate,
    AgentResourceMCPServerResponse,
    AgentResourceSandboxResponse,
    AgentResourcesResponse,
    AgentResponse,
    AgentSandboxConfig,
    AgentSandboxResponse,
    AgentSkillResponse,
    SubagentResponse,
)
from app.artifacts.settings import artifact_settings
from app.database import get_db
from app.database_connections.models import DATABASE_ENGINE_ICON_URLS
from app.database_connections.repository import DatabaseConnectionRepository
from app.database_connections.tools import DBHUB_MANAGED_BY, allowed_tool_names
from app.exceptions import (
    DomainValidationError,
    NotFoundError,
    PermissionDeniedError,
    SandboxUnavailableError,
)
from app.mcp.client.connectivity import probe_authorization
from app.mcp.servers.repository import MCPServerRepository
from app.model_providers.service import ModelService
from app.realtime.schemas import WorkspaceEventKind
from app.realtime.service import stage_workspace_event
from app.sandbox.provider import ensure_sandboxes_available
from app.sandbox.repository import SandboxRepository
from app.sandbox.schemas import SandboxAgentResponse
from app.service import BaseService
from app.skills.service import SkillService
from app.teams.repository import TeamRepository
from app.users.models import WorkspaceRole
from app.users.service import UserService
from app.utils.images import ProcessedImage
from app.visibility import (
    ResourceVisibility,
    audience_contains,
    is_resource_visible_to_identity,
    validate_visibility,
)
from app.workspaces.dependencies import get_active_workspace_id
from app.workspaces.models import WorkspaceMembershipDB
from app.workspaces.repository import WorkspaceRepository


logger = logging.getLogger(__name__)


class AgentService(BaseService[AgentDB, AgentRepository]):
    not_found_message = "Agent not found"

    def __init__(self, db: AsyncSession, workspace_id: UUID | None = None):
        super().__init__(db, AgentRepository(db, workspace_id))
        self.workspace_id = workspace_id
        self.user_service = UserService(db)
        self.mcp_server_repository = AgentMCPServerRepository(db)
        self.mcp_server_service = AgentMCPServerService(db, workspace_id)
        self.skill_service = SkillService(db, workspace_id)
        self.mcp_servers = MCPServerRepository(db, workspace_id)
        self.sandboxes = SandboxRepository(db)
        self.workspaces = WorkspaceRepository(db)
        self.teams = TeamRepository(db)

    async def _stage_agents_changed(self) -> None:
        if self.workspace_id is None:
            raise RuntimeError("workspace_id is required to publish agent changes")
        await stage_workspace_event(
            self.db,
            workspace_id=self.workspace_id,
            kind=WorkspaceEventKind.agents,
        )

    async def _validate_model_defaults(
        self, model_id: str | None, reasoning_effort: str | None
    ) -> None:
        if model_id is None:
            if reasoning_effort is not None:
                raise DomainValidationError(
                    "A default reasoning effort requires a default model."
                )
            return
        if self.workspace_id is None:
            raise RuntimeError("workspace_id is required to validate model defaults")
        await ModelService(self.db, self.workspace_id).ensure_available(model_id)
        await ModelService.validate_reasoning_effort(model_id, reasoning_effort)

    async def _get_scoped(self, agent_id: UUID) -> AgentDB:
        row = await self.repository.get_scoped(agent_id)
        if row is None:
            raise NotFoundError(self.not_found_message)
        return row

    async def get_image(self, agent_id: UUID) -> AgentImageDB:
        await self._get_scoped(agent_id)
        image = await self.repository.get_image(agent_id)
        if image is None:
            raise NotFoundError("Agent image not found")
        return image

    async def get_resources(self, agent_id: UUID) -> AgentResourcesResponse:
        spec = await self.repository.get_run_spec(agent_id)
        if spec is None:
            raise NotFoundError(self.not_found_message)

        server_ids = list(
            dict.fromkeys(binding.mcp_server_id for binding in spec.all_mcp_bindings)
        )
        server_rows = {
            server.id: server
            for server in await self.mcp_servers.list_by_ids(server_ids)
        }
        managed_connections = await DatabaseConnectionRepository(
            self.db, self.workspace_id
        ).list_by_ids(
            [
                server.managed_resource_id
                for server in server_rows.values()
                if server.managed_by == DBHUB_MANAGED_BY
                and server.managed_resource_id is not None
            ]
        )
        managed_icons = {
            connection.id: DATABASE_ENGINE_ICON_URLS[connection.engine]
            for connection in managed_connections
        }
        configured_by_id = {
            server_id: all(
                binding.tools is not None
                for binding in spec.all_mcp_bindings
                if binding.mcp_server_id == server_id
            )
            for server_id in server_ids
        }
        tool_names_by_id: dict[UUID, list[str]] = {}
        for server_id in server_ids:
            server = server_rows.get(server_id)
            if server is None:
                continue
            managed_allowed = (
                allowed_tool_names(server.managed_resource_id)
                if server.managed_by == DBHUB_MANAGED_BY
                and server.managed_resource_id is not None
                else None
            )
            tool_names_by_id[server_id] = list(
                dict.fromkeys(
                    name
                    for binding in spec.all_mcp_bindings
                    if binding.mcp_server_id == server_id
                    for name, status in (binding.tools or {}).items()
                    if status != ToolStatus.disabled
                    and name not in server.disabled_tools
                    and (managed_allowed is None or name in managed_allowed)
                )
            )
        mcp_servers = [
            AgentResourceMCPServerResponse(
                id=server.id,
                name=server.name,
                icon_url=server.icon_url
                or (
                    managed_icons.get(server.managed_resource_id)
                    if server.managed_resource_id is not None
                    else None
                ),
                image_revision=server.image_revision,
                description=server.description,
                tool_names=tool_names_by_id.get(server_id, []),
                configured=configured_by_id[server_id],
                enabled_by_default=all(
                    binding.enabled_by_default
                    for binding in spec.all_mcp_bindings
                    if binding.mcp_server_id == server_id
                ),
            )
            for server_id in server_ids
            if (server := server_rows.get(server_id)) is not None
        ]
        skills = await self.skill_service.list_for_agents(spec.all_agent_ids)
        sandbox_rows = {
            sandbox.id: sandbox for sandbox in spec.all_sandbox_rows
        }.values()
        sandboxes = [
            AgentResourceSandboxResponse(
                id=sandbox.id,
                name=sandbox.name,
                description=sandbox.description,
                provider=sandbox.provider,
                image_revision=sandbox.image_revision,
                enabled_by_default=all(
                    spec_agent.sandbox.enabled_by_default
                    for spec_agent in [spec.agent, *spec.subagents]
                    if spec_agent.sandbox is not None
                    and spec_agent.sandbox.row.id == sandbox.id
                ),
            )
            for sandbox in sandbox_rows
        ]
        subagent_rows = await self.repository.list_by_ids(
            subagent.id for subagent in spec.subagents
        )
        subagents_by_id = {subagent.id: subagent for subagent in subagent_rows}
        subagents = [
            SubagentResponse(
                id=subagent.id,
                name=subagent.name,
                emoji=subagent.emoji,
                color=subagent.color,
                image_revision=subagent.image_revision,
                description=subagent.description,
                enabled_by_default=spec_subagent.enabled_by_default,
            )
            for spec_subagent in spec.subagents
            if (subagent := subagents_by_id.get(spec_subagent.id)) is not None
        ]
        return AgentResourcesResponse(
            mcp_servers=mcp_servers,
            skills=skills,
            sandboxes=sandboxes,
            subagents=subagents,
        )

    async def set_image(self, agent_id: UUID, image: ProcessedImage) -> UUID:
        await self._get_scoped(agent_id)
        revision = uuid4()
        await self.repository.set_image(
            agent_id,
            data=image.data,
            media_type=image.media_type,
            sha256=image.sha256,
            revision=revision,
        )
        await self._stage_agents_changed()
        return revision

    async def delete_image(self, agent_id: UUID) -> None:
        await self._get_scoped(agent_id)
        await self.repository.delete_image(agent_id)
        await self._stage_agents_changed()

    @staticmethod
    def _resolve_permission(
        *,
        owner_id: UUID,
        user_id: UUID | None,
        user_role: WorkspaceRole | None,
        granted: PermissionLevel | None,
        team_member: bool = False,
        visibility: ResourceVisibility = ResourceVisibility.personal,
    ) -> EffectivePermission | None:
        """Resolve one user's access to one agent. Two callers feed it: the
        list/detail assembly (from maps built by one joined query) and
        `require_permission` (from `AgentRepository.get_access`'s single row).
        """
        if user_id and owner_id == user_id:
            return EffectivePermission.owner
        if user_role == WorkspaceRole.admin:
            return EffectivePermission.admin
        if granted is not None:
            return EffectivePermission(granted.value)
        if visibility == ResourceVisibility.workspace:
            return EffectivePermission.member
        if team_member:
            return EffectivePermission.member
        return None

    async def require_permission(
        self,
        agent_id: UUID,
        *,
        at_least: EffectivePermission,
        action: str,
        user_id: UUID | None = None,
        user_role: WorkspaceRole | None = None,
        user_team_id: UUID | None = None,
        include_archived: bool = False,
    ) -> EffectivePermission:
        """The single gate on agent access — every check goes through here.

        Raises `NotFoundError` for an agent the caller cannot see at all and
        `PermissionDeniedError` when their permission is weaker than
        `at_least`; `action` completes the sentence "Not authorized to …".

        It costs one narrow query, not a full `get`: gates run on endpoints
        that then do their own reads (and on one the frontend polls), so
        resolving the permission must not drag the whole detail assembly
        along.
        """
        access = await self.repository.get_access(
            agent_id,
            user_id=user_id,
            user_team_id=user_team_id,
            include_archived=include_archived,
        )
        if access is None:
            raise NotFoundError(self.not_found_message)
        permission = self._resolve_permission(
            owner_id=access.owner_id,
            visibility=access.visibility,
            user_id=user_id,
            user_role=user_role,
            granted=access.granted,
            team_member=access.team_member,
        )
        if permission is None or not permission.covers(at_least):
            raise PermissionDeniedError(f"Not authorized to {action}")
        return permission

    @overload
    async def _assemble(
        self,
        agents: list[AgentDB],
        mcp_map: dict[UUID, list[AgentMCPServerResponse | AgentMCPServerListResponse]],
        permissions_map: dict[UUID, PermissionLevel],
        user_id: UUID | None,
        user_role: WorkspaceRole | None,
        team_agent_ids: set[UUID] | None = ...,
        *,
        slim: Literal[False] = ...,
    ) -> list[AgentResponse]: ...

    @overload
    async def _assemble(
        self,
        agents: list[AgentDB],
        mcp_map: dict[UUID, list[AgentMCPServerResponse | AgentMCPServerListResponse]],
        permissions_map: dict[UUID, PermissionLevel],
        user_id: UUID | None,
        user_role: WorkspaceRole | None,
        team_agent_ids: set[UUID] | None = ...,
        *,
        slim: Literal[True],
    ) -> list[AgentListResponse]: ...

    async def _assemble(  # type: ignore[misc]  # impl is wider than overload 1
        self,
        agents: list[AgentDB],
        mcp_map: dict[UUID, list[AgentMCPServerResponse | AgentMCPServerListResponse]],
        permissions_map: dict[UUID, PermissionLevel],
        user_id: UUID | None,
        user_role: WorkspaceRole | None,
        team_agent_ids: set[UUID] | None = None,
        *,
        slim: bool = False,
    ) -> list[AgentListResponse]:
        """Hydrate agent rows into responses.

        Overloaded on `slim` because the two modes return different types and
        `get` needs the full one: `AgentResponse` is a *subclass* of
        `AgentListResponse`, so a single widened annotation would silently make
        `get`'s own `-> AgentResponse` contract unprovable.

        ``slim`` is the list projection: `AgentListResponse` instead of
        `AgentResponse`, which is not just a narrower serialization but a
        narrower *read* — the rows arrive without `instructions` (see
        `AgentRepository.LIST_COLUMNS`), and sandbox bindings, which only the
        detail response carries, are not queried at all.
        """
        agent_ids = [a.id for a in agents]
        visibility_teams = (
            await self.repository.list_team_ids(agent_ids)
            if any(agent.visibility == ResourceVisibility.teams for agent in agents)
            else {}
        )
        subagents_map, is_subagent_ids = await self._list_subagent_data(agent_ids)
        sandbox_map: dict[UUID, list[AgentSandboxResponse]] = defaultdict(list)
        skills_map: dict[UUID, list[AgentSkillResponse]] = {}
        if not slim:
            # Only the detail response carries bindings; `get` reads one agent.
            for agent_id in agent_ids:
                skills_map[agent_id] = await self.skill_service.list_for_agent(agent_id)
            for link, sandbox in await self.repository.list_sandbox_bindings(agent_ids):
                sandbox_map[link.agent_id].append(
                    AgentSandboxResponse(
                        sandbox_id=sandbox.id,
                        enabled_by_default=link.enabled_by_default,
                        tools=link.tools,
                        name=sandbox.name,
                        provider=sandbox.provider,
                        url=sandbox.url,
                        image_revision=sandbox.image_revision,
                    )
                )
        owner_ids = list({a.owner_id for a in agents})
        owners_by_id = {u.id: u for u in await self.user_service.list_by_ids(owner_ids)}
        response_cls = AgentListResponse if slim else AgentResponse
        return [
            response_cls(
                **agent.model_dump(),
                team_ids=visibility_teams.get(agent.id, []),
                mcp_servers=mcp_map.get(agent.id, []),
                **(
                    {}
                    if slim
                    else {
                        "sandboxes": sandbox_map.get(agent.id, []),
                        "skills": skills_map.get(agent.id, []),
                    }
                ),
                subagents=subagents_map.get(agent.id, []),
                owner=(
                    AgentOwnerInfo(
                        id=owner.id,
                        name=owner.name,
                        email=owner.email,
                        picture_url=owner.picture_url,
                        image_revision=owner.image_revision,
                    )
                    if (owner := owners_by_id.get(agent.owner_id)) is not None
                    else None
                ),
                is_subagent=agent.id in is_subagent_ids,
                current_user_permission=self._resolve_permission(
                    owner_id=agent.owner_id,
                    visibility=agent.visibility,
                    user_id=user_id,
                    user_role=user_role,
                    granted=permissions_map.get(agent.id),
                    team_member=agent.id in team_agent_ids if team_agent_ids else False,
                ),
            )
            for agent in agents
        ]

    @staticmethod
    def _group_rows(
        rows: list,
        user_id: UUID | None,
        *,
        slim: bool = False,
    ) -> tuple[
        dict[UUID, AgentDB],
        dict[UUID, list[AgentMCPServerResponse | AgentMCPServerListResponse]],
        dict[UUID, PermissionLevel],
        set[UUID],
    ]:
        """Collapse the join's fan-out into per-agent maps.

        `slim` must match the flag the rows were read with: a slim binding row
        has no per-tool map loaded, and validating it into the full
        `AgentMCPServerResponse` would fetch one per row.
        """
        binding_cls = AgentMCPServerListResponse if slim else AgentMCPServerResponse
        agents_map: dict[UUID, AgentDB] = {}
        mcp_map: dict[
            UUID, list[AgentMCPServerResponse | AgentMCPServerListResponse]
        ] = defaultdict(list)
        permissions_map: dict[UUID, PermissionLevel] = {}
        team_agent_ids: set[UUID] = set()
        for row in rows:
            agent = row[0]
            link = row[1]
            agents_map[agent.id] = agent
            if link is not None:
                mcp_map[agent.id].append(binding_cls.model_validate(link))
            if user_id and len(row) > 2:
                permission = row[2]
                if permission and agent.id not in permissions_map:
                    permissions_map[agent.id] = permission
            if user_id and len(row) > 3 and row[3] is not None:
                team_agent_ids.add(agent.id)
        return agents_map, mcp_map, permissions_map, team_agent_ids

    async def create_from_config(
        self,
        config: AgentConfig,
        *,
        owner_id: UUID,
        user_role: WorkspaceRole | None = None,
        user_team_id: UUID | None = None,
    ) -> AgentResponse:
        """Create an agent from a full config document in one transaction —
        the create-mode counterpart of `set_config`. Nothing persists if any
        binding is invalid, so a failed draft never leaves a stray agent."""
        if self.workspace_id is None:
            raise RuntimeError("workspace_id is required to create an agent")
        await self._validate_model_defaults(
            config.default_model_id, config.default_reasoning_effort
        )
        agent = await self.repository.create(
            AgentCreateDB(
                workspace_id=self.workspace_id,
                name=config.name,
                instructions=config.instructions,
                owner_id=owner_id,
                emoji=config.emoji,
                color=config.color,
                description=config.description,
                group=config.group,
                visibility=config.visibility,
                web_search_enabled=config.web_search_enabled,
                tool_discovery_mode=config.tool_discovery_mode,
                default_model_id=config.default_model_id,
                default_reasoning_effort=config.default_reasoning_effort,
            )
        )
        validate_visibility(config.visibility, config.team_ids)
        if config.team_ids:
            await self.set_teams(agent.id, config.team_ids)
        await self.mcp_server_service.set_for_agent(agent.id, config.mcp_servers)
        await self.set_sandboxes(agent.id, config.sandboxes)
        if config.disabled_subagent_ids_by_default:
            await self.set_subagents(
                agent.id,
                config.subagent_ids,
                disabled_by_default=config.disabled_subagent_ids_by_default,
                user_id=owner_id,
                user_role=user_role,
                user_team_id=user_team_id,
            )
        else:
            await self.set_subagents(
                agent.id,
                config.subagent_ids,
                user_id=owner_id,
                user_role=user_role,
                user_team_id=user_team_id,
            )
        if config.disabled_skill_ids_by_default:
            await self.skill_service.set_for_agent(
                agent.id,
                config.skill_ids,
                disabled_by_default=config.disabled_skill_ids_by_default,
            )
        else:
            await self.skill_service.set_for_agent(agent.id, config.skill_ids)
        response = await self.get(
            agent.id, user_id=owner_id, user_role=user_role, user_team_id=user_team_id
        )
        await self._stage_agents_changed()
        return response

    async def get(
        self,
        agent_id: UUID,
        user_id: UUID | None = None,
        user_role: WorkspaceRole | None = None,
        user_team_id: UUID | None = None,
        include_archived: bool = False,
    ) -> AgentResponse:
        rows = await self.repository.list_with_permissions(
            user_id=user_id,
            user_role=user_role,
            user_team_id=user_team_id,
            agent_id=agent_id,
            include_archived=include_archived,
        )
        if not rows:
            raise NotFoundError(self.not_found_message)

        agents_map, mcp_map, permissions_map, team_agent_ids = self._group_rows(
            rows, user_id
        )
        responses = await self._assemble(
            list(agents_map.values()),
            mcp_map,
            permissions_map,
            user_id,
            user_role,
            team_agent_ids,
        )
        if (user_id is not None or user_role is not None) and responses[
            0
        ].current_user_permission is None:
            raise NotFoundError(self.not_found_message)
        return responses[0]

    async def list(
        self,
        user_id: UUID | None = None,
        user_role: WorkspaceRole | None = None,
        user_team_id: UUID | None = None,
        archived: bool = False,
    ) -> list[AgentListResponse]:
        """The list projection — `AgentListResponse`, read as narrowly as it is
        rendered. It is not an `AgentResponse` with fields hidden at
        serialization time: `instructions` and the bindings' per-tool maps never
        leave the database, and no caller of this method wants them (§3.5)."""
        rows = await self.repository.list_with_permissions(
            user_id=user_id,
            user_role=user_role,
            user_team_id=user_team_id,
            archived_only=archived,
            slim=True,
        )
        agents_map, mcp_map, permissions_map, team_agent_ids = self._group_rows(
            rows, user_id, slim=True
        )
        responses = await self._assemble(
            list(agents_map.values()),
            mcp_map,
            permissions_map,
            user_id,
            user_role,
            team_agent_ids,
            slim=True,
        )
        return responses

    async def update(
        self,
        agent_id: UUID,
        data: AgentPatch,
        user_id: UUID | None = None,
        user_role: WorkspaceRole | None = None,
        user_team_id: UUID | None = None,
    ) -> AgentResponse:
        if data.visibility is not None:
            raise DomainValidationError(
                "Agent visibility must be changed through the config endpoint"
            )
        await self.require_permission(
            agent_id,
            at_least=EffectivePermission.editor,
            action="edit this agent",
            user_id=user_id,
            user_role=user_role,
            user_team_id=user_team_id,
        )
        if {
            "default_model_id",
            "default_reasoning_effort",
        } & data.model_fields_set:
            current = await self._get_scoped(agent_id)
            await self._validate_model_defaults(
                (
                    data.default_model_id
                    if "default_model_id" in data.model_fields_set
                    else current.default_model_id
                ),
                (
                    data.default_reasoning_effort
                    if "default_reasoning_effort" in data.model_fields_set
                    else current.default_reasoning_effort
                ),
            )
        await self.repository.update_by_id(agent_id, data)
        response = await self.get(
            agent_id, user_id=user_id, user_role=user_role, user_team_id=user_team_id
        )
        await self._stage_agents_changed()
        return response

    async def set_default(
        self,
        agent_id: UUID,
        *,
        user_id: UUID,
        user_role: WorkspaceRole,
        user_team_id: UUID | None = None,
    ) -> AgentResponse:
        """Make one active agent the workspace-wide default."""
        await self.require_permission(
            agent_id,
            at_least=EffectivePermission.editor,
            action="set this agent as the workspace default",
            user_id=user_id,
            user_role=user_role,
            user_team_id=user_team_id,
        )
        if self.workspace_id is None:
            raise RuntimeError("workspace_id is required to set a default agent")

        # The workspace row is the shared lock even when no default exists yet.
        # That keeps two concurrent requests from racing the partial unique index.
        if not await self.workspaces.lock_for_update(self.workspace_id):
            raise NotFoundError("Workspace not found")
        agent = await self.repository.get_scoped_for_update(agent_id)
        if agent is None:
            raise NotFoundError(self.not_found_message)
        if agent.is_archived:
            raise DomainValidationError(
                "An archived agent cannot be the workspace default"
            )

        await self.repository.set_default(agent_id)
        response = await self.get(
            agent_id,
            user_id=user_id,
            user_role=user_role,
            user_team_id=user_team_id,
        )
        await self._stage_agents_changed()
        return response

    async def clear_default(
        self,
        agent_id: UUID,
        *,
        user_id: UUID,
        user_role: WorkspaceRole,
        user_team_id: UUID | None = None,
    ) -> AgentResponse:
        """Remove this agent as the workspace default, leaving none selected."""
        await self.require_permission(
            agent_id,
            at_least=EffectivePermission.editor,
            action="clear this agent as the workspace default",
            user_id=user_id,
            user_role=user_role,
            user_team_id=user_team_id,
        )
        if self.workspace_id is None:
            raise RuntimeError("workspace_id is required to clear a default agent")

        if not await self.workspaces.lock_for_update(self.workspace_id):
            raise NotFoundError("Workspace not found")
        if await self.repository.get_scoped_for_update(agent_id) is None:
            raise NotFoundError(self.not_found_message)

        await self.repository.clear_default(agent_id)
        response = await self.get(
            agent_id,
            user_id=user_id,
            user_role=user_role,
            user_team_id=user_team_id,
        )
        await self._stage_agents_changed()
        return response

    async def set_config(
        self,
        agent_id: UUID,
        config: AgentConfig,
        user_id: UUID,
        user_role: WorkspaceRole | None = None,
        user_team_id: UUID | None = None,
    ) -> AgentResponse:
        """Atomic whole-config replace: scalars, MCP bindings, subagents and
        skills in one request transaction. The client carries complete per-tool
        maps (or None = never synced); model defaults are validated centrally."""
        await self.require_permission(
            agent_id,
            at_least=EffectivePermission.editor,
            action="edit this agent",
            user_id=user_id,
            user_role=user_role,
            user_team_id=user_team_id,
        )
        await self._validate_model_defaults(
            config.default_model_id, config.default_reasoning_effort
        )
        current_agent = await self.repository.get_scoped_for_update(agent_id)
        if not isinstance(current_agent, AgentDB):
            raise NotFoundError(self.not_found_message)
        stored_team_ids = (
            await self.repository.get_team_ids(agent_id)
            if current_agent.visibility == ResourceVisibility.teams
            else []
        )
        visibility = (
            config.visibility
            if "visibility" in config.model_fields_set
            else current_agent.visibility
        )
        team_ids = (
            config.team_ids
            if "team_ids" in config.model_fields_set
            else stored_team_ids
        )
        validate_visibility(visibility, team_ids)
        current_team_ids = set(stored_team_ids)
        scope_changed = (
            current_agent.visibility != visibility or current_team_ids != set(team_ids)
        )
        if scope_changed:
            await self._validate_trigger_dependencies_for_scope(
                agent_id, visibility, set(team_ids)
            )
            await self._validate_subagent_dependencies_for_scope(
                agent_id, visibility, set(team_ids)
            )
            await self._validate_bound_dependencies_for_scope(
                agent_id, visibility, set(team_ids)
            )
            await self._validate_team_ids(team_ids)
            await self.repository.set_teams(agent_id, team_ids)

        await self.repository.update_by_id(
            agent_id,
            AgentPatch(
                name=config.name,
                instructions=config.instructions,
                description=config.description,
                emoji=config.emoji,
                color=config.color,
                group=config.group,
                visibility=visibility,
                web_search_enabled=config.web_search_enabled,
                tool_discovery_mode=config.tool_discovery_mode,
                default_model_id=config.default_model_id,
                default_reasoning_effort=config.default_reasoning_effort,
            ),
        )
        await self.mcp_server_service.set_for_agent(agent_id, config.mcp_servers)
        await self.set_sandboxes(agent_id, config.sandboxes)
        if config.disabled_subagent_ids_by_default:
            await self.set_subagents(
                agent_id,
                config.subagent_ids,
                disabled_by_default=config.disabled_subagent_ids_by_default,
                user_id=user_id,
                user_role=user_role,
                user_team_id=user_team_id,
            )
        else:
            await self.set_subagents(
                agent_id,
                config.subagent_ids,
                user_id=user_id,
                user_role=user_role,
                user_team_id=user_team_id,
            )
        if config.disabled_skill_ids_by_default:
            await self.skill_service.set_for_agent(
                agent_id,
                config.skill_ids,
                disabled_by_default=config.disabled_skill_ids_by_default,
            )
        else:
            await self.skill_service.set_for_agent(agent_id, config.skill_ids)
        response = await self.get(
            agent_id, user_id=user_id, user_role=user_role, user_team_id=user_team_id
        )
        await self._stage_agents_changed()
        return response

    async def _validate_trigger_dependencies_for_scope(
        self,
        agent_id: UUID,
        visibility: ResourceVisibility,
        team_ids: set[UUID],
    ) -> None:
        from app.projects.repository import ProjectRepository
        from app.triggers.repository import TriggerRepository

        agent = await self.repository.get_scoped(agent_id)
        if agent is None:
            raise NotFoundError(self.not_found_message)
        granted_user_ids = {
            grant.user_id for grant in await self.repository.get_permissions(agent_id)
        }
        triggers = TriggerRepository(self.db, self.workspace_id)
        projects = ProjectRepository(self.db, self.workspace_id)
        for trigger in await triggers.list_for_agent(agent_id):
            membership = await self.workspaces.get_membership(
                self.workspace_id, trigger.owner_id
            )
            owner_can_execute = (
                trigger.owner_id == agent.owner_id
                or trigger.owner_id in granted_user_ids
                or (
                    membership is not None
                    and is_resource_visible_to_identity(
                        visibility=visibility,
                        owner_id=agent.owner_id,
                        team_ids=team_ids,
                        user_id=trigger.owner_id,
                        is_admin=membership.role == WorkspaceRole.admin,
                        team_id=membership.team_id,
                    )
                )
            )
            if not owner_can_execute:
                raise DomainValidationError(
                    f"Agent scope would prevent trigger owner from running "
                    f"'{trigger.name}'"
                )
            effective_visibility = trigger.visibility
            effective_owner_id = trigger.owner_id
            if trigger.project_id is not None:
                project = await projects.get(trigger.project_id)
            else:
                project = None
            if project is not None:
                effective_visibility = project.visibility
                effective_owner_id = project.owner_id
                trigger_team_ids = (
                    set(await projects.list_team_ids(project.id))
                    if project.visibility == ResourceVisibility.teams
                    else set()
                )
            else:
                trigger_team_ids = (
                    set(await triggers.list_team_ids(trigger.id))
                    if trigger.visibility == ResourceVisibility.teams
                    else set()
                )
            compatible = audience_contains(
                parent_visibility=effective_visibility,
                parent_owner_id=effective_owner_id,
                parent_team_ids=trigger_team_ids,
                child_visibility=visibility,
                child_owner_id=agent.owner_id,
                child_team_ids=team_ids,
            )
            if (
                not compatible
                and effective_visibility == ResourceVisibility.personal
                and effective_owner_id in granted_user_ids
            ):
                compatible = True
            if not compatible:
                raise DomainValidationError(
                    f"Agent scope is incompatible with trigger '{trigger.name}'"
                )

    async def _validate_subagent_dependencies_for_scope(
        self,
        agent_id: UUID,
        visibility: ResourceVisibility,
        team_ids: set[UUID],
    ) -> None:
        links = await self.repository.list_subagent_links_for_agents([agent_id])
        if not links:
            return
        related_ids = {
            related_id
            for link in links
            for related_id in (link.supervisor_id, link.subagent_id)
        }
        agents = {}
        for related_id in sorted(related_ids, key=str):
            related = await self.repository.get_scoped_for_update(related_id)
            if related is not None:
                agents[related.id] = related
        for link in links:
            supervisor = agents.get(link.supervisor_id)
            subagent = agents.get(link.subagent_id)
            if supervisor is None or subagent is None:
                continue
            supervisor_visibility = (
                visibility if supervisor.id == agent_id else supervisor.visibility
            )
            supervisor_team_ids = (
                team_ids
                if supervisor.id == agent_id
                else (
                    set(await self.repository.get_team_ids(supervisor.id))
                    if supervisor.visibility == ResourceVisibility.teams
                    else set()
                )
            )
            subagent_visibility = (
                visibility if subagent.id == agent_id else subagent.visibility
            )
            subagent_team_ids = (
                team_ids
                if subagent.id == agent_id
                else (
                    set(await self.repository.get_team_ids(subagent.id))
                    if subagent.visibility == ResourceVisibility.teams
                    else set()
                )
            )
            if not audience_contains(
                parent_visibility=supervisor_visibility,
                parent_owner_id=supervisor.owner_id,
                parent_team_ids=supervisor_team_ids,
                child_visibility=subagent_visibility,
                child_owner_id=subagent.owner_id,
                child_team_ids=subagent_team_ids,
            ):
                raise DomainValidationError(
                    f"Agent scope is incompatible with supervisor '{supervisor.name}'"
                )
            if self.workspace_id is None:
                continue
            for grant in await self.repository.get_permissions(supervisor.id):
                membership = await self.workspaces.get_membership(
                    self.workspace_id, grant.user_id
                )
                if membership is not None and not is_resource_visible_to_identity(
                    visibility=subagent_visibility,
                    owner_id=subagent.owner_id,
                    team_ids=subagent_team_ids,
                    user_id=grant.user_id,
                    is_admin=membership.role == WorkspaceRole.admin,
                    team_id=membership.team_id,
                ):
                    raise DomainValidationError(
                        f"Agent scope excludes a grantee of supervisor "
                        f"'{supervisor.name}'"
                    )

    async def ensure_subagent_scopes(self, agent_id: UUID) -> None:
        """Runtime backstop for legacy or externally corrupted graph links."""
        agent = await self.repository.get_scoped_for_update(agent_id)
        if agent is None:
            raise NotFoundError(self.not_found_message)
        team_ids = (
            set(await self.repository.get_team_ids(agent_id))
            if agent.visibility == ResourceVisibility.teams
            else set()
        )
        await self._validate_subagent_dependencies_for_scope(
            agent_id, agent.visibility, team_ids
        )

    async def _validate_bound_dependencies_for_scope(
        self,
        agent_id: UUID,
        visibility: ResourceVisibility,
        team_ids: set[UUID],
    ) -> None:
        agent = await self._get_scoped(agent_id)
        for binding in await self.mcp_server_repository.list_for_agent(agent_id):
            server = await self.mcp_servers.get_scoped_for_update(binding.mcp_server_id)
            if server is None:
                continue
            if not audience_contains(
                parent_visibility=visibility,
                parent_owner_id=agent.owner_id,
                parent_team_ids=team_ids,
                child_visibility=server.visibility,
                child_owner_id=server.owner_id,
                child_team_ids=(
                    set(await self.mcp_servers.list_team_ids(server.id))
                    if server.visibility == ResourceVisibility.teams
                    else set()
                ),
            ):
                raise DomainValidationError(
                    f"MCP server '{server.name}' is more private than this agent"
                )

        for skill_id in await self.skill_service.repository.list_attached_ids(agent_id):
            skill = await self.skill_service.repository.get_for_update(skill_id)
            if skill is None:
                continue
            if not audience_contains(
                parent_visibility=visibility,
                parent_owner_id=agent.owner_id,
                parent_team_ids=team_ids,
                child_visibility=skill.visibility,
                child_owner_id=skill.owner_id,
                child_team_ids=(
                    set(await self.skill_service.repository.list_team_ids(skill.id))
                    if skill.visibility == ResourceVisibility.teams
                    else set()
                ),
            ):
                raise DomainValidationError(
                    f"Skill '{skill.name}' is more private than this agent"
                )

    async def delete(
        self,
        agent_id: UUID,
        user_id: UUID | None = None,
        user_role: WorkspaceRole | None = None,
    ) -> None:
        await self.require_permission(
            agent_id,
            at_least=EffectivePermission.admin,
            action="delete this agent",
            user_id=user_id,
            user_role=user_role,
            # Archiving is idempotent: an already-archived agent must resolve
            # here rather than 404, or a repeated delete fails.
            include_archived=True,
        )
        await self.repository.delete_all_subagent_links(agent_id)
        await self.repository.set_archived(agent_id, archived=True)
        await self._stage_agents_changed()

    async def restore(
        self,
        agent_id: UUID,
        user_id: UUID | None = None,
        user_role: WorkspaceRole | None = None,
        user_team_id: UUID | None = None,
    ) -> AgentResponse:
        await self.require_permission(
            agent_id,
            at_least=EffectivePermission.admin,
            action="restore this agent",
            user_id=user_id,
            user_role=user_role,
            user_team_id=user_team_id,
            include_archived=True,
        )
        await self.repository.set_archived(agent_id, archived=False)
        response = await self.get(
            agent_id,
            user_id=user_id,
            user_role=user_role,
            user_team_id=user_team_id,
            include_archived=True,
        )
        await self._stage_agents_changed()
        return response

    async def delete_permanently(self, agent_id: UUID) -> None:
        """Delete the agent row and every agents-owned row that references it.

        Two things are deliberately *not* done here. The agent's threads point
        at it by FK and must go first, but they belong to the threads module —
        a thread's permission is its agent's, so the dependency runs
        threads → agents and never back. And checkpoint purging is an external,
        non-transactional side effect that must run only after the deletes are
        *committed*, not merely flushed. `DELETE /agents/{id}/permanent`
        composes all three in that order (threads, agent, commit, purge) and
        declares the admin gate on the route, since the thread delete has to
        run before this method could gate it (P1-9, #369).
        """
        await self.repository.delete_all_subagent_links(agent_id)
        await self.mcp_server_repository.delete_all_for_agent(agent_id)
        await self.repository.delete_all_permissions(agent_id)
        await self.repository.delete_all_teams(agent_id)
        await self.repository.delete_by_id(agent_id)
        await self._stage_agents_changed()

    async def get_permissions(self, agent_id: UUID) -> list[AgentUserPermissionDB]:
        return await self.repository.get_permissions(agent_id)

    async def set_permissions(
        self, agent_id: UUID, permissions: list[AgentPermissionCreate]
    ) -> list[AgentUserPermissionDB]:
        if self.workspace_id is None:
            raise RuntimeError("workspace_id is required to manage permissions")
        if await self.repository.get_scoped_for_update(agent_id) is None:
            raise NotFoundError(self.not_found_message)
        proposed_user_ids = {permission.user_id for permission in permissions}
        for permission in permissions:
            membership = await self.workspaces.get_membership(
                self.workspace_id, permission.user_id
            )
            if membership is None:
                raise NotFoundError("User not found")
            await self.ensure_dependencies_visible_to_identity(
                agent_id,
                user_id=permission.user_id,
                user_role=membership.role,
                user_team_id=membership.team_id,
            )
        await self._ensure_trigger_owners_keep_access(agent_id, proposed_user_ids)
        saved = await self.repository.set_permissions(agent_id, permissions)
        await self._stage_agents_changed()
        return saved

    async def _ensure_trigger_owners_keep_access(
        self, agent_id: UUID, proposed_user_ids: set[UUID]
    ) -> None:
        from app.projects.repository import ProjectRepository
        from app.triggers.repository import TriggerRepository

        if self.workspace_id is None:
            return
        agent = await self.repository.get_scoped_for_update(agent_id)
        if agent is None:
            raise NotFoundError(self.not_found_message)
        agent_team_ids = (
            set(await self.repository.get_team_ids(agent_id))
            if agent.visibility == ResourceVisibility.teams
            else set()
        )
        triggers = TriggerRepository(self.db, self.workspace_id)
        projects = ProjectRepository(self.db, self.workspace_id)
        membership_by_user: dict[UUID, WorkspaceMembershipDB | None] = {}

        async def keeps_access(user_id: UUID) -> bool:
            if user_id in proposed_user_ids:
                return True
            if user_id not in membership_by_user:
                membership_by_user[user_id] = await self.workspaces.get_membership(
                    self.workspace_id, user_id
                )
            membership = membership_by_user[user_id]
            return membership is not None and is_resource_visible_to_identity(
                visibility=agent.visibility,
                owner_id=agent.owner_id,
                team_ids=agent_team_ids,
                user_id=user_id,
                is_admin=membership.role == WorkspaceRole.admin,
                team_id=membership.team_id,
            )

        for trigger in await triggers.list_for_agent(agent_id):
            project = (
                await projects.get(trigger.project_id)
                if trigger.project_id is not None
                else None
            )
            effective_visibility = (
                project.visibility if project is not None else trigger.visibility
            )
            effective_owner_id = (
                project.owner_id if project is not None else trigger.owner_id
            )
            if not await keeps_access(trigger.owner_id):
                raise DomainValidationError(
                    f"Removing this grant would disable trigger '{trigger.name}'"
                )
            if (
                project is not None
                and effective_visibility == ResourceVisibility.personal
                and effective_owner_id != trigger.owner_id
                and not await keeps_access(effective_owner_id)
            ):
                raise DomainValidationError(
                    "Removing this grant would make the agent unavailable to "
                    f"the owner of trigger project '{project.name}'"
                )

    async def ensure_dependencies_visible_to_identity(
        self,
        agent_id: UUID,
        *,
        user_id: UUID,
        user_role: WorkspaceRole,
        user_team_id: UUID | None,
    ) -> None:
        is_admin = user_role == WorkspaceRole.admin
        for binding in await self.mcp_server_repository.list_for_agent(agent_id):
            server = await self.mcp_servers.get_scoped_for_update(binding.mcp_server_id)
            if server is None:
                continue
            team_ids = (
                set(await self.mcp_servers.list_team_ids(server.id))
                if server.visibility == ResourceVisibility.teams
                else set()
            )
            if not is_resource_visible_to_identity(
                visibility=server.visibility,
                owner_id=server.owner_id,
                team_ids=team_ids,
                user_id=user_id,
                is_admin=is_admin,
                team_id=user_team_id,
            ):
                raise DomainValidationError(
                    f"MCP server '{server.name}' is not visible to this user"
                )

        for skill_id in await self.skill_service.repository.list_attached_ids(agent_id):
            skill = await self.skill_service.repository.get_for_update(skill_id)
            if skill is None:
                continue
            team_ids = (
                set(await self.skill_service.repository.list_team_ids(skill.id))
                if skill.visibility == ResourceVisibility.teams
                else set()
            )
            if not is_resource_visible_to_identity(
                visibility=skill.visibility,
                owner_id=skill.owner_id,
                team_ids=team_ids,
                user_id=user_id,
                is_admin=is_admin,
                team_id=user_team_id,
            ):
                raise DomainValidationError(
                    f"Skill '{skill.name}' is not visible to this user"
                )

        links = await self.repository.list_subagent_links(agent_id)
        subagents = {}
        for subagent_id in sorted({link.subagent_id for link in links}, key=str):
            subagent = await self.repository.get_scoped_for_update(subagent_id)
            if subagent is not None:
                subagents[subagent.id] = subagent
        for link in links:
            subagent = subagents.get(link.subagent_id)
            if subagent is None:
                continue
            team_ids = (
                set(await self.repository.get_team_ids(subagent.id))
                if subagent.visibility == ResourceVisibility.teams
                else set()
            )
            if not is_resource_visible_to_identity(
                visibility=subagent.visibility,
                owner_id=subagent.owner_id,
                team_ids=team_ids,
                user_id=user_id,
                is_admin=is_admin,
                team_id=user_team_id,
            ):
                raise DomainValidationError(
                    f"Subagent '{subagent.name}' is not visible to this user"
                )

    async def get_team_ids(self, agent_id: UUID) -> list[UUID]:
        return await self.repository.get_team_ids(agent_id)

    async def _validate_team_ids(self, team_ids: list[UUID]) -> None:
        if self.workspace_id is None:
            raise RuntimeError("workspace_id is required to manage teams")
        for team_id in set(team_ids):
            if (
                await self.teams.get_in_workspace_for_key_share(
                    team_id, self.workspace_id
                )
                is None
            ):
                raise NotFoundError("Team not found")

    async def set_teams(self, agent_id: UUID, team_ids: list[UUID]) -> list[UUID]:
        await self._validate_team_ids(team_ids)
        agent = await self.repository.get_scoped_for_update(agent_id)
        if agent is None:
            raise NotFoundError(self.not_found_message)
        validate_visibility(agent.visibility, team_ids)
        candidate_team_ids = set(team_ids)
        await self._validate_trigger_dependencies_for_scope(
            agent_id, agent.visibility, candidate_team_ids
        )
        await self._validate_subagent_dependencies_for_scope(
            agent_id, agent.visibility, candidate_team_ids
        )
        await self._validate_bound_dependencies_for_scope(
            agent_id, agent.visibility, candidate_team_ids
        )
        saved = await self.repository.set_teams(agent_id, team_ids)
        await self._stage_agents_changed()
        return saved

    # -- Subagents -------------------------------------------------------------
    #
    # A binding of the aggregate, like permissions and teams: the link rows carry
    # the pair plus its new-conversation default, so there is no service of their
    # own — the validations below are the whole behaviour.

    @staticmethod
    def _to_subagent_response(
        agent: AgentDB, *, enabled_by_default: bool = True
    ) -> SubagentResponse:
        return SubagentResponse(
            id=agent.id,
            name=agent.name,
            emoji=agent.emoji,
            color=agent.color,
            image_revision=agent.image_revision,
            description=agent.description,
            enabled_by_default=enabled_by_default,
        )

    async def _list_subagent_data(
        self, agent_ids: list[UUID]
    ) -> tuple[dict[UUID, list[SubagentResponse]], set[UUID]]:
        """Per-agent subagent lists plus the set of agents that are themselves
        a subagent, for the response hydration — two queries however many
        agents are being assembled."""
        if not agent_ids:
            return {}, set()

        links = await self.repository.list_subagent_links_for_agents(agent_ids)
        referenced_ids = {link.supervisor_id for link in links} | {
            link.subagent_id for link in links
        }
        agents = {a.id: a for a in await self.repository.list_by_ids(referenced_ids)}

        subagents_map: dict[UUID, list[SubagentResponse]] = defaultdict(list)
        is_subagent_ids: set[UUID] = set()
        agent_ids_set = set(agent_ids)
        for link in links:
            if link.supervisor_id in agent_ids_set:
                sub = agents.get(link.subagent_id)
                if sub:
                    subagents_map[link.supervisor_id].append(
                        self._to_subagent_response(
                            sub, enabled_by_default=link.enabled_by_default
                        )
                    )
            if link.subagent_id in agent_ids_set:
                is_subagent_ids.add(link.subagent_id)
        return subagents_map, is_subagent_ids

    async def create_subagent(
        self,
        supervisor_id: UUID,
        subagent_id: UUID,
        *,
        enabled_by_default: bool = True,
        user_id: UUID | None = None,
        user_role: WorkspaceRole | None = None,
        user_team_id: UUID | None = None,
    ) -> AgentSubagentDB:
        """Link one subagent under a supervisor; idempotent for an existing
        link. Graphs are one level deep: a supervisor cannot itself be a
        subagent, and a subagent cannot have subagents of its own.

        The caller must be able to use the child. The audience and grantee
        checks below remain stronger: everyone who can use the supervisor must
        also be able to see the child."""
        if supervisor_id == subagent_id:
            raise DomainValidationError("Cannot add an agent as its own subagent")

        locked = {}
        for current_id in sorted((supervisor_id, subagent_id), key=str):
            locked[current_id] = await self.repository.get_scoped_for_update(current_id)
        supervisor = locked[supervisor_id]
        if not supervisor or supervisor.is_archived:
            raise NotFoundError("Supervisor agent not found")

        subagent = locked[subagent_id]
        if not subagent or subagent.is_archived:
            raise NotFoundError("Subagent not found")
        await self.require_permission(
            subagent_id,
            at_least=EffectivePermission.member,
            action="use this agent as a subagent",
            user_id=user_id,
            user_role=user_role,
            user_team_id=user_team_id,
        )
        supervisor_team_ids = (
            set(await self.repository.get_team_ids(supervisor.id))
            if supervisor.visibility == ResourceVisibility.teams
            else set()
        )
        subagent_team_ids = (
            set(await self.repository.get_team_ids(subagent.id))
            if subagent.visibility == ResourceVisibility.teams
            else set()
        )
        if not audience_contains(
            parent_visibility=supervisor.visibility,
            parent_owner_id=supervisor.owner_id,
            parent_team_ids=supervisor_team_ids,
            child_visibility=subagent.visibility,
            child_owner_id=subagent.owner_id,
            child_team_ids=subagent_team_ids,
        ):
            raise DomainValidationError(
                f"Subagent '{subagent.name}' is more private than its supervisor"
            )
        if self.workspace_id is not None:
            for grant in await self.repository.get_permissions(supervisor.id):
                membership = await self.workspaces.get_membership(
                    self.workspace_id, grant.user_id
                )
                if membership is not None and not is_resource_visible_to_identity(
                    visibility=subagent.visibility,
                    owner_id=subagent.owner_id,
                    team_ids=subagent_team_ids,
                    user_id=grant.user_id,
                    is_admin=membership.role == WorkspaceRole.admin,
                    team_id=membership.team_id,
                ):
                    raise DomainValidationError(
                        f"Subagent '{subagent.name}' is not visible to every "
                        "supervisor grantee"
                    )

        if await self.repository.has_subagents(subagent_id):
            raise DomainValidationError(
                "This agent already has subagents and cannot be used as a subagent"
            )

        if await self.repository.is_subagent(supervisor_id):
            raise DomainValidationError(
                "This agent is already used as a subagent and cannot have subagents"
            )

        # Joining a graph merges two skill sets, and nothing has to be checked
        # about that: the skill library is one namespace, so two different
        # skills of one name do not exist to be merged.
        existing = await self.repository.get_subagent_link(supervisor_id, subagent_id)
        if existing:
            return existing
        if enabled_by_default:
            created = await self.repository.create_subagent_link(
                supervisor_id, subagent_id
            )
        else:
            created = await self.repository.create_subagent_link(
                supervisor_id,
                subagent_id,
                enabled_by_default=False,
            )
        await self._stage_agents_changed()
        return created

    async def delete_subagent(self, supervisor_id: UUID, subagent_id: UUID) -> None:
        link = await self.repository.get_subagent_link(supervisor_id, subagent_id)
        if not link:
            raise NotFoundError("Subagent not found")
        await self.repository.delete_subagent_link(link)
        await self._stage_agents_changed()

    async def set_subagents(
        self,
        agent_id: UUID,
        subagent_ids: list[UUID],
        *,
        disabled_by_default: list[UUID] | None = None,
        user_id: UUID | None = None,
        user_role: WorkspaceRole | None = None,
        user_team_id: UUID | None = None,
    ) -> None:
        """Whole-set replace of an agent's subagents, routed through
        `create_subagent` so the self-link / archived / cycle validations
        and the caller's access to each added child keep firing. The caller's
        editor access to the supervisor is checked by the config save or route."""
        current_links = await self.repository.list_subagent_links(agent_id)
        current = {link.subagent_id for link in current_links}
        wanted = set(subagent_ids)
        disabled = set(disabled_by_default or []) & wanted
        # Removals first, so every validation an addition runs sees the graph
        # this save asks for and not a transient union of the two. One
        # transaction, so a failed addition rolls the removals back with it.
        for subagent_id in current - wanted:
            await self.delete_subagent(agent_id, subagent_id)
        for subagent_id in wanted - current:
            if subagent_id in disabled:
                await self.create_subagent(
                    agent_id,
                    subagent_id,
                    enabled_by_default=False,
                    user_id=user_id,
                    user_role=user_role,
                    user_team_id=user_team_id,
                )
            else:
                await self.create_subagent(
                    agent_id,
                    subagent_id,
                    user_id=user_id,
                    user_role=user_role,
                    user_team_id=user_team_id,
                )
        defaults_changed = False
        for link in current_links:
            if link.subagent_id in wanted:
                enabled = link.subagent_id not in disabled
                if link.enabled_by_default != enabled:
                    defaults_changed = True
                    await self.repository.set_subagent_default(
                        link, enabled_by_default=enabled
                    )
        if defaults_changed:
            await self._stage_agents_changed()

    # -- Sandbox binding -------------------------------------------------------

    async def list_for_sandbox(self, sandbox_id: UUID) -> list[SandboxAgentResponse]:
        """Agents currently bound to the sandbox (delete-guard dialog)."""
        agents = await self.repository.list_for_sandbox(sandbox_id)
        return [
            SandboxAgentResponse(
                id=agent.id,
                name=agent.name,
                emoji=agent.emoji,
                color=agent.color,
                image_revision=agent.image_revision,
            )
            for agent in agents
        ]

    async def detach_sandbox(self, sandbox_id: UUID) -> None:
        """Unbind the sandbox from every agent — the dialog's explicit confirm
        before the sandbox itself is deleted."""
        await self.repository.delete_all_sandbox_bindings_for_sandbox(sandbox_id)

    async def set_sandboxes(
        self, agent_id: UUID, configs: list[AgentSandboxConfig]
    ) -> None:
        """Whole-set replace of an agent's sandbox binding (≤1 for now). Same
        semantics as `AgentMCPServerService.set_for_agent`, minus tool
        discovery — the sandbox tool surface is static."""
        wanted = configs[0] if configs else None
        if wanted is not None and (
            self.workspace_id is None
            or not await self.sandboxes.get_scoped(wanted.sandbox_id, self.workspace_id)
        ):
            raise NotFoundError("Sandbox not found")
        await self.repository.set_sandbox(agent_id, wanted)

    async def collect_run_bindings(self, agent_id: UUID) -> list[AgentMCPServerDB]:
        """Every MCP binding a run of this agent touches: the agent's own plus
        each direct subagent's. One level only — matches `Agent.build`, which
        does not recurse into a subagent's own subagents.

        A projection of `RunSpec` — see `run_spec.all_mcp_bindings` for the
        not-deduped contract. This used to be a full `AgentService.get` per
        agent, i.e. (1+N)×~5 queries, and it sits on the endpoint the frontend
        polls (design review §1.2).
        """
        spec = await self.repository.get_run_spec(agent_id)
        if spec is None:
            return []
        return spec.all_mcp_bindings

    async def describe_readiness(
        self,
        agent_id: UUID,
        user_id: str,
        *,
        disabled_mcp_server_ids: set[UUID] | None = None,
        disabled_sandbox_ids: set[UUID] | None = None,
        disabled_subagent_ids: set[UUID] | None = None,
        force_enable_all_capabilities: bool | None = None,
        force_disable_all_capabilities: bool = False,
        inherit_agent_tool_mode: bool = False,
    ) -> dict:
        spec = await self.repository.get_run_spec(agent_id)
        if (
            spec is not None
            and inherit_agent_tool_mode
            and force_enable_all_capabilities is None
            and not force_disable_all_capabilities
            and spec.agent.tool_discovery_mode is ToolDiscoveryMode.lazy
        ):
            # An inherited Lazy policy has the same resource precedence as an
            # explicit Lazy thread mode: all attached resources are candidates.
            force_enable_all_capabilities = True
        exclusions = (
            spec.resource_exclusions(
                disabled_mcp_server_ids=disabled_mcp_server_ids or set(),
                disabled_sandbox_ids=disabled_sandbox_ids or set(),
                disabled_subagent_ids=disabled_subagent_ids or set(),
                force_enable_all_capabilities=force_enable_all_capabilities,
                force_disable_all_capabilities=force_disable_all_capabilities,
            )
            if spec
            else None
        )
        enabled_specs = (
            [
                spec.agent,
                *(
                    subagent
                    for subagent in spec.subagents
                    if subagent.id not in exclusions.subagent_ids
                ),
            ]
            if spec and exclusions
            else []
        )
        enabled_sandbox_rows = (
            [
                agent_spec.sandbox.row
                for agent_spec in enabled_specs
                if agent_spec.sandbox is not None
                and agent_spec.sandbox.row.id not in exclusions.sandbox_ids
            ]
            if exclusions
            else []
        )
        accepts_files = bool(artifact_settings.provider and enabled_sandbox_rows)
        # The sandbox first: an outage blocks the agent outright, and there is
        # nothing the user can click to fix it (unlike an MCP reconnect).
        try:
            await ensure_sandboxes_available(enabled_sandbox_rows)
        except SandboxUnavailableError as exc:
            return {
                "ready": False,
                "accepts_files": accepts_files,
                "disconnected_servers": [],
                "status": "sandbox_unavailable",
                "detail": exc.detail,
            }
        # Includes subagents' servers so the UI can offer every optional OAuth
        # connection. Missing per-user OAuth no longer blocks a run: the
        # runtime omits those servers from that user's toolset.
        bindings = (
            [
                binding
                for agent_spec in enabled_specs
                for binding in agent_spec.mcp_servers
                if binding.mcp_server_id not in exclusions.mcp_server_ids
            ]
            if exclusions
            else []
        )

        if not bindings:
            return {
                "ready": True,
                "accepts_files": accepts_files,
                "disconnected_servers": [],
                "status": "ready",
            }

        is_configured = all(binding.tools is not None for binding in bindings)

        server_ids = {b.mcp_server_id for b in bindings}  # dedupe for the probe
        servers = await self.mcp_servers.list_by_ids(server_ids)

        if self.workspace_id is None:
            raise RuntimeError("workspace_id is required for MCP authorization")
        authorized = await probe_authorization(servers, user_id, self.workspace_id)
        disconnected = [
            str(server.id) for server in servers if not authorized.get(server.id, True)
        ]

        if not is_configured:
            return {
                "ready": False,
                "accepts_files": accepts_files,
                "disconnected_servers": disconnected,
                "status": "not_configured",
            }

        return {
            "ready": True,
            "accepts_files": accepts_files,
            "disconnected_servers": disconnected,
            "status": "disconnected" if disconnected else "ready",
        }


def get_agent_service(
    db: AsyncSession = Depends(get_db),
    workspace_id: UUID = Depends(get_active_workspace_id),
) -> AgentService:
    return AgentService(db, workspace_id)
