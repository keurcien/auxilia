from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col, select

from app.repository import BaseRepository
from app.skills.models import SkillSourceDB


class SkillSourceRepository(BaseRepository[SkillSourceDB]):
    def __init__(self, db: AsyncSession):
        super().__init__(SkillSourceDB, db)

    async def list_all(self) -> list[SkillSourceDB]:
        stmt = select(SkillSourceDB).order_by(
            col(SkillSourceDB.name), col(SkillSourceDB.id)
        )
        return list((await self.db.execute(stmt)).scalars().all())

    async def get_by_url(
        self, url: str, ref: str, subpath: str | None
    ) -> SkillSourceDB | None:
        stmt = select(SkillSourceDB).where(
            SkillSourceDB.url == url,
            SkillSourceDB.ref == ref,
            col(SkillSourceDB.subpath).is_(subpath)
            if subpath is None
            else SkillSourceDB.subpath == subpath,
        )
        return (await self.db.execute(stmt)).scalar_one_or_none()
