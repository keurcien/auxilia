from uuid import UUID

from fastapi import Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.tokens.models import PersonalAccessTokenDB
from app.auth.tokens.repository import PersonalAccessTokenRepository
from app.database import get_db


class PersonalAccessTokenService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.repository = PersonalAccessTokenRepository(db)

    async def create_token(
        self, user_id: UUID, name: str
    ) -> tuple[PersonalAccessTokenDB, str]:
        return await self.repository.create(user_id, name)

    async def list_tokens(self, user_id: UUID) -> list[PersonalAccessTokenDB]:
        return await self.repository.list_by_user(user_id)

    async def delete_token(self, token_id: UUID, user_id: UUID) -> None:
        pat = await self.repository.get(token_id)
        if not pat or pat.user_id != user_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Token not found",
            )
        await self.repository.delete(pat)

    async def resolve_token(self, plaintext: str) -> PersonalAccessTokenDB | None:
        return await self.repository.resolve_token(plaintext)


def get_pat_service(db: AsyncSession = Depends(get_db)) -> PersonalAccessTokenService:
    return PersonalAccessTokenService(db)
