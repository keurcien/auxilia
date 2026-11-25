"""Plan and apply nested sharing changes.

Access flows down a chain: a project (or a standalone trigger) runs an agent,
and an agent uses subagents, MCP servers and skills. Each link requires the
child to be visible to everyone who can see the parent, and every service
validates only its own link. Sharing a trigger therefore used to mean finding
the order by hand: the project first, which needs the agent first, which needs
its MCP servers first.

`plan` walks that graph from one requested change and lists every change it
implies: children widened to keep covering a parent, parents narrowed to stay
within a child. `apply` performs a list of changes in one transaction, each
through its own service so every existing check still runs.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, replace
from uuid import UUID

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.core.repository import AgentRepository
from app.agents.core.service import AgentService
from app.agents.mcp_servers.repository import AgentMCPServerRepository
from app.agents.models import EffectivePermission
from app.database import get_db
from app.exceptions import (
    DomainValidationError,
    NotFoundError,
    PermissionDeniedError,
)
from app.mcp.servers.repository import MCPServerRepository
from app.mcp.servers.schemas import MCPServerPatch
from app.mcp.servers.service import MCPServerService
from app.projects.repository import ProjectRepository
from app.projects.schemas import ProjectPatch
from app.projects.service import ProjectService
from app.sharing.schemas import (
    ScopeChange,
    ScopeChangeRole,
    ScopePlanItem,
    ScopePlanResponse,
    ScopeResourceKind,
)
from app.skills.repository import SkillRepository
from app.skills.service import SkillService
from app.triggers.repository import TriggerRepository
from app.triggers.schemas import TriggerPatch
from app.triggers.service import TriggerService
from app.users.models import UserDB, WorkspaceRole
from app.visibility import (
    ResourceVisibility,
    audience_contains,
    is_resource_visible_to_identity,
    validate_visibility,
)
from app.workspaces.dependencies import get_active_workspace_id
from app.workspaces.repository import WorkspaceRepository


_TARGET_KINDS = {
    ScopeResourceKind.agent,
    ScopeResourceKind.project,
    ScopeResourceKind.trigger,
}
_KIND_LABELS = {
    ScopeResourceKind.agent: "agent",
    ScopeResourceKind.project: "project",
    ScopeResourceKind.trigger: "trigger",
    ScopeResourceKind.mcp_server: "MCP server",
    ScopeResourceKind.skill: "skill",
}
# Leaves first: widening a child never breaks its parents, so this order
# usually applies a widening plan without a retry.
_APPLY_ORDER = {
    ScopeResourceKind.mcp_server: 0,
    ScopeResourceKind.skill: 0,
    ScopeResourceKind.agent: 1,
    ScopeResourceKind.trigger: 2,
    ScopeResourceKind.project: 2,
}
_ROLE_ORDER = {
    ScopeChangeRole.target: 0,
    ScopeChangeRole.required: 1,
    ScopeChangeRole.suggested: 2,
}
# Each step processes one changed resource; a workspace graph that needs more
# than this is cycling between incompatible requirements.
_MAX_STEPS = 500

type _Key = tuple[ScopeResourceKind, UUID]


@dataclass(frozen=True)
class _Audience:
    visibility: ResourceVisibility
    owner_id: UUID
    team_ids: frozenset[UUID] = frozenset()

    def same_scope(self, other: _Audience) -> bool:
        return self.visibility == other.visibility and self.team_ids == other.team_ids


@dataclass
class _Node:
    kind: ScopeResourceKind
    id: UUID
    name: str
    current: _Audience
    can_manage: bool
    proposed: _Audience | None = None
    role: ScopeChangeRole | None = None
    caused_by: _Key | None = None
    reason: str | None = None

    @property
    def key(self) -> _Key:
        return (self.kind, self.id)

    @property
    def audience(self) -> _Audience:
        return self.proposed or self.current

    @property
    def label(self) -> str:
        return f"{_KIND_LABELS[self.kind]} '{self.name}'"

    def to_change(self) -> ScopeChange:
        audience = self.audience
        return ScopeChange(
            kind=self.kind,
            id=self.id,
            visibility=audience.visibility,
            team_ids=sorted(audience.team_ids, key=str),
        )


class _Planner:
    """One propagation over the sharing graph, caching what it reads."""

    def __init__(self, service: SharingService, user: UserDB):
        self.service = service
        self.user = user
        self.nodes: dict[_Key, _Node | None] = {}
        self.grantees: dict[UUID, set[UUID]] = {}
        self.owner_teams: dict[UUID, UUID | None] = {}
        self.blockers: list[str] = []

    # -- Reading ---------------------------------------------------------------

    async def node(self, key: _Key) -> _Node | None:
        if key not in self.nodes:
            self.nodes[key] = await self.service.load_node(key, self.user)
        return self.nodes[key]

    async def _grantees_of(self, agent_id: UUID) -> set[UUID]:
        if agent_id not in self.grantees:
            self.grantees[agent_id] = {
                grant.user_id
                for grant in await self.service.agents.get_permissions(agent_id)
            }
        return self.grantees[agent_id]

    async def children(self, node: _Node) -> list[tuple[_Key, str]]:
        service = self.service
        if node.kind == ScopeResourceKind.project:
            return [
                (
                    (ScopeResourceKind.agent, trigger.agent_id),
                    f"Runs trigger '{trigger.name}' in project '{node.name}'",
                )
                for trigger in await service.projects.list_triggers(node.id)
            ]
        if node.kind == ScopeResourceKind.trigger:
            trigger = await service.triggers.get(node.id)
            if trigger is None or trigger.project_id is not None:
                return []
            return [
                (
                    (ScopeResourceKind.agent, trigger.agent_id),
                    f"Runs trigger '{node.name}'",
                )
            ]
        if node.kind != ScopeResourceKind.agent:
            return []
        edges: list[tuple[_Key, str]] = [
            (
                (ScopeResourceKind.agent, link.subagent_id),
                f"Subagent of '{node.name}'",
            )
            for link in await service.agents.list_subagent_links(node.id)
        ]
        edges.extend(
            (
                (ScopeResourceKind.mcp_server, binding.mcp_server_id),
                f"Used by agent '{node.name}'",
            )
            for binding in await service.agent_mcp_servers.list_for_agent(node.id)
        )
        edges.extend(
            ((ScopeResourceKind.skill, skill_id), f"Used by agent '{node.name}'")
            for skill_id in sorted(
                await service.skills.list_attached_ids(node.id), key=str
            )
        )
        return edges

    async def parents(self, node: _Node) -> list[tuple[_Key, str]]:
        # MCP servers and skills are only ever widened by a plan, which never
        # constrains what uses them.
        if node.kind != ScopeResourceKind.agent:
            return []
        service = self.service
        edges: list[tuple[_Key, str]] = []
        for trigger in await service.triggers.list_for_agent(node.id):
            if trigger.project_id is not None:
                edges.append(
                    (
                        (ScopeResourceKind.project, trigger.project_id),
                        f"Its trigger '{trigger.name}' runs agent '{node.name}'",
                    )
                )
            else:
                edges.append(
                    (
                        (ScopeResourceKind.trigger, trigger.id),
                        f"Runs agent '{node.name}'",
                    )
                )
        edges.extend(
            (
                (ScopeResourceKind.agent, link.supervisor_id),
                f"Supervises '{node.name}'",
            )
            for link in await service.agents.list_subagent_links_for_agents([node.id])
            if link.subagent_id == node.id
        )
        return edges

    # -- Rules -----------------------------------------------------------------

    async def _fits(self, parent: _Node, child: _Node) -> bool:
        p, c = parent.audience, child.audience
        if audience_contains(
            parent_visibility=p.visibility,
            parent_owner_id=p.owner_id,
            parent_team_ids=set(p.team_ids),
            child_visibility=c.visibility,
            child_owner_id=c.owner_id,
            child_team_ids=set(c.team_ids),
        ):
            return True
        # Mirrors AgentService: a personal project or trigger may run an agent
        # its owner was explicitly granted.
        return (
            child.kind == ScopeResourceKind.agent
            and parent.kind in (ScopeResourceKind.project, ScopeResourceKind.trigger)
            and p.visibility == ResourceVisibility.personal
            and p.owner_id in await self._grantees_of(child.id)
        )

    @staticmethod
    def _widen(child: _Audience, parent: _Audience) -> _Audience:
        """The smallest change to `child` that covers `parent`'s audience."""
        if parent.visibility == ResourceVisibility.teams:
            kept = (
                child.team_ids
                if child.visibility == ResourceVisibility.teams
                else frozenset()
            )
            return replace(
                child,
                visibility=ResourceVisibility.teams,
                team_ids=kept | parent.team_ids,
            )
        # A workspace parent, or a personal one owned by someone else: only
        # the workspace reaches that owner without an explicit grant.
        return replace(
            child, visibility=ResourceVisibility.workspace, team_ids=frozenset()
        )

    @staticmethod
    def _narrow(parent: _Audience, child: _Audience) -> _Audience | None:
        """The change to `parent` that keeps it within `child`'s audience."""
        if child.visibility == ResourceVisibility.teams:
            if parent.visibility == ResourceVisibility.personal:
                return None
            kept = (
                parent.team_ids & child.team_ids
                if parent.visibility == ResourceVisibility.teams
                else frozenset()
            )
            return replace(
                parent,
                visibility=ResourceVisibility.teams,
                team_ids=kept or child.team_ids,
            )
        if (
            child.visibility == ResourceVisibility.personal
            and parent.owner_id == child.owner_id
        ):
            return replace(
                parent, visibility=ResourceVisibility.personal, team_ids=frozenset()
            )
        return None

    # -- Propagation -----------------------------------------------------------

    def seed(
        self,
        node: _Node,
        audience: _Audience,
        role: ScopeChangeRole,
        *,
        caused_by: _Key | None = None,
        reason: str | None = None,
    ) -> None:
        node.proposed = audience
        node.role = role
        node.caused_by = caused_by
        node.reason = reason

    def _change(
        self,
        node: _Node,
        audience: _Audience,
        cause: _Node,
        reason: str,
        role: ScopeChangeRole,
        queue: deque[_Key],
    ) -> None:
        if node.role == ScopeChangeRole.target:
            self.blockers.append(
                f"The requested change conflicts with how {cause.label} is shared."
            )
            return
        if node.proposed is None:
            node.role = role
            node.caused_by = cause.key
            node.reason = reason
        node.proposed = audience
        queue.append(node.key)

    async def propagate(self, seeds: list[_Key], role: ScopeChangeRole) -> None:
        queue = deque(seeds)
        steps = 0
        while queue:
            steps += 1
            if steps > _MAX_STEPS:
                self.blockers.append(
                    "These resources depend on each other in a way that cannot "
                    "be resolved automatically."
                )
                return
            node = self.nodes[queue.popleft()]
            if node is None:
                continue
            for key, reason in await self.children(node):
                child = await self.node(key)
                if child is None or await self._fits(node, child):
                    continue
                widened = self._widen(child.audience, node.audience)
                self._change(child, widened, node, reason, role, queue)
            for key, reason in await self.parents(node):
                parent = await self.node(key)
                if parent is None or await self._fits(parent, node):
                    continue
                narrowed = self._narrow(parent.audience, node.audience)
                if narrowed is None:
                    self.blockers.append(
                        f"The {parent.label} cannot be restricted to match "
                        f"{node.label}, because they belong to different owners."
                    )
                    continue
                self._change(parent, narrowed, node, reason, role, queue)

    async def check(self) -> None:
        """Rules propagation does not express: who may make each change, and
        trigger owners keeping the agent their runs execute."""
        service = self.service
        for node in self.changed():
            if not node.can_manage:
                self.blockers.append(
                    f"You cannot change who can access the {node.label}. Ask "
                    "its owner or a workspace admin."
                )
            if node.kind != ScopeResourceKind.agent:
                continue
            audience = node.audience
            grantees = await self._grantees_of(node.id)
            for trigger in await service.triggers.list_for_agent(node.id):
                if (
                    trigger.owner_id == audience.owner_id
                    or trigger.owner_id in grantees
                ):
                    continue
                membership = await service.workspaces.get_membership(
                    service.workspace_id, trigger.owner_id
                )
                if membership is not None and not is_resource_visible_to_identity(
                    visibility=audience.visibility,
                    owner_id=audience.owner_id,
                    team_ids=set(audience.team_ids),
                    user_id=trigger.owner_id,
                    is_admin=membership.role == WorkspaceRole.admin,
                    team_id=membership.team_id,
                ):
                    self.blockers.append(
                        f"The owner of trigger '{trigger.name}' would lose access "
                        f"to the {node.label}."
                    )

    def changed(self) -> list[_Node]:
        return [
            node
            for node in self.nodes.values()
            if node is not None
            and node.proposed is not None
            and not node.proposed.same_scope(node.current)
        ]


