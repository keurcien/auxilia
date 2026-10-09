from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col, select

from app.repository import BaseRepository
from app.skills.models import SkillSourceDB


class SkillSourceRepository(BaseRepository[SkillSourceDB]):
    def __init__(self, db: AsyncSession, workspace_id: UUID):
        super().__init__(SkillSourceDB, db)
        self.workspace_id = workspace_id

    async def list_all(self) -> list[SkillSourceDB]:
        stmt = (
            select(SkillSourceDB)
            .where(SkillSourceDB.workspace_id == self.workspace_id)
            .order_by(col(SkillSourceDB.name), col(SkillSourceDB.id))
        )
        return list((await self.db.execute(stmt)).scalars().all())

    async def get_scoped(self, source_id: UUID) -> SkillSourceDB | None:
        stmt = select(SkillSourceDB).where(
            SkillSourceDB.id == source_id,
            SkillSourceDB.workspace_id == self.workspace_id,
        )
        return (await self.db.execute(stmt)).scalar_one_or_none()

    async def get_for_update(self, source_id: UUID) -> SkillSourceDB | None:
        """The row, locked for the rest of the transaction — one sync of a
        source at a time (`SkillSourceService._manageable`)."""
        stmt = (
            select(SkillSourceDB)
            .where(
                SkillSourceDB.id == source_id,
                SkillSourceDB.workspace_id == self.workspace_id,
            )
            .with_for_update()
        )
        return (await self.db.execute(stmt)).scalar_one_or_none()

    async def get_by_url(
        self, url: str, ref: str, subpath: str | None
    ) -> SkillSourceDB | None:
        stmt = select(SkillSourceDB).where(
            SkillSourceDB.workspace_id == self.workspace_id,
            SkillSourceDB.url == url,
            SkillSourceDB.ref == ref,
            col(SkillSourceDB.subpath).is_(subpath)
            if subpath is None
            else SkillSourceDB.subpath == subpath,
        )
        return (await self.db.execute(stmt)).scalar_one_or_none()
