from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.repository import BaseRepository
from app.sandbox.models import SandboxDB


class SandboxRepository(BaseRepository[SandboxDB]):
    def __init__(self, db: AsyncSession):
        super().__init__(SandboxDB, db)

    async def list(self, workspace_id: UUID) -> list[SandboxDB]:
        stmt = (
            select(SandboxDB)
            .where(SandboxDB.workspace_id == workspace_id)
            .order_by(SandboxDB.created_at)
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def get_scoped(
        self, sandbox_id: UUID, workspace_id: UUID
    ) -> SandboxDB | None:
        stmt = select(SandboxDB).where(
            SandboxDB.id == sandbox_id,
            SandboxDB.workspace_id == workspace_id,
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()