class SharingService:
    def __init__(self, db: AsyncSession, workspace_id: UUID):
        self.db = db
        self.workspace_id = workspace_id
        self.agents = AgentRepository(db, workspace_id)
        self.agent_mcp_servers = AgentMCPServerRepository(db)
        self.mcp_servers = MCPServerRepository(db, workspace_id)
        self.projects = ProjectRepository(db, workspace_id)
        self.skills = SkillRepository(db, workspace_id)
        self.triggers = TriggerRepository(db, workspace_id)
        self.workspaces = WorkspaceRepository(db)

    # -- Plan ------------------------------------------------------------------

    async def load_node(self, key: _Key, user: UserDB) -> _Node | None:
        kind, resource_id = key
        is_admin = user.role == WorkspaceRole.admin
        if kind == ScopeResourceKind.agent:
            agent = await self.agents.get_scoped(resource_id)
            if agent is None:
                return None
            team_ids = (
                await self.agents.get_team_ids(agent.id)
                if agent.visibility == ResourceVisibility.teams
                else []
            )
            return _Node(
                kind=kind,
                id=agent.id,
                name=agent.name,
                current=_Audience(
                    agent.visibility, agent.owner_id, frozenset(team_ids)
                ),
                can_manage=await self._can_edit_agent(agent.id, user),
            )
        if kind == ScopeResourceKind.project:
            project = await self.projects.get(resource_id)
            if project is None:
                return None
            team_ids = (
                await self.projects.list_team_ids(project.id)
                if project.visibility == ResourceVisibility.teams
                else []
            )
            return _Node(
                kind=kind,
                id=project.id,
                name=project.name,
                current=_Audience(
                    project.visibility, project.owner_id, frozenset(team_ids)
                ),
                can_manage=is_admin or project.owner_id == user.id,
            )
        if kind == ScopeResourceKind.trigger:
            trigger = await self.triggers.get(resource_id)
            if trigger is None:
                return None
            team_ids = (
                await self.triggers.list_team_ids(trigger.id)
                if trigger.visibility == ResourceVisibility.teams
                else []
            )
            return _Node(
                kind=kind,
                id=trigger.id,
                name=trigger.name,
                current=_Audience(
                    trigger.visibility, trigger.owner_id, frozenset(team_ids)
                ),
                can_manage=is_admin or trigger.owner_id == user.id,
            )
        if kind == ScopeResourceKind.mcp_server:
            server = await self.mcp_servers.get_scoped(resource_id)
            if server is None:
                return None
            team_ids = (
                await self.mcp_servers.list_team_ids(server.id)
                if server.visibility == ResourceVisibility.teams
                else []
            )
            return _Node(
                kind=kind,
                id=server.id,
                name=server.name,
                current=_Audience(
                    server.visibility, server.owner_id, frozenset(team_ids)
                ),
                can_manage=is_admin and server.managed_by is None,
            )
        skill = await self.skills.get_scoped(resource_id)
        if skill is None:
            return None
        team_ids = (
            await self.skills.list_team_ids(skill.id)
            if skill.visibility == ResourceVisibility.teams
            else []
        )
        return _Node(
            kind=kind,
            id=skill.id,
            name=skill.name,
            current=_Audience(skill.visibility, skill.owner_id, frozenset(team_ids)),
            can_manage=is_admin or skill.owner_id == user.id,
        )

    async def _can_edit_agent(self, agent_id: UUID, user: UserDB) -> bool:
        try:
            await AgentService(self.db, self.workspace_id).require_permission(
                agent_id,
                at_least=EffectivePermission.editor,
                action="change who can use this agent",
                user_id=user.id,
                user_role=user.role,
                user_team_id=user.team_id,
            )
        except NotFoundError, PermissionDeniedError:
            return False
        return True

    async def _resolve_target(
        self, request: ScopeChange, user: UserDB
    ) -> tuple[_Planner, _Node, str | None]:
        planner = _Planner(self, user)
        key: _Key = (request.kind, request.id)
        inherited_from_project = False
        if request.kind == ScopeResourceKind.trigger:
            trigger = await self.triggers.get(request.id)
            if trigger is not None and trigger.project_id is not None:
                key = (ScopeResourceKind.project, trigger.project_id)
                inherited_from_project = True
        node = await planner.node(key)
        if node is None:
            raise NotFoundError(f"{_KIND_LABELS[request.kind].capitalize()} not found")
        note = (
            f"This trigger inherits its access from project '{node.name}', so "
            "the project is shared instead."
            if inherited_from_project
            else None
        )
        return planner, node, note

    async def _propagate_from(
        self,
        request: ScopeChange,
        user: UserDB,
        suggestions: list[tuple[_Key, str]] | None = None,
    ) -> tuple[_Planner, _Node, str | None]:
        planner, target, note = await self._resolve_target(request, user)
        planner.seed(
            target,
            replace(
                target.current,
                visibility=request.visibility,
                team_ids=frozenset(request.team_ids),
            ),
            ScopeChangeRole.target,
        )
        seeds = [target.key]
        for key, reason in suggestions or []:
            node = await planner.node(key)
            if node is None:
                continue
            planner.seed(
                node,
                replace(
                    node.current,
                    visibility=request.visibility,
                    team_ids=frozenset(request.team_ids),
                ),
                ScopeChangeRole.suggested,
                caused_by=target.key,
                reason=reason,
            )
            seeds.append(key)
        await planner.propagate(seeds, ScopeChangeRole.required)
        await planner.check()
        return planner, target, note

    async def _suggestions(
        self, planner: _Planner, target: _Node
    ) -> list[tuple[_Key, str]]:
        """What already relies on a newly shared agent and is still shared
        more narrowly: the trigger the user is really trying to share."""
        if target.kind != ScopeResourceKind.agent:
            return []
        audience = target.audience
        suggestions: dict[_Key, str] = {}
        for key, reason in await planner.parents(target):
            if key[0] == ScopeResourceKind.agent or key in suggestions:
                continue
            parent = await planner.node(key)
            if parent is None or not parent.can_manage or parent.proposed is not None:
                continue
            if not audience_contains(
                parent_visibility=audience.visibility,
                parent_owner_id=audience.owner_id,
                parent_team_ids=set(audience.team_ids),
                child_visibility=parent.current.visibility,
                child_owner_id=parent.current.owner_id,
                child_team_ids=set(parent.current.team_ids),
            ):
                suggestions[key] = reason
        return list(suggestions.items())

    async def plan(self, request: ScopeChange, user: UserDB) -> ScopePlanResponse:
        if request.kind not in _TARGET_KINDS:
            raise DomainValidationError(
                "Only agents, projects and triggers can start a sharing plan"
            )
        validate_visibility(request.visibility, request.team_ids)
        minimal, target, note = await self._propagate_from(request, user)
        complete: _Planner | None = None
        if not minimal.blockers:
            suggestions = await self._suggestions(minimal, target)
            if suggestions:
                candidate, _, _ = await self._propagate_from(request, user, suggestions)
                if not candidate.blockers:
                    complete = candidate

        minimal_changes = {node.key: node for node in minimal.changed()}
        shown = complete or minimal
        nodes = shown.changed()
        if target.key not in {node.key for node in nodes}:
            nodes.insert(0, target)
        for node in nodes:
            if node.role == ScopeChangeRole.target:
                continue
            # Only what the target alone needs, exactly as it needs it, is
            # required; anything the suggestions add on top is a suggestion.
            required = minimal_changes.get(node.key)
            if required is None or not required.audience.same_scope(node.audience):
                node.role = ScopeChangeRole.suggested
        return ScopePlanResponse(
            items=self._tree(nodes, target.key),
            blockers=list(dict.fromkeys(minimal.blockers)),
            note=note,
            minimal=[node.to_change() for node in minimal_changes.values()],
            complete=(
                [node.to_change() for node in complete.changed()]
                if complete is not None
                else None
            ),
        )

    @staticmethod
    def _tree(nodes: list[_Node], root: _Key) -> list[ScopePlanItem]:
        """Depth-first, each change under the one that caused it."""
        by_cause: dict[_Key | None, list[_Node]] = {}
        for node in nodes:
            cause = None if node.key == root else node.caused_by
            by_cause.setdefault(cause, []).append(node)
        items: list[ScopePlanItem] = []
        seen: set[_Key] = set()

        def visit(node: _Node, depth: int) -> None:
            if node.key in seen:
                return
            seen.add(node.key)
            audience = node.audience
            items.append(
                ScopePlanItem(
                    kind=node.kind,
                    id=node.id,
                    name=node.name,
                    role=node.role or ScopeChangeRole.target,
                    depth=depth,
                    reason=node.reason,
                    can_manage=node.can_manage,
                    current_visibility=node.current.visibility,
                    current_team_ids=sorted(node.current.team_ids, key=str),
                    visibility=audience.visibility,
                    team_ids=sorted(audience.team_ids, key=str),
                )
            )
            for child in sorted(
                by_cause.get(node.key, []),
                key=lambda n: (
                    _ROLE_ORDER[n.role or ScopeChangeRole.target],
                    n.kind,
                    n.name,
                ),
            ):
                visit(child, depth + 1)

        for top in by_cause.get(None, []):
            visit(top, 0)
        for node in nodes:
            visit(node, 1)
        return items

    # -- Apply -----------------------------------------------------------------

    async def apply(self, changes: list[ScopeChange], user: UserDB) -> None:
        """Apply every change or none.

        Each change goes through its own service, which validates it against
        the current state. Changes that do not fit yet are retried once the
        others have landed, each inside a savepoint so a rejected attempt
        leaves nothing behind.
        """
        unique = {(change.kind, change.id): change for change in changes}
        pending = sorted(unique.values(), key=lambda change: _APPLY_ORDER[change.kind])
        while pending:
            remaining: list[ScopeChange] = []
            last_error: DomainValidationError | None = None
            for change in pending:
                try:
                    async with self.db.begin_nested():
                        await self._apply_one(change, user)
                except DomainValidationError as exc:
                    last_error = exc
                    remaining.append(change)
            if last_error is not None and len(remaining) == len(pending):
                raise last_error
            pending = remaining

    async def _apply_one(self, change: ScopeChange, user: UserDB) -> None:
        if change.kind == ScopeResourceKind.agent:
            await AgentService(self.db, self.workspace_id).set_scope(
                change.id,
                change.visibility,
                change.team_ids,
                user_id=user.id,
                user_role=user.role,
                user_team_id=user.team_id,
            )
        elif change.kind == ScopeResourceKind.project:
            await ProjectService(self.db, self.workspace_id).update(
                change.id,
                ProjectPatch(visibility=change.visibility, team_ids=change.team_ids),
                user,
            )
        elif change.kind == ScopeResourceKind.trigger:
            await TriggerService(self.db, self.workspace_id).update(
                change.id,
                TriggerPatch(visibility=change.visibility, team_ids=change.team_ids),
                user,
            )
        elif change.kind == ScopeResourceKind.mcp_server:
            if user.role != WorkspaceRole.admin:
                raise PermissionDeniedError(
                    "Only workspace admins can change who can use an MCP server"
                )
            await MCPServerService(self.db, self.workspace_id).update(
                change.id,
                MCPServerPatch(visibility=change.visibility, team_ids=change.team_ids),
            )
        else:
            await SkillService(self.db, self.workspace_id).set_scope(
                change.id, change.visibility, change.team_ids, user
            )


def get_sharing_service(
    db: AsyncSession = Depends(get_db),
    workspace_id: UUID = Depends(get_active_workspace_id),
) -> SharingService:
    return SharingService(db, workspace_id)
