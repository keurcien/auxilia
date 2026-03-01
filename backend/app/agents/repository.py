from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.agents.models import (
    AgentCreate,
    AgentDB,
    AgentMCPServerBindingDB,
    AgentPermissionWrite,
    AgentUserPermissionDB,
)
from app.users.models import WorkspaceRole


class AgentRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get(self, agent_id: UUID) -> AgentDB | None:
        result = await self.db.execute(select(AgentDB).where(AgentDB.id == agent_id))
        return result.scalar_one_or_none()

    async def list_with_permissions(
        self,
        user_id: UUID | None,
        user_role: WorkspaceRole | None,
    ) -> list:
        is_workspace_admin = user_role == WorkspaceRole.admin

        if user_id and not is_workspace_admin:
            query = (
                select(AgentDB, AgentMCPServerBindingDB,
                       AgentUserPermissionDB.permission)
                .outerjoin(
                    AgentMCPServerBindingDB, AgentDB.id == AgentMCPServerBindingDB.agent_id
                )
                .outerjoin(
                    AgentUserPermissionDB,
                    (AgentDB.id == AgentUserPermissionDB.agent_id)
                    & (AgentUserPermissionDB.user_id == user_id),
                )
                .order_by(AgentDB.created_at.asc())
            )
        else:
            query = (
                select(AgentDB, AgentMCPServerBindingDB)
                .outerjoin(
                    AgentMCPServerBindingDB, AgentDB.id == AgentMCPServerBindingDB.agent_id
                )
                .order_by(AgentDB.created_at.asc())
            )

        result = await self.db.execute(query)
        return result.all()

    async def create(self, data: AgentCreate) -> AgentDB:
        db_agent = AgentDB.model_validate(data)
        self.db.add(db_agent)
        await self.db.commit()
        await self.db.refresh(db_agent)
        return db_agent

    async def update(self, agent: AgentDB, data: dict) -> AgentDB:
        for key, value in data.items():
            setattr(agent, key, value)
        self.db.add(agent)
        await self.db.commit()
        await self.db.refresh(agent)
        return agent

    async def delete(self, agent: AgentDB) -> None:
        await self.db.delete(agent)
        await self.db.commit()

    async def get_binding(
        self, agent_id: UUID, server_id: UUID
    ) -> AgentMCPServerBindingDB | None:
        result = await self.db.execute(
            select(AgentMCPServerBindingDB).where(
                AgentMCPServerBindingDB.agent_id == agent_id,
                AgentMCPServerBindingDB.mcp_server_id == server_id,
            )
        )
        return result.scalar_one_or_none()

    async def create_binding(
        self, agent_id: UUID, server_id: UUID
    ) -> AgentMCPServerBindingDB:
        db_binding = AgentMCPServerBindingDB(
            agent_id=agent_id,
            mcp_server_id=server_id,
            tools=None,
        )
        self.db.add(db_binding)
        await self.db.commit()
        await self.db.refresh(db_binding)
        return db_binding

    async def update_binding(
        self, binding: AgentMCPServerBindingDB, data: dict
    ) -> AgentMCPServerBindingDB:
        for key, value in data.items():
            setattr(binding, key, value)
        self.db.add(binding)
        await self.db.commit()
        await self.db.refresh(binding)
        return binding

    async def delete_binding(self, binding: AgentMCPServerBindingDB) -> None:
        await self.db.delete(binding)
        await self.db.commit()

    async def get_permissions(self, agent_id: UUID) -> list[AgentUserPermissionDB]:
        result = await self.db.execute(
            select(AgentUserPermissionDB).where(
                AgentUserPermissionDB.agent_id == agent_id
            )
        )
        return list(result.scalars().all())

    async def set_permissions(
        self, agent_id: UUID, permissions: list[AgentPermissionWrite]
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

        await self.db.commit()
        for perm in new_permissions:
            await self.db.refresh(perm)
        return new_permissions
