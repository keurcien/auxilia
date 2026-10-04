from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col, select

from app.invites.models import InviteDB, InviteStatus
from app.repository import BaseRepository


class InviteRepository(BaseRepository[InviteDB]):
    def __init__(self, db: AsyncSession):
        super().__init__(InviteDB, db)

    async def get_by_token(self, token: str) -> InviteDB | None:
        stmt = select(InviteDB).where(InviteDB.token == token)
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_pending_by_email(
        self, email: str, workspace_id: UUID | None = None
    ) -> InviteDB | None:
        stmt = (
            select(InviteDB)
            .where(
                InviteDB.email == email,
                InviteDB.status == InviteStatus.pending,
            )
            .order_by(col(InviteDB.created_at).desc())
        )
        if workspace_id is not None:
            stmt = stmt.where(InviteDB.workspace_id == workspace_id)
        result = await self.db.execute(stmt)
        return result.scalars().first()

    async def list_pending(self, workspace_id: UUID) -> list[InviteDB]:
        stmt = select(InviteDB).where(
            InviteDB.workspace_id == workspace_id,
            InviteDB.status == InviteStatus.pending,
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def revoke_pending_by_email(self, workspace_id: UUID, email: str) -> None:
        """Set all pending invites for the given email to revoked (no commit)."""
        stmt = select(InviteDB).where(
            InviteDB.email == email,
            InviteDB.workspace_id == workspace_id,
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
