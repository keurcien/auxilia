from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.agents.models import (
    AgentDB,
    AgentMCPServerDB,
    AgentTeamDB,
    AgentUserPermissionDB,
)
from app.agents.schemas import AgentPermissionCreate
from app.repository import BaseRepository
from app.users.models import WorkspaceRole


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
