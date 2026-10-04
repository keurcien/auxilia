from uuid import UUID

from fastapi import APIRouter, Depends

from app.auth.dependencies import get_current_user, require_admin
from app.exceptions import NotFoundError
from app.invites.schemas import InviteCreate, InviteResponse
from app.invites.service import InviteService, get_invite_service
from app.users.models import UserDB
from app.workspaces.dependencies import get_active_workspace_id
from app.workspaces.service import WorkspaceService, get_workspace_service


router = APIRouter(prefix="/invites", tags=["invites"])


@router.post("/", response_model=InviteResponse, status_code=201)
async def create_invite(
    data: InviteCreate,
    current_user: UserDB = Depends(get_current_user),
    active_workspace_id: UUID = Depends(get_active_workspace_id),
    service: InviteService = Depends(get_invite_service),
    workspaces: WorkspaceService = Depends(get_workspace_service),
) -> InviteResponse:
    """Create an invite for a new user. Admin only."""
    workspace_id = data.workspace_id or active_workspace_id
    await workspaces.require_admin(workspace_id, current_user.id)
    invite = await service.create(
        email=data.email,
        role=data.role.value,
        invited_by=current_user.id,
        workspace_id=workspace_id,
        team_id=data.team_id,
    )
    return service._to_response(invite, include_url=True)


@router.get("/", response_model=list[InviteResponse])
async def list_invites(
    _: UserDB = Depends(require_admin),
    workspace_id: UUID = Depends(get_active_workspace_id),
    service: InviteService = Depends(get_invite_service),
) -> list[InviteResponse]:
    """List pending invites. Admin only."""
    invites_with_inviters = await service.list_pending_with_inviters(workspace_id)
    return [
        service._to_response(inv, include_url=True, invited_by_name=name)
        for inv, name in invites_with_inviters
    ]


@router.delete("/{invite_id}", status_code=204)
async def revoke_invite(
    invite_id: UUID,
    _: UserDB = Depends(require_admin),
    workspace_id: UUID = Depends(get_active_workspace_id),
    service: InviteService = Depends(get_invite_service),
) -> None:
    """Revoke an invite. Admin only."""
    invite = await service.revoke(invite_id, workspace_id)
    if not invite:
        raise NotFoundError("Invite not found")
