from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.repository import BaseRepository
from app.sandbox.models import SandboxDB


class SandboxRepository(BaseRepository[SandboxDB]):
    def __init__(self, db: AsyncSession):
        super().__init__(SandboxDB, db)

    async def list(self) -> list[SandboxDB]:
        stmt = select(SandboxDB).order_by(SandboxDB.created_at)
        result = await self.db.execute(stmt)
        return list(result.scalars().all())
