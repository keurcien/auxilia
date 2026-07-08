from uuid import UUID

from fastapi import APIRouter, Depends

from app.auth.dependencies import get_current_user, require_admin
from app.pagination import Page, PageParams
from app.users.models import UserDB, WorkspaceRole
from app.users.schemas import (
    UserCreate,
    UserPatch,
    UserResponse,
    UserRoleCounts,
    UserRolePatch,
    UserTeamPatch,
)
from app.users.service import UserService, get_user_service


router = APIRouter(prefix="/users", tags=["users"])


@router.post("/", response_model=UserResponse, status_code=201)
async def create_user(
    user: UserCreate,
    _: UserDB = Depends(require_admin),
    service: UserService = Depends(get_user_service),
) -> UserResponse:
    return await service.create(user)


@router.get("/", response_model=Page[UserResponse])
async def get_users(
    role: WorkspaceRole | None = None,
    search: str | None = None,
    page: PageParams = Depends(),
    _: UserDB = Depends(get_current_user),
    service: UserService = Depends(get_user_service),
) -> Page[UserResponse]:
    return await service.list(page, role=role, search=search)


# Declared before /{user_id} so "role-counts" is not captured as a user id.
@router.get("/role-counts", response_model=UserRoleCounts)
async def count_users_by_role(
    _: UserDB = Depends(get_current_user),
    service: UserService = Depends(get_user_service),
) -> UserRoleCounts:
    return await service.count_by_role()


@router.get("/{user_id}", response_model=UserResponse)
async def get_user(
    user_id: UUID,
    _: UserDB = Depends(get_current_user),
    service: UserService = Depends(get_user_service),
) -> UserResponse:
    return await service.get(user_id)


@router.get("/email/{email}", response_model=UserResponse)
async def get_user_by_email(
    email: str,
    _: UserDB = Depends(get_current_user),
    service: UserService = Depends(get_user_service),
) -> UserResponse:
    return await service.get_by_email(email)


@router.patch("/{user_id}", response_model=UserResponse)
async def update_user(
    user_id: UUID,
    user_update: UserPatch,
    _: UserDB = Depends(require_admin),
    service: UserService = Depends(get_user_service),
) -> UserResponse:
    return await service.update(user_id, user_update)


@router.patch("/{user_id}/role", response_model=UserResponse)
async def update_user_role(
    user_id: UUID,
    role_update: UserRolePatch,
    _: UserDB = Depends(require_admin),
    service: UserService = Depends(get_user_service),
) -> UserResponse:
    return await service.update_role(user_id, role_update)


@router.patch("/{user_id}/team", response_model=UserResponse)
async def update_user_team(
    user_id: UUID,
    team_update: UserTeamPatch,
    _: UserDB = Depends(require_admin),
    service: UserService = Depends(get_user_service),
) -> UserResponse:
    return await service.update_team(user_id, team_update)


@router.delete("/{user_id}", status_code=204)
async def delete_user(
    user_id: UUID,
    _: UserDB = Depends(require_admin),
    service: UserService = Depends(get_user_service),
) -> None:
    await service.delete(user_id)
