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
        user_id: UUID | None,
        user_role: WorkspaceRole | None,
    ) -> list:
        is_workspace_admin = user_role == WorkspaceRole.admin

        if user_id and not is_workspace_admin:
            stmt = (
                select(
                    AgentDB, AgentMCPServerDB, AgentUserPermissionDB.permission
                )
                .outerjoin(
                    AgentMCPServerDB,
                    AgentDB.id == AgentMCPServerDB.agent_id,
                )
                .outerjoin(
                    AgentUserPermissionDB,
                    (AgentDB.id == AgentUserPermissionDB.agent_id)
                    & (AgentUserPermissionDB.user_id == user_id),
                )
                .order_by(AgentDB.created_at.asc())
            )
        else:
            stmt = (
                select(AgentDB, AgentMCPServerDB)
                .outerjoin(
                    AgentMCPServerDB,
                    AgentDB.id == AgentMCPServerDB.agent_id,
                )
                .order_by(AgentDB.created_at.asc())
            )

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

        new_permissions = []
        for p in permissions:
            db_perm = AgentUserPermissionDB(
                agent_id=agent_id,
                user_id=p.user_id,
                permission=p.permission,
            )
            self.db.add(db_perm)
            new_permissions.append(db_perm)

        await self.db.flush()
        for perm in new_permissions:
            await self.db.refresh(perm)
        return new_permissions
