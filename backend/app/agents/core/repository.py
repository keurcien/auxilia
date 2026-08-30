from collections import defaultdict
from typing import NamedTuple
from uuid import UUID

from sqlalchemy import or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.agents.models import (
    AgentDB,
    AgentMCPServerDB,
    AgentSubagentDB,
    AgentTeamDB,
    AgentUserPermissionDB,
    PermissionLevel,
)
from app.agents.run_spec import AgentSpec, RunSpec, SandboxSpec
from app.agents.sandboxes.repository import AgentSandboxRepository
from app.agents.schemas import AgentPermissionCreate
from app.repository import BaseRepository
from app.users.models import WorkspaceRole


class AgentAccess(NamedTuple):
    """Everything `AgentService._resolve_permission` needs about one agent."""

    owner_id: UUID
    granted: PermissionLevel | None
    team_member: bool


class AgentRepository(BaseRepository[AgentDB]):
    def __init__(self, db: AsyncSession):
        super().__init__(AgentDB, db)

    async def list_with_permissions(
        self,
        *,
        user_id: UUID | None,
        user_role: WorkspaceRole | None,
        user_team_id: UUID | None = None,
        agent_id: UUID | None = None,
        include_archived: bool = False,
        archived_only: bool = False,
    ) -> list:
        """Join agent ↔ MCP links ↔ user permission ↔ team link in one shot.

        When ``user_id`` is set and the user is not a workspace admin, the
        query includes a third tuple element: the user's permission row (or
        ``None``). When the user also has a ``user_team_id``, a fourth element
        carries the matching agent↔team link's ``team_id`` (or ``None``) so the
        service can grant ``member`` through team membership. Otherwise rows are
        ``(AgentDB, AgentMCPServerDB | None)``.

        The team join is filtered on the user's single ``team_id``, so it
        matches at most one row per agent — no cartesian fan-out.

        ``archived_only`` restricts the result to archived agents (for the
        Archived view); it takes precedence over ``include_archived``.
        """
        is_workspace_admin = user_role == WorkspaceRole.admin
        include_permissions = bool(user_id) and not is_workspace_admin
        include_team = include_permissions and user_team_id is not None

        columns = [AgentDB, AgentMCPServerDB]
        if include_permissions:
            columns.append(AgentUserPermissionDB.permission)
        if include_team:
            columns.append(AgentTeamDB.team_id)

        stmt = select(*columns).outerjoin(
            AgentMCPServerDB, AgentDB.id == AgentMCPServerDB.agent_id
        )
        if include_permissions:
            stmt = stmt.outerjoin(
                AgentUserPermissionDB,
                (AgentDB.id == AgentUserPermissionDB.agent_id)
                & (AgentUserPermissionDB.user_id == user_id),
            )
        if include_team:
            stmt = stmt.outerjoin(
                AgentTeamDB,
                (AgentDB.id == AgentTeamDB.agent_id)
                & (AgentTeamDB.team_id == user_team_id),
            )
        if agent_id is not None:
            stmt = stmt.where(AgentDB.id == agent_id)
        if archived_only:
            stmt = stmt.where(AgentDB.is_archived == True)  # noqa: E712
        elif not include_archived:
            stmt = stmt.where(AgentDB.is_archived == False)  # noqa: E712
        stmt = stmt.order_by(AgentDB.created_at.asc())

        result = await self.db.execute(stmt)
        return result.all()

    async def get_access(
        self,
        agent_id: UUID,
        *,
        user_id: UUID | None,
        user_team_id: UUID | None = None,
        include_archived: bool = False,
    ) -> AgentAccess | None:
        """The three permission facts for one agent, in one narrow row.

        `list_with_permissions` answers the same question, but it carries the
        MCP-binding join and feeds a multi-query assembly — far too much work
        for a gate that only needs to know who owns the agent and what this
        user was granted. Returns `None` when the agent does not exist (or is
        archived and the caller did not ask for archived ones), which the
        service turns into the same 404 a read would raise.
        """
        include_team = user_id is not None and user_team_id is not None

        columns = [AgentDB.owner_id, AgentUserPermissionDB.permission]
        if include_team:
            columns.append(AgentTeamDB.team_id)

        stmt = select(*columns).outerjoin(
            AgentUserPermissionDB,
            (AgentDB.id == AgentUserPermissionDB.agent_id)
            & (AgentUserPermissionDB.user_id == user_id),
        )
        if include_team:
            stmt = stmt.outerjoin(
                AgentTeamDB,
                (AgentDB.id == AgentTeamDB.agent_id)
                & (AgentTeamDB.team_id == user_team_id),
            )
        stmt = stmt.where(AgentDB.id == agent_id)
        if not include_archived:
            stmt = stmt.where(AgentDB.is_archived == False)  # noqa: E712

        # Both joins match at most one row — the grant table is unique on
        # (agent_id, user_id) and the team join is filtered to the user's
        # single team — so there is exactly one row per existing agent.
        row = (await self.db.execute(stmt)).first()
        if row is None:
            return None
        return AgentAccess(
            owner_id=row[0],
            granted=row[1],
            team_member=include_team and row[2] is not None,
        )

    async def get_run_spec(self, agent_id: UUID) -> RunSpec | None:
        """The parent agent and its direct subagents, with their MCP and sandbox
        bindings, in three flat queries — regardless of how many subagents there
        are (design review §2.2). Returns `None` if the agent does not exist.

        Archived agents are included: a run already under way must survive its
        agent being archived mid-flight, and a subagent is routinely archived
        out of the agents list while still wired to a supervisor.
        """
        # One query for the whole first level. The outer join carries the link
        # row's `created_at` so subagents come back in a stable order; the parent matches
        # the first disjunct and joins to a NULL link, hence `nullsfirst`.
        stmt = (
            select(AgentDB, AgentSubagentDB.created_at)
            .outerjoin(
                AgentSubagentDB,
                (AgentSubagentDB.subagent_id == AgentDB.id)
                & (AgentSubagentDB.supervisor_id == agent_id),
            )
            .where(
                or_(
                    AgentDB.id == agent_id,
                    AgentSubagentDB.supervisor_id == agent_id,
                )
            )
            .order_by(
                AgentSubagentDB.created_at.asc().nullsfirst(),
                # `created_at` is the *transaction* timestamp, so subagents bound
                # in one save all share it and would otherwise come back in
                # whatever order the planner liked. The tie-break only buys
                # repeatability — subagents are addressed by name, so their
                # relative order carries no meaning.
                AgentSubagentDB.id.asc(),
            )
        )
        rows = (await self.db.execute(stmt)).all()

        parent: AgentDB | None = None
        subagent_rows: list[AgentDB] = []
        for agent, link_created_at in rows:
            if link_created_at is None and agent.id == agent_id:
                parent = agent
            else:
                subagent_rows.append(agent)
        if parent is None:
            return None

        agent_ids = [parent.id, *(a.id for a in subagent_rows)]

        bindings_by_agent: dict[UUID, list[AgentMCPServerDB]] = defaultdict(list)
        stmt = (
            select(AgentMCPServerDB)
            .where(AgentMCPServerDB.agent_id.in_(agent_ids))
            .order_by(AgentMCPServerDB.created_at.asc())
        )
        for binding in (await self.db.execute(stmt)).scalars().all():
            bindings_by_agent[binding.agent_id].append(binding)

        # An agent binds at most one sandbox (uq_agent_sandbox), so last-wins is
        # the same as only-one; the dict just avoids asserting that here.
        sandbox_by_agent: dict[UUID, SandboxSpec] = {}
        sandbox_repository = AgentSandboxRepository(self.db)
        for link, sandbox in await sandbox_repository.list_for_agents(agent_ids):
            sandbox_by_agent[link.agent_id] = SandboxSpec(row=sandbox, tools=link.tools)

        def to_spec(agent: AgentDB) -> AgentSpec:
            return AgentSpec(
                id=agent.id,
                name=agent.name,
                instructions=agent.instructions,
                description=agent.description,
                mcp_servers=bindings_by_agent.get(agent.id, []),
                sandbox=sandbox_by_agent.get(agent.id),
            )

        return RunSpec(
            agent=to_spec(parent),
            subagents=[to_spec(a) for a in subagent_rows],
        )

    async def archive(self, agent: AgentDB) -> None:
        agent.is_archived = True
        self.db.add(agent)
        await self.db.flush()

    async def restore(self, agent: AgentDB) -> None:
        agent.is_archived = False
        self.db.add(agent)
        await self.db.flush()

    async def delete_all_permissions(self, agent_id: UUID) -> None:
        existing = await self.get_permissions(agent_id)
        for perm in existing:
            await self.db.delete(perm)
        if existing:
            await self.db.flush()

    async def get_permissions(self, agent_id: UUID) -> list[AgentUserPermissionDB]:
        stmt = select(AgentUserPermissionDB).where(
            AgentUserPermissionDB.agent_id == agent_id
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def set_permissions(
        self, agent_id: UUID, permissions: list[AgentPermissionCreate]
    ) -> list[AgentUserPermissionDB]:
        existing = await self.get_permissions(agent_id)
        for perm in existing:
            await self.db.delete(perm)
        await self.db.flush()

        new_permissions = [
            AgentUserPermissionDB(
                agent_id=agent_id,
                user_id=p.user_id,
                permission=p.permission,
            )
            for p in permissions
        ]
        for perm in new_permissions:
            self.db.add(perm)
        await self.db.flush()
        for perm in new_permissions:
            await self.db.refresh(perm)
        return new_permissions

    async def get_team_ids(self, agent_id: UUID) -> list[UUID]:
        stmt = select(AgentTeamDB.team_id).where(AgentTeamDB.agent_id == agent_id)
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def _get_team_links(self, agent_id: UUID) -> list[AgentTeamDB]:
        stmt = select(AgentTeamDB).where(AgentTeamDB.agent_id == agent_id)
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def delete_all_teams(self, agent_id: UUID) -> None:
        existing = await self._get_team_links(agent_id)
        for link in existing:
            await self.db.delete(link)
        if existing:
            await self.db.flush()

    async def set_teams(self, agent_id: UUID, team_ids: list[UUID]) -> list[UUID]:
        existing = await self._get_team_links(agent_id)
        for link in existing:
            await self.db.delete(link)
        await self.db.flush()

        new_links = [
            AgentTeamDB(agent_id=agent_id, team_id=team_id)
            for team_id in dict.fromkeys(team_ids)
        ]
        for link in new_links:
            self.db.add(link)
        await self.db.flush()
        return [link.team_id for link in new_links]
