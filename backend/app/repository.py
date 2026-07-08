from typing import Generic, TypeVar
from uuid import UUID

from sqlalchemy import func
from sqlalchemy.engine import Result
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import Select
from sqlmodel import SQLModel, select

from app.pagination import PageParams


ModelType = TypeVar("ModelType", bound=SQLModel)


class BaseRepository(Generic[ModelType]):
    """Base repository with generic CRUD operations for SQLModel classes."""

    def __init__(self, model: type[ModelType], db: AsyncSession):
        self.model = model
        self.db = db

    async def get(self, id: UUID) -> ModelType | None:
        stmt = select(self.model).where(self.model.id == id)
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def paginate(self, stmt: Select, page: PageParams) -> tuple[Result, int]:
        """Execute ``stmt`` with the page's LIMIT/OFFSET applied and return the
        result together with the unpaginated row count.

        Callers consume the result the same way they would for the unpaginated
        statement (``.all()`` for multi-column rows, ``.scalars().all()`` for
        single-entity selects)."""
        count_stmt = select(func.count()).select_from(stmt.order_by(None).subquery())
        count_result = await self.db.execute(count_stmt)
        total = count_result.scalar_one()
        result = await self.db.execute(stmt.limit(page.limit).offset(page.offset))
        return result, total

    async def create(self, obj_in: SQLModel) -> ModelType:
        db_obj = self.model.model_validate(obj_in)
        self.db.add(db_obj)
        await self.db.flush()
        await self.db.refresh(db_obj)
        return db_obj

    async def update(self, db_obj: ModelType, obj_in: SQLModel) -> ModelType:
        update_data = obj_in.model_dump(exclude_unset=True)
        db_obj.sqlmodel_update(update_data)
        self.db.add(db_obj)
        await self.db.flush()
        await self.db.refresh(db_obj)
        return db_obj

    async def delete(self, db_obj: ModelType) -> None:
        await self.db.delete(db_obj)
        await self.db.flush()
