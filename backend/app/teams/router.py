from uuid import UUID

from fastapi import APIRouter, Depends

from app.auth.dependencies import get_current_user, require_admin
from app.teams.schemas import TeamCreate, TeamPatch, TeamResponse
from app.teams.service import TeamService, get_team_service
from app.users.models import UserDB
from app.workspaces.dependencies import get_active_workspace_id
from app.workspaces.service import WorkspaceService, get_workspace_service


router = APIRouter(prefix="/teams", tags=["teams"])


@router.get("/", response_model=list[TeamResponse])
async def list_teams(
    workspace_id: UUID | None = None,
    current_user: UserDB = Depends(get_current_user),
    active_workspace_id: UUID = Depends(get_active_workspace_id),
    service: TeamService = Depends(get_team_service),
    workspaces: WorkspaceService = Depends(get_workspace_service),
) -> list[TeamResponse]:
    target_workspace_id = workspace_id or active_workspace_id
    if workspace_id is not None:
        await workspaces.require_admin(target_workspace_id, current_user.id)
    return await service.list(target_workspace_id)


@router.post("/", response_model=TeamResponse, status_code=201)
async def create_team(
    data: TeamCreate,
    _: UserDB = Depends(require_admin),
    workspace_id: UUID = Depends(get_active_workspace_id),
    service: TeamService = Depends(get_team_service),
) -> TeamResponse:
    return await service.create(data, workspace_id)


@router.patch("/{team_id}", response_model=TeamResponse)
async def update_team(
    team_id: UUID,
    data: TeamPatch,
    _: UserDB = Depends(require_admin),
    workspace_id: UUID = Depends(get_active_workspace_id),
    service: TeamService = Depends(get_team_service),
) -> TeamResponse:
    return await service.update(team_id, workspace_id, data)


@router.delete("/{team_id}", status_code=204)
async def delete_team(
    team_id: UUID,
    _: UserDB = Depends(require_admin),
    workspace_id: UUID = Depends(get_active_workspace_id),
    service: TeamService = Depends(get_team_service),
) -> None:
    await service.delete(team_id, workspace_id)
