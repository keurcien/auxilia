from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.auth.tokens.models import PersonalAccessTokenDB
from app.auth.utils import verify_password
from app.repositories import BaseRepository


class PersonalAccessTokenRepository(BaseRepository[PersonalAccessTokenDB]):
    def __init__(self, db: AsyncSession):
        super().__init__(PersonalAccessTokenDB, db)

    async def list_by_user(self, user_id: UUID) -> list[PersonalAccessTokenDB]:
        stmt = (
            select(PersonalAccessTokenDB)
            .where(PersonalAccessTokenDB.user_id == user_id)
            .order_by(PersonalAccessTokenDB.created_at.desc())
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def resolve_token(self, plaintext: str) -> PersonalAccessTokenDB | None:
        """Find the PAT matching a plaintext token by prefix, then verify hash."""
        prefix = plaintext[:12]
        stmt = select(PersonalAccessTokenDB).where(
            PersonalAccessTokenDB.prefix == prefix
        )
        result = await self.db.execute(stmt)
        candidates = result.scalars().all()
        for pat in candidates:
            if verify_password(plaintext, pat.token_hash):
                return pat
        return None
