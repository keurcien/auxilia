import secrets
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.invites.models import InviteDB, InviteStatus


class InviteRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get(self, invite_id: UUID) -> InviteDB | None:
        result = await self.db.execute(select(InviteDB).where(InviteDB.id == invite_id))
        return result.scalar_one_or_none()

    async def get_by_token(self, token: str) -> InviteDB | None:
        result = await self.db.execute(select(InviteDB).where(InviteDB.token == token))
        return result.scalar_one_or_none()

    async def get_pending_by_email(self, email: str) -> InviteDB | None:
        result = await self.db.execute(
            select(InviteDB).where(
                InviteDB.email == email,
                InviteDB.status == InviteStatus.pending,
            )
        )
        return result.scalar_one_or_none()

    async def list_pending(self) -> list[InviteDB]:
        result = await self.db.execute(
            select(InviteDB).where(InviteDB.status == InviteStatus.pending)
        )
        return list(result.scalars().all())

    async def revoke_pending_by_email(self, email: str) -> None:
        """Set all pending invites for the given email to revoked (no commit)."""
        result = await self.db.execute(
            select(InviteDB).where(
                InviteDB.email == email,
                InviteDB.status == InviteStatus.pending,
            )
        )
        for invite in result.scalars().all():
            invite.status = InviteStatus.revoked
            self.db.add(invite)

    async def create(self, email: str, role: str, invited_by: UUID) -> InviteDB:
        invite = InviteDB(
            email=email,
            role=role,
            token=secrets.token_urlsafe(32),
            invited_by=invited_by,
            expires_at=datetime.now(timezone.utc) + timedelta(days=7),
        )
        self.db.add(invite)
        await self.db.commit()
        await self.db.refresh(invite)
        return invite

    async def set_status(self, invite: InviteDB, new_status: InviteStatus) -> InviteDB:
        invite.status = new_status
        self.db.add(invite)
        await self.db.commit()
        await self.db.refresh(invite)
        return invite
