from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.agents.models import (
    AgentDB,
    AgentMCPServerDB,
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
        agent_id: UUID | None = None,
        include_archived: bool = False,
    ) -> list:
        """Join agent ↔ MCP links ↔ user permission in one shot.

        When ``user_id`` is set and the user is not a workspace admin, the
        query includes a third tuple element: the user's permission row (or
        ``None``). Otherwise rows are ``(AgentDB, AgentMCPServerDB | None)``.
        """
        is_workspace_admin = user_role == WorkspaceRole.admin
        include_permissions = bool(user_id) and not is_workspace_admin

        columns = [AgentDB, AgentMCPServerDB]
        if include_permissions:
            columns.append(AgentUserPermissionDB.permission)

        stmt = select(*columns).outerjoin(
            AgentMCPServerDB, AgentDB.id == AgentMCPServerDB.agent_id
        )
        if include_permissions:
            stmt = stmt.outerjoin(
                AgentUserPermissionDB,
                (AgentDB.id == AgentUserPermissionDB.agent_id)
                & (AgentUserPermissionDB.user_id == user_id),
            )
        if agent_id is not None:
            stmt = stmt.where(AgentDB.id == agent_id)
        if not include_archived:
            stmt = stmt.where(AgentDB.is_archived == False)  # noqa: E712
        stmt = stmt.order_by(AgentDB.created_at.asc())

        result = await self.db.execute(stmt)
        return result.all()

    async def archive(self, agent: AgentDB) -> None:
        agent.is_archived = True
        self.db.add(agent)
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
