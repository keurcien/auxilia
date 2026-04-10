from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.repository import BaseRepository
from app.users.models import UserDB, WorkspaceRole


class UserRepository(BaseRepository[UserDB]):
    def __init__(self, db: AsyncSession):
        super().__init__(UserDB, db)

    async def get_by_email(self, email: str) -> UserDB | None:
        stmt = select(UserDB).where(UserDB.email == email)
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def list(self, role: WorkspaceRole | None = None) -> list[UserDB]:
        stmt = select(UserDB)
        if role is not None:
            stmt = stmt.where(UserDB.role == role)
        result = await self.db.execute(stmt)
        return list(result.scalars().all())
