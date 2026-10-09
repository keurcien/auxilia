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
    AgentResponse,
    AgentSandboxConfig,
    AgentSandboxResponse,
    AgentSkillResponse,
    SubagentResponse,
)
from app.database import get_db
from app.exceptions import (
    DomainValidationError,
    NotFoundError,
    PermissionDeniedError,
    SandboxUnavailableError,
)
from app.mcp.client.connectivity import probe_authorization
from app.mcp.servers.repository import MCPServerRepository
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
        return revision

    async def delete_image(self, agent_id: UUID) -> None:
        await self._get_scoped(agent_id)
        await self.repository.delete_image(agent_id)

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
                        tools=link.tools,
                        name=sandbox.name,
                        provider=sandbox.provider,
                        url=sandbox.url,
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
            )
        )
        validate_visibility(config.visibility, config.team_ids)
        if config.team_ids:
            await self.set_teams(agent.id, config.team_ids)
        await self.mcp_server_service.set_for_agent(agent.id, config.mcp_servers)
        await self.set_sandboxes(agent.id, config.sandboxes)
        await self.set_subagents(agent.id, config.subagent_ids, user_role=user_role)
        await self.skill_service.set_for_agent(agent.id, config.skill_ids)
        return await self.get(
            agent.id, user_id=owner_id, user_role=user_role, user_team_id=user_team_id
        )

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
        await self.repository.update_by_id(agent_id, data)
        return await self.get(
            agent_id, user_id=user_id, user_role=user_role, user_team_id=user_team_id
        )

    async def set_config(
        self,
        agent_id: UUID,
        config: AgentConfig,
        user_id: UUID,
        user_role: WorkspaceRole | None = None,
        user_team_id: UUID | None = None,
    ) -> AgentResponse:
        """Atomic whole-config replace: scalars, MCP bindings, subagents and
        skills in one request transaction. Performs zero network calls — the client
        already carries the complete per-tool maps (or None = never synced)."""
        await self.require_permission(
            agent_id,
            at_least=EffectivePermission.editor,
            action="edit this agent",
            user_id=user_id,
            user_role=user_role,
            user_team_id=user_team_id,
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
            ),
        )
        await self.mcp_server_service.set_for_agent(agent_id, config.mcp_servers)
        await self.set_sandboxes(agent_id, config.sandboxes)
        await self.set_subagents(agent_id, config.subagent_ids, user_role=user_role)
        await self.skill_service.set_for_agent(agent_id, config.skill_ids)
        return await self.get(
            agent_id, user_id=user_id, user_role=user_role, user_team_id=user_team_id
        )

    async def _validate_trigger_dependencies_for_scope(
        self,
        agent_id: UUID,
        visibility: ResourceVisibility,
        team_ids: set[UUID],
    ) -> None:
        from app.triggers.repository import TriggerRepository

        agent = await self.repository.get_scoped(agent_id)
        if agent is None:
            raise NotFoundError(self.not_found_message)
        granted_user_ids = {
            grant.user_id for grant in await self.repository.get_permissions(agent_id)
        }
        triggers = TriggerRepository(self.db, self.workspace_id)
        for trigger in await triggers.list_for_agent(agent_id):
            trigger_team_ids = (
                set(await triggers.list_team_ids(trigger.id))
                if trigger.visibility == ResourceVisibility.teams
                else set()
            )
            compatible = audience_contains(
                parent_visibility=trigger.visibility,
                parent_owner_id=trigger.owner_id,
                parent_team_ids=trigger_team_ids,
                child_visibility=visibility,
                child_owner_id=agent.owner_id,
                child_team_ids=team_ids,
            )
            if (
                not compatible
                and trigger.visibility == ResourceVisibility.personal
                and trigger.owner_id in granted_user_ids
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
        return await self.get(
            agent_id,
            user_id=user_id,
            user_role=user_role,
            user_team_id=user_team_id,
            include_archived=True,
        )

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
        return await self.repository.set_permissions(agent_id, permissions)

    async def _ensure_trigger_owners_keep_access(
        self, agent_id: UUID, proposed_user_ids: set[UUID]
    ) -> None:
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
        for trigger in await triggers.list_for_agent(agent_id):
            if trigger.visibility != ResourceVisibility.personal:
                continue
            membership = await self.workspaces.get_membership(
                self.workspace_id, trigger.owner_id
            )
            has_baseline_access = (
                membership is not None
                and is_resource_visible_to_identity(
                    visibility=agent.visibility,
                    owner_id=agent.owner_id,
                    team_ids=agent_team_ids,
                    user_id=trigger.owner_id,
                    is_admin=membership.role == WorkspaceRole.admin,
                    team_id=membership.team_id,
                )
            )
            if trigger.owner_id not in proposed_user_ids and not has_baseline_access:
                raise DomainValidationError(
                    f"Removing this grant would disable trigger '{trigger.name}'"
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
        return await self.repository.set_teams(agent_id, team_ids)

    # -- Subagents -------------------------------------------------------------
    #
    # A binding of the aggregate, like permissions and teams: the link rows carry
    # nothing but the pair, so there is no service of their own — the
    # validations below are the whole behaviour.

    @staticmethod
    def _to_subagent_response(agent: AgentDB) -> SubagentResponse:
        return SubagentResponse(
            id=agent.id,
            name=agent.name,
            emoji=agent.emoji,
            color=agent.color,
            image_revision=agent.image_revision,
            description=agent.description,
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
                        self._to_subagent_response(sub)
                    )
            if link.subagent_id in agent_ids_set:
                is_subagent_ids.add(link.subagent_id)
        return subagents_map, is_subagent_ids

    async def create_subagent(
        self, supervisor_id: UUID, subagent_id: UUID
    ) -> AgentSubagentDB:
        """Link one subagent under a supervisor; idempotent for an existing
        link. Graphs are one level deep: a supervisor cannot itself be a
        subagent, and a subagent cannot have subagents of its own."""
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
        return await self.repository.create_subagent_link(supervisor_id, subagent_id)

    async def delete_subagent(self, supervisor_id: UUID, subagent_id: UUID) -> None:
        link = await self.repository.get_subagent_link(supervisor_id, subagent_id)
        if not link:
            raise NotFoundError("Subagent not found")
        await self.repository.delete_subagent_link(link)

    async def set_subagents(
        self,
        agent_id: UUID,
        subagent_ids: list[UUID],
        *,
        user_role: WorkspaceRole | None,
    ) -> None:
        """Whole-set replace of an agent's subagents, routed through
        `create_subagent` so the self-link / archived / cycle validations
        keep firing. Admin-gated only when the set actually changes — an
        editor saving an agent whose subagents they didn't touch passes."""
        current = {
            link.subagent_id
            for link in await self.repository.list_subagent_links(agent_id)
        }
        wanted = set(subagent_ids)
        if current == wanted:
            return
        if user_role != WorkspaceRole.admin:
            raise PermissionDeniedError("Only admins can modify subagents")
        # Removals first, so every validation an addition runs sees the graph
        # this save asks for and not a transient union of the two. One
        # transaction, so a failed addition rolls the removals back with it.
        for subagent_id in current - wanted:
            await self.delete_subagent(agent_id, subagent_id)
        for subagent_id in wanted - current:
            await self.create_subagent(agent_id, subagent_id)

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

    async def describe_readiness(self, agent_id: UUID, user_id: str) -> dict:
        spec = await self.repository.get_run_spec(agent_id)
        # The sandbox first: an outage blocks the agent outright, and there is
        # nothing the user can click to fix it (unlike an MCP reconnect).
        try:
            await ensure_sandboxes_available(spec.all_sandbox_rows if spec else [])
        except SandboxUnavailableError as exc:
            return {
                "ready": False,
                "disconnected_servers": [],
                "status": "sandbox_unavailable",
                "detail": exc.detail,
            }
        # Includes subagents' servers so the UI can offer every optional OAuth
        # connection. Missing per-user OAuth no longer blocks a run: the
        # runtime omits those servers from that user's toolset.
        bindings = spec.all_mcp_bindings if spec else []

        if not bindings:
            return {"ready": True, "disconnected_servers": [], "status": "ready"}

        for binding in bindings:
            if binding.tools is None:
                return {
                    "ready": False,
                    "disconnected_servers": [],
                    "status": "not_configured",
                }

        server_ids = {b.mcp_server_id for b in bindings}  # dedupe for the probe
        servers = await self.mcp_servers.list_by_ids(server_ids)

        if self.workspace_id is None:
            raise RuntimeError("workspace_id is required for MCP authorization")
        authorized = await probe_authorization(servers, user_id, self.workspace_id)
        disconnected = [
            str(server.id) for server in servers if not authorized.get(server.id, True)
        ]

        return {
            "ready": True,
            "disconnected_servers": disconnected,
            "status": "disconnected" if disconnected else "ready",
        }


def get_agent_service(
    db: AsyncSession = Depends(get_db),
    workspace_id: UUID = Depends(get_active_workspace_id),
) -> AgentService:
    return AgentService(db, workspace_id)
