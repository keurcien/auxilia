import secrets
from datetime import datetime, timedelta, timezone
from uuid import UUID

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.auth.settings import auth_settings
from app.database import get_db
from app.exceptions import AlreadyExistsError
from app.invites.models import InviteCreateDB, InviteDB, InviteStatus
from app.invites.repository import InviteRepository
from app.users.models import UserDB


class InviteService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.repository = InviteRepository(db)

    def build_invite_url(self, token: str) -> str:
        return f"{auth_settings.FRONTEND_URL}/invite/{token}"

    async def create_invite(self, email: str, role: str, invited_by: UUID) -> InviteDB:
        """Create a new invite, revoking any existing pending invite for the same email."""
        result = await self.db.execute(select(UserDB).where(UserDB.email == email))
        if result.scalar_one_or_none():
            raise AlreadyExistsError("Email already registered")
        await self.repository.revoke_pending_by_email(email)
        data = InviteCreateDB(
            email=email,
            role=role,
            token=secrets.token_urlsafe(32),
            invited_by=invited_by,
            expires_at=datetime.now(timezone.utc) + timedelta(days=7),
        )
        invite = await self.repository.create(data)
        await self.db.commit()
        return invite

    async def validate_invite(self, token: str) -> InviteDB | None:
        """Return the invite if it's pending and not expired, else None."""
        invite = await self.repository.get_by_token(token)
        if invite is None or invite.status != InviteStatus.pending:
            return None
        if invite.expires_at < datetime.now(timezone.utc):
            return None
        return invite

    async def get_pending_by_email(self, email: str) -> InviteDB | None:
        """Find a pending, non-expired invite by email."""
        invite = await self.repository.get_pending_by_email(email)
        if invite is None or invite.expires_at < datetime.now(timezone.utc):
            return None
        return invite

    async def list_pending_with_inviters(self) -> list[tuple[InviteDB, str | None]]:
        invites = await self.repository.list_pending()
        inviter_ids = list({inv.invited_by for inv in invites})
        inviters: dict[UUID, str | None] = {}
        if inviter_ids:
            users_result = await self.db.execute(
                select(UserDB).where(UserDB.id.in_(inviter_ids))
            )
            for user in users_result.scalars().all():
                inviters[user.id] = user.name
        return [(inv, inviters.get(inv.invited_by)) for inv in invites]

    async def revoke(self, invite_id: UUID) -> InviteDB | None:
        invite = await self.repository.get(invite_id)
        if invite is None:
            return None
        result = await self.repository.set_status(invite, InviteStatus.revoked)
        await self.db.commit()
        return result


def get_invite_service(db: AsyncSession = Depends(get_db)) -> InviteService:
    return InviteService(db)
