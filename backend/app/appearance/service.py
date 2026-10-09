from uuid import uuid4

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.appearance.models import InstanceAppearanceDB
from app.appearance.repository import InstanceAppearanceRepository
from app.appearance.schemas import InstanceAppearanceResponse
from app.database import get_db
from app.exceptions import DomainValidationError
from app.service import BaseService
from app.utils.images import ProcessedImage


class InstanceAppearanceService(
    BaseService[InstanceAppearanceDB, InstanceAppearanceRepository]
):
    def __init__(self, db: AsyncSession):
        super().__init__(db, InstanceAppearanceRepository(db))

    @staticmethod
    def to_response(
        row: InstanceAppearanceDB | None,
    ) -> InstanceAppearanceResponse:
        if row is None:
            return InstanceAppearanceResponse(app_name="auxilia")
        return InstanceAppearanceResponse(
            app_name=row.app_name,
            logo_revision=row.logo_revision,
        )

    async def get_settings(self) -> InstanceAppearanceResponse:
        return self.to_response(await self.repository.get_settings())

    async def update_name(self, app_name: str) -> InstanceAppearanceResponse:
        app_name = app_name.strip()
        if not app_name:
            raise DomainValidationError("Application name cannot be empty")
        row = await self.repository.get_or_create()
        row.app_name = app_name
        self.db.add(row)
        await self.db.flush()
        await self.db.refresh(row)
        return self.to_response(row)

    async def set_logo(self, image: ProcessedImage) -> InstanceAppearanceResponse:
        row = await self.repository.get_or_create()
        row.logo_data = image.data
        row.logo_media_type = image.media_type
        row.logo_sha256 = image.sha256
        row.logo_revision = uuid4()
        self.db.add(row)
        await self.db.flush()
        await self.db.refresh(row)
        return self.to_response(row)

    async def delete_logo(self) -> InstanceAppearanceResponse:
        row = await self.repository.get_settings()
        if row is None:
            return self.to_response(None)
        row.logo_data = None
        row.logo_media_type = None
        row.logo_sha256 = None
        row.logo_revision = None
        self.db.add(row)
        await self.db.flush()
        await self.db.refresh(row)
        return self.to_response(row)

    async def get_logo(self) -> InstanceAppearanceDB | None:
        row = await self.repository.get_settings()
        return row if row is not None and row.logo_data is not None else None


def get_instance_appearance_service(
    db: AsyncSession = Depends(get_db),
) -> InstanceAppearanceService:
    return InstanceAppearanceService(db)
