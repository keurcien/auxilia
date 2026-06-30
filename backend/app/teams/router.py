from uuid import UUID

from fastapi import APIRouter, Depends

from app.auth.dependencies import get_current_user, require_admin
from app.teams.schemas import TeamCreate, TeamPatch, TeamResponse
from app.teams.service import TeamService, get_team_service
from app.users.models import UserDB


router = APIRouter(prefix="/teams", tags=["teams"])


@router.get("/", response_model=list[TeamResponse])
async def list_teams(
    _: UserDB = Depends(get_current_user),
    service: TeamService = Depends(get_team_service),
) -> list[TeamResponse]:
    return await service.list()


@router.post("/", response_model=TeamResponse, status_code=201)
async def create_team(
    data: TeamCreate,
    _: UserDB = Depends(require_admin),
    service: TeamService = Depends(get_team_service),
) -> TeamResponse:
    return await service.create(data)


@router.patch("/{team_id}", response_model=TeamResponse)
async def update_team(
    team_id: UUID,
    data: TeamPatch,
    _: UserDB = Depends(require_admin),
    service: TeamService = Depends(get_team_service),
) -> TeamResponse:
    return await service.update(team_id, data)


@router.delete("/{team_id}", status_code=204)
async def delete_team(
    team_id: UUID,
    _: UserDB = Depends(require_admin),
    service: TeamService = Depends(get_team_service),
) -> None:
    await service.delete(team_id)
