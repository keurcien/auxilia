from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.repository import BaseRepository
from app.teams.models import TeamDB


class TeamRepository(BaseRepository[TeamDB]):
    def __init__(self, db: AsyncSession):
        super().__init__(TeamDB, db)

    async def list_all(self) -> list[TeamDB]:
        stmt = select(TeamDB).order_by(TeamDB.name.asc())
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def get_by_name(self, name: str) -> TeamDB | None:
        stmt = select(TeamDB).where(TeamDB.name == name)
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()
