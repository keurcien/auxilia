from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.appearance.models import InstanceAppearanceDB
from app.repository import BaseRepository


class InstanceAppearanceRepository(BaseRepository[InstanceAppearanceDB]):
    def __init__(self, db: AsyncSession):
        super().__init__(InstanceAppearanceDB, db)

    async def get_settings(self) -> InstanceAppearanceDB | None:
        stmt = select(InstanceAppearanceDB).where(
            InstanceAppearanceDB.key == "default",
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_or_create(self) -> InstanceAppearanceDB:
        row = await self.get_settings()
        if row is None:
            try:
                async with self.db.begin_nested():
                    row = InstanceAppearanceDB()
                    self.db.add(row)
                    await self.db.flush()
            except IntegrityError:
                row = await self.get_settings()
                if row is None:
                    raise
            await self.db.refresh(row)
        return row
