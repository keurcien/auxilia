from sqlalchemy import func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.repository import BaseRepository
from app.teams.models import TeamDB
from app.users.models import UserDB


class TeamRepository(BaseRepository[TeamDB]):
    def __init__(self, db: AsyncSession):
        super().__init__(TeamDB, db)

    async def list_with_member_counts(self) -> list[tuple[TeamDB, int]]:
        stmt = (
            select(TeamDB, func.count(UserDB.id))
            .outerjoin(UserDB, UserDB.team_id == TeamDB.id)
            .group_by(TeamDB.id)
            .order_by(TeamDB.name.asc())
        )
        result = await self.db.execute(stmt)
        return [(team, count) for team, count in result.all()]

    async def get_by_name(self, name: str) -> TeamDB | None:
        stmt = select(TeamDB).where(TeamDB.name == name)
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()
