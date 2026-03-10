import secrets
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.auth.tokens.models import PersonalAccessTokenDB
from app.auth.utils import get_password_hash, verify_password


TOKEN_PREFIX = "aux_"


class PersonalAccessTokenRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    def generate_token(self) -> tuple[str, str, str]:
        """Generate a new token. Returns (plaintext, hash, prefix)."""
        raw = secrets.token_urlsafe(32)
        plaintext = f"{TOKEN_PREFIX}{raw}"
        prefix = plaintext[:12]
        token_hash = get_password_hash(plaintext)
        return plaintext, token_hash, prefix

    async def create(
        self, user_id: UUID, name: str
    ) -> tuple[PersonalAccessTokenDB, str]:
        """Create a PAT. Returns (db_record, plaintext_token)."""
        plaintext, token_hash, prefix = self.generate_token()
        pat = PersonalAccessTokenDB(
            user_id=user_id,
            name=name,
            token_hash=token_hash,
            prefix=prefix,
        )
        self.db.add(pat)
        await self.db.commit()
        await self.db.refresh(pat)
        return pat, plaintext

    async def list_by_user(self, user_id: UUID) -> list[PersonalAccessTokenDB]:
        result = await self.db.execute(
            select(PersonalAccessTokenDB)
            .where(PersonalAccessTokenDB.user_id == user_id)
            .order_by(PersonalAccessTokenDB.created_at.desc())
        )
        return list(result.scalars().all())

    async def get(self, token_id: UUID) -> PersonalAccessTokenDB | None:
        result = await self.db.execute(
            select(PersonalAccessTokenDB).where(
                PersonalAccessTokenDB.id == token_id
            )
        )
        return result.scalar_one_or_none()

    async def delete(self, pat: PersonalAccessTokenDB) -> None:
        await self.db.delete(pat)
        await self.db.commit()

    async def resolve_token(self, plaintext: str) -> PersonalAccessTokenDB | None:
        """Find the PAT matching a plaintext token by prefix, then verify hash."""
        prefix = plaintext[:12]
        result = await self.db.execute(
            select(PersonalAccessTokenDB).where(
                PersonalAccessTokenDB.prefix == prefix
            )
        )
        candidates = result.scalars().all()
        for pat in candidates:
            if verify_password(plaintext, pat.token_hash):
                return pat
        return None
