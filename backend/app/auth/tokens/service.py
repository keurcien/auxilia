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


TOKEN_PREFIX = "aux_"


class PersonalAccessTokenService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.repository = PersonalAccessTokenRepository(db)

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
        await self.db.commit()
        return pat, plaintext

    async def list_tokens(self, user_id: UUID) -> list[PersonalAccessTokenDB]:
        return await self.repository.list_by_user(user_id)

    async def delete_token(self, token_id: UUID, user_id: UUID) -> None:
        pat = await self.repository.get(token_id)
        if not pat or pat.user_id != user_id:
            raise NotFoundError("Token not found")
        await self.repository.delete(pat)
        await self.db.commit()

    async def resolve_token(self, plaintext: str) -> PersonalAccessTokenDB | None:
        return await self.repository.resolve_token(plaintext)


def get_pat_service(db: AsyncSession = Depends(get_db)) -> PersonalAccessTokenService:
    return PersonalAccessTokenService(db)
