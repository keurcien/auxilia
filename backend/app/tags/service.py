from __future__ import annotations

from uuid import UUID

from fastapi import Depends
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.exceptions import AlreadyExistsError, DomainValidationError
from app.service import BaseService
from app.tags.models import TagDB
from app.tags.repository import TagRepository
from app.tags.schemas import TagCreate, TagPatch


class TagService(BaseService[TagDB, TagRepository]):
    not_found_message = "Tag not found"

    def __init__(self, db: AsyncSession):
        super().__init__(db, TagRepository(db))

    async def _ensure_name_available(self, name: str) -> None:
        if await self.repository.get_by_name(name):
            raise AlreadyExistsError("Tag name already exists")

    async def list(self) -> list[TagDB]:
        return await self.repository.list_all()

    async def list_by_ids(self, tag_ids: list[UUID]) -> list[TagDB]:
        return await self.repository.list_by_ids(tag_ids)

    async def get(self, tag_id: UUID) -> TagDB:
        return await self.get_or_404(tag_id)

    async def create(self, data: TagCreate) -> TagDB:
        # Store the trimmed name so " Data " can't slip past the unique index
        # as a visually identical duplicate of "Data".
        name = (data.name or "").strip()
        if not name:
            raise DomainValidationError("Tag name cannot be empty")
        data.name = name
        await self._ensure_name_available(name)
        try:
            return await self.repository.create(data)
        except IntegrityError as exc:
            # Lost a race against a concurrent create with the same name.
            raise AlreadyExistsError("Tag name already exists") from exc

    async def update(self, tag_id: UUID, data: TagPatch) -> TagDB:
        tag = await self.get_or_404(tag_id)
        update_data = data.model_dump(exclude_unset=True)
        if "name" in update_data:
            new_name = (update_data["name"] or "").strip()
            if not new_name:
                raise DomainValidationError("Tag name cannot be empty")
            data.name = new_name
            if new_name != tag.name:
                await self._ensure_name_available(new_name)
        try:
            return await self.repository.update(tag, data)
        except IntegrityError as exc:
            raise AlreadyExistsError("Tag name already exists") from exc

    async def delete(self, tag_id: UUID) -> None:
        tag = await self.get_or_404(tag_id)
        await self.repository.delete(tag)


def get_tag_service(db: AsyncSession = Depends(get_db)) -> TagService:
    return TagService(db)
