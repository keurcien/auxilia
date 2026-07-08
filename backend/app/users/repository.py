from uuid import UUID

from sqlalchemy import func, or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.pagination import PageParams
from app.repository import BaseRepository
from app.users.models import UserDB, WorkspaceRole


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


class UserRepository(BaseRepository[UserDB]):
    def __init__(self, db: AsyncSession):
        super().__init__(UserDB, db)

    async def list_by_ids(self, user_ids: list[UUID]) -> list[UserDB]:
        if not user_ids:
            return []
        stmt = select(UserDB).where(UserDB.id.in_(user_ids))
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def get_by_email(self, email: str) -> UserDB | None:
        stmt = select(UserDB).where(UserDB.email == email)
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def list(
        self,
        page: PageParams,
        role: WorkspaceRole | None = None,
        search: str | None = None,
    ) -> tuple[list[UserDB], int]:
        stmt = select(UserDB).order_by(UserDB.created_at.desc(), UserDB.id)
        if role is not None:
            stmt = stmt.where(UserDB.role == role)
        if search:
            pattern = f"%{_escape_like(search)}%"
            stmt = stmt.where(
                or_(
                    UserDB.name.ilike(pattern, escape="\\"),
                    UserDB.email.ilike(pattern, escape="\\"),
                )
            )
        result, total = await self.paginate(stmt, page)
        return list(result.scalars().all()), total

    async def count_by_role(self) -> dict[WorkspaceRole, int]:
        stmt = select(UserDB.role, func.count()).group_by(UserDB.role)
        result = await self.db.execute(stmt)
        return dict(result.all())
