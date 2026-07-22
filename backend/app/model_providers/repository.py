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
        self, provider: str, model_id: str
    ) -> ModelDB | None:
        stmt = select(ModelDB).where(
            ModelDB.provider == provider,
            ModelDB.model_id == model_id,
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_default(self) -> ModelDB | None:
        stmt = select(ModelDB).where(ModelDB.is_default)
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()
