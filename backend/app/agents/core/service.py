from __future__ import annotations

import logging
from collections import defaultdict
from typing import Literal, overload
from uuid import UUID

from fastapi import Depends
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.core.repository import AgentRepository
from app.agents.mcp_servers.repository import AgentMCPServerRepository
from app.agents.mcp_servers.service import AgentMCPServerService
from app.agents.models import (
    AgentDB,
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
    TagInfo,
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
from app.service import BaseService
from app.skills.service import SkillService
from app.tags.service import TagService
from app.threads.service import ThreadService
from app.users.models import WorkspaceRole
from app.users.service import UserService


logger = logging.getLogger(__name__)


class AgentService(BaseService[AgentDB, AgentRepository]):
    not_found_message = "Agent not found"

    def __init__(self, db: AsyncSession):
        super().__init__(db, AgentRepository(db))
        self.thread_service = ThreadService(db)
        self.tag_service = TagService(db)
        self.user_service = UserService(db)
        self.mcp_server_repository = AgentMCPServerRepository(db)
        self.mcp_server_service = AgentMCPServerService(db)
        self.skill_service = SkillService(db)
        self.mcp_servers = MCPServerRepository(db)
        self.sandboxes = SandboxRepository(db)

    @staticmethod
    def _resolve_permission(
        *,
        owner_id: UUID,
        user_id: UUID | None,
        user_role: WorkspaceRole | None,
        granted: PermissionLevel | None,
        team_member: bool = False,
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
        tag_ids = list({a.tag_id for a in agents if a.tag_id is not None})
        tags_by_id = {t.id: t for t in await self.tag_service.list_by_ids(tag_ids)}
        owner_ids = list({a.owner_id for a in agents})
        owners_by_id = {u.id: u for u in await self.user_service.list_by_ids(owner_ids)}
        response_cls = AgentListResponse if slim else AgentResponse
        return [
            response_cls(
                **agent.model_dump(),
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
                tag=(
                    TagInfo(id=tag.id, name=tag.name)
                    if (tag := tags_by_id.get(agent.tag_id)) is not None
                    else None
                ),
                owner=(
                    AgentOwnerInfo(
                        id=owner.id,
                        name=owner.name,
                        email=owner.email,
                        picture_url=owner.picture_url,
                    )
                    if (owner := owners_by_id.get(agent.owner_id)) is not None
                    else None
                ),
                is_subagent=agent.id in is_subagent_ids,
                current_user_permission=self._resolve_permission(
                    owner_id=agent.owner_id,
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
        agent = await self.repository.create(
            AgentCreateDB(
                name=config.name,
                instructions=config.instructions,
                owner_id=owner_id,
                emoji=config.emoji,
                color=config.color,
                description=config.description,
            )
        )
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
        return await self._assemble(
            list(agents_map.values()),
            mcp_map,
            permissions_map,
            user_id,
            user_role,
            team_agent_ids,
            slim=True,
        )

    async def update(
        self,
        agent_id: UUID,
        data: AgentPatch,
        user_id: UUID | None = None,
        user_role: WorkspaceRole | None = None,
        user_team_id: UUID | None = None,
    ) -> AgentResponse:
        await self.require_permission(
            agent_id,
            at_least=EffectivePermission.editor,
            action="edit this agent",
            user_id=user_id,
            user_role=user_role,
            user_team_id=user_team_id,
        )
        if data.tag_id is not None:
            await self.tag_service.get(data.tag_id)
        try:
            await self.repository.update_by_id(agent_id, data)
        except IntegrityError as exc:
            if "fk_agents_tag_id_tags" not in str(getattr(exc, "orig", exc)):
                raise
            # The tag existed at validation time but was deleted before the
            # flush — surface the same 404 the validation would have raised.
            raise NotFoundError("Tag not found") from exc
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

        await self.repository.update_by_id(
            agent_id,
            AgentPatch(
                name=config.name,
                instructions=config.instructions,
                description=config.description,
                emoji=config.emoji,
                color=config.color,
            ),
        )
        await self.mcp_server_service.set_for_agent(agent_id, config.mcp_servers)
        await self.set_sandboxes(agent_id, config.sandboxes)
        await self.set_subagents(agent_id, config.subagent_ids, user_role=user_role)
        await self.skill_service.set_for_agent(agent_id, config.skill_ids)
        return await self.get(
            agent_id, user_id=user_id, user_role=user_role, user_team_id=user_team_id
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

    async def delete_permanently(
        self,
        agent_id: UUID,
        user_id: UUID | None = None,
        user_role: WorkspaceRole | None = None,
        user_team_id: UUID | None = None,
    ) -> list[str]:
        """Delete every DB row that references the agent, and return the ids of
        the threads that went with it.

        Checkpoint purging is deliberately **not** done here — it is an
        external, non-transactional side effect, so it must run after the
        caller has *committed* these deletes, not merely flushed them. Same
        contract as `ThreadService.delete_rows_for_agent`, and the same reason
        the thread endpoint commits before purging (P1-9): a purge that ran
        first and a commit that then failed would leave an agent whose entire
        history is irrecoverably gone.
        """
        await self.require_permission(
            agent_id,
            at_least=EffectivePermission.admin,
            action="permanently delete this agent",
            user_id=user_id,
            user_role=user_role,
            user_team_id=user_team_id,
            include_archived=True,
        )
        # Threads must go before the agent row, due to the FK.
        thread_ids = await self.thread_service.delete_rows_for_agent(agent_id)
        await self.repository.delete_all_subagent_links(agent_id)
        await self.mcp_server_repository.delete_all_for_agent(agent_id)
        await self.repository.delete_all_permissions(agent_id)
        await self.repository.delete_all_teams(agent_id)
        await self.repository.delete_by_id(agent_id)
        return thread_ids

    async def get_permissions(self, agent_id: UUID) -> list[AgentUserPermissionDB]:
        return await self.repository.get_permissions(agent_id)

    async def set_permissions(
        self, agent_id: UUID, permissions: list[AgentPermissionCreate]
    ) -> list[AgentUserPermissionDB]:
        return await self.repository.set_permissions(agent_id, permissions)

    async def get_team_ids(self, agent_id: UUID) -> list[UUID]:
        return await self.repository.get_team_ids(agent_id)

    async def set_teams(self, agent_id: UUID, team_ids: list[UUID]) -> list[UUID]:
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
            description=agent.description,
        )

    async def list_subagents(self, agent_id: UUID) -> list[SubagentResponse]:
        links = await self.repository.list_subagent_links(agent_id)
        sub_ids = [link.subagent_id for link in links]
        agents = {a.id: a for a in await self.repository.list_by_ids(sub_ids)}
        return [
            self._to_subagent_response(agents[sid]) for sid in sub_ids if sid in agents
        ]

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

        supervisor = await self.repository.get(supervisor_id)
        if not supervisor or supervisor.is_archived:
            raise NotFoundError("Supervisor agent not found")

        subagent = await self.repository.get(subagent_id)
        if not subagent or subagent.is_archived:
            raise NotFoundError("Subagent not found")

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

    async def set_sandboxes(
        self, agent_id: UUID, configs: list[AgentSandboxConfig]
    ) -> None:
        """Whole-set replace of an agent's sandbox binding (≤1 for now). Same
        semantics as `AgentMCPServerService.set_for_agent`, minus tool
        discovery — the sandbox tool surface is static."""
        wanted = configs[0] if configs else None
        if wanted is not None and not await self.sandboxes.get(wanted.sandbox_id):
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
        # Includes subagents' servers: a subagent's unauthorized OAuth server
        # must keep the agent "not ready" too, or the run launches and fails
        # mid-flight when the subagent calls it.
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

        authorized = await probe_authorization(servers, user_id)
        disconnected = [
            str(server.id) for server in servers if not authorized.get(server.id, True)
        ]

        return {
            "ready": not disconnected,
            "disconnected_servers": disconnected,
            # Was hardcoded to "disconnected" even when everything was connected
            # (design review §4.1) — the frontend's own `ready` flag disagreed
            # with the status string it was shown next to.
            "status": "disconnected" if disconnected else "ready",
        }


def get_agent_service(db: AsyncSession = Depends(get_db)) -> AgentService:
    return AgentService(db)
