import secrets
from uuid import UUID

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.tokens.models import PersonalAccessTokenDB
from app.auth.tokens.repository import PersonalAccessTokenRepository
from app.auth.tokens.schemas import PersonalAccessTokenCreateDB
from app.auth.utils import get_password_hash
from app.database import get_db
from app.exceptions import NotFoundError
from app.service import BaseService


TOKEN_PREFIX = "aux_"


class PersonalAccessTokenService(
    BaseService[PersonalAccessTokenDB, PersonalAccessTokenRepository]
):
    not_found_message = "Token not found"

    def __init__(self, db: AsyncSession):
        super().__init__(db, PersonalAccessTokenRepository(db))

    @staticmethod
    def _generate_token() -> tuple[str, str, str]:
        """Generate a new token. Returns (plaintext, hash, prefix)."""
        raw = secrets.token_urlsafe(32)
        plaintext = f"{TOKEN_PREFIX}{raw}"
        prefix = plaintext[:12]
        token_hash = get_password_hash(plaintext)
        return plaintext, token_hash, prefix

    async def create_token(
        self, user_id: UUID, name: str
    ) -> tuple[PersonalAccessTokenDB, str]:
        plaintext, token_hash, prefix = self._generate_token()
        data = PersonalAccessTokenCreateDB(
            user_id=user_id,
            name=name,
            token_hash=token_hash,
            prefix=prefix,
        )
        pat = await self.repository.create(data)
        return pat, plaintext

    async def list_tokens(self, user_id: UUID) -> list[PersonalAccessTokenDB]:
        return await self.repository.list_by_user(user_id)

    async def delete_token(self, token_id: UUID, user_id: UUID) -> None:
        pat = await self.get_or_404(token_id)
        if pat.user_id != user_id:
            raise NotFoundError(self.not_found_message)
        await self.repository.delete(pat)

    async def resolve_token(self, plaintext: str) -> PersonalAccessTokenDB | None:
        return await self.repository.resolve_token(plaintext)


def get_pat_service(db: AsyncSession = Depends(get_db)) -> PersonalAccessTokenService:
    return PersonalAccessTokenService(db)
