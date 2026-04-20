from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.invites.models import InviteDB, InviteStatus
from app.repository import BaseRepository


class InviteRepository(BaseRepository[InviteDB]):
    def __init__(self, db: AsyncSession):
        super().__init__(InviteDB, db)

    async def get_by_token(self, token: str) -> InviteDB | None:
        stmt = select(InviteDB).where(InviteDB.token == token)
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_pending_by_email(self, email: str) -> InviteDB | None:
        stmt = select(InviteDB).where(
            InviteDB.email == email,
            InviteDB.status == InviteStatus.pending,
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def list_pending(self) -> list[InviteDB]:
        stmt = select(InviteDB).where(InviteDB.status == InviteStatus.pending)
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def revoke_pending_by_email(self, email: str) -> None:
        """Set all pending invites for the given email to revoked (no commit)."""
        stmt = select(InviteDB).where(
            InviteDB.email == email,
            InviteDB.status == InviteStatus.pending,
        )
        result = await self.db.execute(stmt)
        for invite in result.scalars().all():
            invite.status = InviteStatus.revoked
            self.db.add(invite)

    async def set_status(self, invite: InviteDB, new_status: InviteStatus) -> InviteDB:
        invite.status = new_status
        self.db.add(invite)
        await self.db.flush()
        await self.db.refresh(invite)
        return invite
