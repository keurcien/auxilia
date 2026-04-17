import secrets
from datetime import UTC, datetime, timedelta
from uuid import UUID

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.auth.settings import auth_settings
from app.database import get_db
from app.exceptions import AlreadyExistsError
from app.invites.models import InviteCreateDB, InviteDB, InviteStatus
from app.invites.repository import InviteRepository
from app.service import BaseService
from app.users.models import UserDB


class InviteService(BaseService[InviteDB, InviteRepository]):
    not_found_message = "Invite not found"

    def __init__(self, db: AsyncSession):
        super().__init__(db, InviteRepository(db))

    def build_invite_url(self, token: str) -> str:
        return f"{auth_settings.FRONTEND_URL}/invite/{token}"

    @staticmethod
    def _is_usable(invite: InviteDB | None) -> bool:
        return (
            invite is not None
            and invite.status == InviteStatus.pending
            and invite.expires_at >= datetime.now(UTC)
        )

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
            expires_at=datetime.now(UTC) + timedelta(days=7),
        )
        return await self.repository.create(data)

    async def validate_invite(self, token: str) -> InviteDB | None:
        invite = await self.repository.get_by_token(token)
        return invite if self._is_usable(invite) else None

    async def get_pending_by_email(self, email: str) -> InviteDB | None:
        invite = await self.repository.get_pending_by_email(email)
        return invite if self._is_usable(invite) else None

    async def list_pending_with_inviters(self) -> list[tuple[InviteDB, str | None]]:
        invites = await self.repository.list_pending()
        inviter_ids = list({inv.invited_by for inv in invites})
        if not inviter_ids:
            return [(inv, None) for inv in invites]
        users_result = await self.db.execute(
            select(UserDB).where(UserDB.id.in_(inviter_ids))
        )
        inviters = {user.id: user.name for user in users_result.scalars().all()}
        return [(inv, inviters.get(inv.invited_by)) for inv in invites]

    async def revoke(self, invite_id: UUID) -> InviteDB | None:
        invite = await self.repository.get(invite_id)
        if invite is None:
            return None
        return await self.repository.set_status(invite, InviteStatus.revoked)


def get_invite_service(db: AsyncSession = Depends(get_db)) -> InviteService:
    return InviteService(db)
