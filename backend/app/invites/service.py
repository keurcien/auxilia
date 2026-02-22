import secrets
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.auth.settings import auth_settings
from app.invites.models import InviteDB, InviteStatus


async def create_invite(
    email: str,
    role: str,
    invited_by: UUID,
    db: AsyncSession,
) -> InviteDB:
    """Create a new invite, revoking any existing pending invite for the same email."""
    # Revoke existing pending invites for this email
    result = await db.execute(
        select(InviteDB).where(
            InviteDB.email == email,
            InviteDB.status == InviteStatus.pending,
        )
    )
    for existing in result.scalars().all():
        existing.status = InviteStatus.revoked
        db.add(existing)

    invite = InviteDB(
        email=email,
        role=role,
        token=secrets.token_urlsafe(32),
        invited_by=invited_by,
        expires_at=datetime.now(timezone.utc) + timedelta(days=7),
    )
    db.add(invite)
    await db.commit()
    await db.refresh(invite)
    return invite


async def get_invite_by_token(token: str, db: AsyncSession) -> InviteDB | None:
    result = await db.execute(select(InviteDB).where(InviteDB.token == token))
    return result.scalar_one_or_none()


async def validate_invite(token: str, db: AsyncSession) -> InviteDB | None:
    """Return the invite if it's pending and not expired, else None."""
    invite = await get_invite_by_token(token, db)
    if invite is None:
        return None
    if invite.status != InviteStatus.pending:
        return None
    if invite.expires_at < datetime.now(timezone.utc):
        return None
    return invite


async def get_pending_invite_by_email(email: str, db: AsyncSession) -> InviteDB | None:
    """Find a pending, non-expired invite by email."""
    result = await db.execute(
        select(InviteDB).where(
            InviteDB.email == email,
            InviteDB.status == InviteStatus.pending,
        )
    )
    invite = result.scalar_one_or_none()
    if invite is None:
        return None
    if invite.expires_at < datetime.now(timezone.utc):
        return None
    return invite


def build_invite_url(token: str) -> str:
    return f"{auth_settings.FRONTEND_URL}/invite/{token}"
