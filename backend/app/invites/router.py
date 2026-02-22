from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.auth.dependencies import require_admin
from app.database import get_db
from app.invites.models import InviteDB, InviteStatus
from app.invites.schemas import InviteCreate, InviteRead
from app.invites.service import build_invite_url, create_invite
from app.users.models import UserDB

router = APIRouter(prefix="/invites", tags=["invites"])


def _invite_to_read(invite: InviteDB, include_url: bool = False) -> InviteRead:
    return InviteRead(
        id=invite.id,
        email=invite.email,
        role=invite.role,
        status=invite.status.value,
        invite_url=build_invite_url(invite.token) if include_url else None,
        invited_by=invite.invited_by,
        expires_at=invite.expires_at,
        created_at=invite.created_at,
    )


@router.post("/", response_model=InviteRead, status_code=201)
async def create_invite_endpoint(
    data: InviteCreate,
    current_user: UserDB = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> InviteRead:
    """Create an invite for a new user. Admin only."""
    # Check if email is already registered
    result = await db.execute(select(UserDB).where(UserDB.email == data.email))
    if result.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered",
        )

    invite = await create_invite(
        email=data.email,
        role=data.role.value,
        invited_by=current_user.id,
        db=db,
    )
    return _invite_to_read(invite, include_url=True)


@router.get("/", response_model=list[InviteRead])
async def list_invites(
    current_user: UserDB = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> list[InviteRead]:
    """List pending invites. Admin only."""
    result = await db.execute(
        select(InviteDB).where(InviteDB.status == InviteStatus.pending)
    )
    invites = result.scalars().all()
    return [_invite_to_read(inv) for inv in invites]


@router.delete("/{invite_id}", status_code=204)
async def revoke_invite(
    invite_id: UUID,
    current_user: UserDB = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Revoke an invite. Admin only."""
    result = await db.execute(select(InviteDB).where(InviteDB.id == invite_id))
    invite = result.scalar_one_or_none()
    if not invite:
        raise HTTPException(status_code=404, detail="Invite not found")

    invite.status = InviteStatus.revoked
    db.add(invite)
    await db.commit()
