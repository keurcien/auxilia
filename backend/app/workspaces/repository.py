from uuid import UUID

from sqlalchemy import delete, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col, select

from app.repository import BaseRepository
from app.workspaces.models import WorkspaceDB, WorkspaceImageDB, WorkspaceMembershipDB


class WorkspaceRepository(BaseRepository[WorkspaceDB]):
    def __init__(self, db: AsyncSession):
        super().__init__(WorkspaceDB, db)

    async def list_for_user(
        self, user_id: UUID
    ) -> list[tuple[WorkspaceDB, WorkspaceMembershipDB]]:
        stmt = (
            select(WorkspaceDB, WorkspaceMembershipDB)
            .join(
                WorkspaceMembershipDB,
                col(WorkspaceMembershipDB.workspace_id) == col(WorkspaceDB.id),
            )
            .where(WorkspaceMembershipDB.user_id == user_id)
            .order_by(col(WorkspaceDB.created_at), col(WorkspaceDB.id))
        )
        result = await self.db.execute(stmt)
        return [(workspace, membership) for workspace, membership in result.all()]

    async def get_first_workspace(self) -> WorkspaceDB | None:
        stmt = (
            select(WorkspaceDB)
            .order_by(col(WorkspaceDB.created_at), col(WorkspaceDB.id))
            .limit(1)
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_membership(
        self, workspace_id: UUID, user_id: UUID
    ) -> WorkspaceMembershipDB | None:
        stmt = select(WorkspaceMembershipDB).where(
            WorkspaceMembershipDB.workspace_id == workspace_id,
            WorkspaceMembershipDB.user_id == user_id,
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_image(self, workspace_id: UUID) -> WorkspaceImageDB | None:
        stmt = select(WorkspaceImageDB).where(
            WorkspaceImageDB.workspace_id == workspace_id
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def _lock_image_parent(self, workspace_id: UUID) -> None:
        stmt = (
            select(WorkspaceDB.id)
            .where(WorkspaceDB.id == workspace_id)
            .with_for_update()
        )
        await self.db.execute(stmt)

    async def set_image(
        self,
        workspace_id: UUID,
        *,
        data: bytes,
        media_type: str,
        sha256: str,
        revision: UUID,
    ) -> None:
        await self._lock_image_parent(workspace_id)
        image = await self.get_image(workspace_id)
        if image is None:
            image = WorkspaceImageDB(
                workspace_id=workspace_id,
                data=data,
                media_type=media_type,
                sha256=sha256,
            )
        else:
            image.data = data
            image.media_type = media_type
            image.sha256 = sha256
        self.db.add(image)
        stmt = (
            update(WorkspaceDB)
            .where(col(WorkspaceDB.id) == workspace_id)
            .values(image_revision=revision)
        )
        await self.db.execute(stmt)
        await self.db.flush()

    async def delete_image(self, workspace_id: UUID) -> None:
        await self._lock_image_parent(workspace_id)
        delete_stmt = delete(WorkspaceImageDB).where(
            col(WorkspaceImageDB.workspace_id) == workspace_id
        )
        await self.db.execute(delete_stmt)
        update_stmt = (
            update(WorkspaceDB)
            .where(col(WorkspaceDB.id) == workspace_id)
            .values(image_revision=None)
        )
        await self.db.execute(update_stmt)
        await self.db.flush()

    async def get_first_membership(self, user_id: UUID) -> WorkspaceMembershipDB | None:
        stmt = (
            select(WorkspaceMembershipDB)
            .join(
                WorkspaceDB,
                col(WorkspaceDB.id) == col(WorkspaceMembershipDB.workspace_id),
            )
            .where(WorkspaceMembershipDB.user_id == user_id)
            .order_by(col(WorkspaceDB.created_at), col(WorkspaceDB.id))
            .limit(1)
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_first_membership_except(
        self, user_id: UUID, workspace_id: UUID
    ) -> WorkspaceMembershipDB | None:
        stmt = (
            select(WorkspaceMembershipDB)
            .join(
                WorkspaceDB,
                col(WorkspaceDB.id) == col(WorkspaceMembershipDB.workspace_id),
            )
            .where(
                WorkspaceMembershipDB.user_id == user_id,
                WorkspaceMembershipDB.workspace_id != workspace_id,
            )
            .order_by(col(WorkspaceDB.created_at), col(WorkspaceDB.id))
            .limit(1)
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def create_membership(
        self, membership: WorkspaceMembershipDB
    ) -> WorkspaceMembershipDB:
        self.db.add(membership)
        await self.db.flush()
        await self.db.refresh(membership)
        return membership

    async def delete_membership(self, membership: WorkspaceMembershipDB) -> None:
        await self.db.delete(membership)
        await self.db.flush()
