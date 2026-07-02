from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.repository import BaseRepository
from app.tags.models import TagDB


class TagRepository(BaseRepository[TagDB]):
    def __init__(self, db: AsyncSession):
        super().__init__(TagDB, db)

    async def list_all(self) -> list[TagDB]:
        stmt = select(TagDB).order_by(TagDB.name.asc())
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def list_by_ids(self, tag_ids: list[UUID]) -> list[TagDB]:
        if not tag_ids:
            return []
        stmt = select(TagDB).where(TagDB.id.in_(tag_ids))
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def get_by_name(self, name: str) -> TagDB | None:
        stmt = select(TagDB).where(TagDB.name == name)
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()
