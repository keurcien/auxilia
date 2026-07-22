from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.model_providers.models import ModelDB
from app.repository import BaseRepository


class ModelRepository(BaseRepository[ModelDB]):
    def __init__(self, db: AsyncSession):
        super().__init__(ModelDB, db)

    async def list_all(self) -> list[ModelDB]:
        stmt = select(ModelDB)
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def get_by_provider_and_model_id(
        self, provider: str, model_id: str, *, for_update: bool = False
    ) -> ModelDB | None:
        stmt = select(ModelDB).where(
            ModelDB.provider == provider,
            ModelDB.model_id == model_id,
        )
        if for_update:
            stmt = stmt.with_for_update()
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_default(self, *, for_update: bool = False) -> ModelDB | None:
        stmt = select(ModelDB).where(ModelDB.is_default)
        if for_update:
            stmt = stmt.with_for_update()
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()
