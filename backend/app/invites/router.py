from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException

from app.auth.dependencies import require_admin
from app.invites.models import InviteDB
from app.invites.schemas import InviteCreate, InviteRead
from app.invites.service import InviteService, get_invite_service
from app.users.models import UserDB

router = APIRouter(prefix="/invites", tags=["invites"])


def _invite_to_read(
    invite: InviteDB,
    service: InviteService,
    include_url: bool = False,
    invited_by_name: str | None = None,
) -> InviteRead:
    return InviteRead(
        id=invite.id,
        email=invite.email,
        role=invite.role,
        status=invite.status.value,
        invite_url=service.build_invite_url(invite.token) if include_url else None,
        invited_by=invite.invited_by,
        invited_by_name=invited_by_name,
        expires_at=invite.expires_at,
        created_at=invite.created_at,
    )


@router.post("/", response_model=InviteRead, status_code=201)
async def create_invite_endpoint(
    data: InviteCreate,
    current_user: UserDB = Depends(require_admin),
    service: InviteService = Depends(get_invite_service),
) -> InviteRead:
    """Create an invite for a new user. Admin only."""
    invite = await service.create_invite(
        email=data.email,
        role=data.role.value,
        invited_by=current_user.id,
    )
    return _invite_to_read(invite, service, include_url=True)


@router.get("/", response_model=list[InviteRead])
async def list_invites(
    current_user: UserDB = Depends(require_admin),
    service: InviteService = Depends(get_invite_service),
) -> list[InviteRead]:
    """List pending invites. Admin only."""
    invites_with_inviters = await service.list_pending_with_inviters()
    return [
        _invite_to_read(inv, service, include_url=True, invited_by_name=name)
        for inv, name in invites_with_inviters
    ]


@router.delete("/{invite_id}", status_code=204)
async def revoke_invite(
    invite_id: UUID,
    current_user: UserDB = Depends(require_admin),
    service: InviteService = Depends(get_invite_service),
) -> None:
    """Revoke an invite. Admin only."""
    invite = await service.revoke(invite_id)
    if not invite:
        raise HTTPException(status_code=404, detail="Invite not found")
