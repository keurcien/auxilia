from uuid import UUID

from fastapi import APIRouter, Depends, File, Header, UploadFile
from fastapi.responses import Response

from app.auth.dependencies import get_current_user, require_admin
from app.pagination import Page, PageParams
from app.users.models import UserDB, WorkspaceRole
from app.users.schemas import (
    BackupCodesResponse,
    CurrentUserResponse,
    PasswordChange,
    ProfilePatch,
    TwoFactorConfirmRequest,
    TwoFactorDisableRequest,
    TwoFactorRegenerateRequest,
    TwoFactorSetupRequest,
    TwoFactorSetupResponse,
    TwoFactorStatus,
    UserCreate,
    UserPatch,
    UserResponse,
    UserRoleCounts,
    UserRolePatch,
    UserTeamPatch,
)
from app.users.service import UserService, get_user_service
from app.utils.images import image_response, process_uploaded_image
from app.workspaces.dependencies import get_active_workspace_id


router = APIRouter(prefix="/users", tags=["users"])


@router.post("/", response_model=UserResponse, status_code=201)
async def create_user(
    user: UserCreate,
    _: UserDB = Depends(require_admin),
    workspace_id: UUID = Depends(get_active_workspace_id),
    service: UserService = Depends(get_user_service),
) -> UserResponse:
    return await service.create(user, workspace_id)


@router.get("/", response_model=Page[UserResponse])
async def get_users(
    role: WorkspaceRole | None = None,
    search: str | None = None,
    page: PageParams = Depends(),
    _: UserDB = Depends(get_current_user),
    workspace_id: UUID = Depends(get_active_workspace_id),
    service: UserService = Depends(get_user_service),
) -> Page[UserResponse]:
    return await service.list(workspace_id, page, role=role, search=search)


# Declared before /{user_id} so "role-counts" is not captured as a user id.
@router.get("/role-counts", response_model=UserRoleCounts)
async def count_users_by_role(
    _: UserDB = Depends(get_current_user),
    workspace_id: UUID = Depends(get_active_workspace_id),
    service: UserService = Depends(get_user_service),
) -> UserRoleCounts:
    return await service.count_by_role(workspace_id)


@router.patch("/me", response_model=CurrentUserResponse)
async def update_profile(
    data: ProfilePatch,
    current_user: UserDB = Depends(get_current_user),
    service: UserService = Depends(get_user_service),
) -> CurrentUserResponse:
    user = await service.update_profile(current_user, data)
    return CurrentUserResponse.model_validate(
        user, update={"workspace_id": current_user.active_workspace_id}
    )


@router.put("/me/password", status_code=204)
async def change_password(
    data: PasswordChange,
    current_user: UserDB = Depends(get_current_user),
    service: UserService = Depends(get_user_service),
) -> None:
    await service.change_password(current_user, data)


@router.get("/me/two-factor", response_model=TwoFactorStatus)
async def get_two_factor_status(
    current_user: UserDB = Depends(get_current_user),
    service: UserService = Depends(get_user_service),
) -> TwoFactorStatus:
    return await service.get_two_factor_status(current_user)


@router.post("/me/two-factor/setup", response_model=TwoFactorSetupResponse)
async def begin_two_factor_setup(
    data: TwoFactorSetupRequest,
    current_user: UserDB = Depends(get_current_user),
    service: UserService = Depends(get_user_service),
) -> TwoFactorSetupResponse:
    return await service.begin_two_factor_setup(current_user, data)


@router.post("/me/two-factor/confirm", response_model=BackupCodesResponse)
async def confirm_two_factor_setup(
    data: TwoFactorConfirmRequest,
    current_user: UserDB = Depends(get_current_user),
    service: UserService = Depends(get_user_service),
) -> BackupCodesResponse:
    return await service.confirm_two_factor_setup(current_user, data)


@router.post("/me/two-factor/disable", status_code=204)
async def disable_two_factor(
    data: TwoFactorDisableRequest,
    current_user: UserDB = Depends(get_current_user),
    service: UserService = Depends(get_user_service),
) -> None:
    await service.disable_two_factor(current_user, data)


@router.post(
    "/me/two-factor/backup-codes",
    response_model=BackupCodesResponse,
)
async def regenerate_backup_codes(
    data: TwoFactorRegenerateRequest,
    current_user: UserDB = Depends(get_current_user),
    service: UserService = Depends(get_user_service),
) -> BackupCodesResponse:
    return await service.regenerate_backup_codes(current_user, data)


@router.put("/me/image")
async def set_profile_image(
    file: UploadFile = File(...),
    current_user: UserDB = Depends(get_current_user),
    service: UserService = Depends(get_user_service),
) -> dict[str, UUID]:
    image = await process_uploaded_image(file)
    return {"image_revision": await service.set_image(current_user.id, image)}


@router.delete("/me/image", status_code=204)
async def delete_profile_image(
    current_user: UserDB = Depends(get_current_user),
    service: UserService = Depends(get_user_service),
) -> None:
    await service.delete_image(current_user.id)


@router.get("/{user_id}/image", response_class=Response)
async def get_profile_image(
    user_id: UUID,
    if_none_match: str | None = Header(default=None),
    _: UserDB = Depends(get_current_user),
    workspace_id: UUID = Depends(get_active_workspace_id),
    service: UserService = Depends(get_user_service),
) -> Response:
    image = await service.get_image(user_id, workspace_id)
    return image_response(
        data=image.data,
        media_type=image.media_type,
        digest=image.sha256,
        if_none_match=if_none_match,
    )


@router.get("/{user_id}", response_model=UserResponse)
async def get_user(
    user_id: UUID,
    _: UserDB = Depends(get_current_user),
    workspace_id: UUID = Depends(get_active_workspace_id),
    service: UserService = Depends(get_user_service),
) -> UserResponse:
    return await service.get(user_id, workspace_id)


@router.get("/email/{email}", response_model=UserResponse)
async def get_user_by_email(
    email: str,
    _: UserDB = Depends(get_current_user),
    workspace_id: UUID = Depends(get_active_workspace_id),
    service: UserService = Depends(get_user_service),
) -> UserResponse:
    return await service.get_by_email(email, workspace_id)


@router.patch("/{user_id}", response_model=UserResponse)
async def update_user(
    user_id: UUID,
    user_update: UserPatch,
    _: UserDB = Depends(require_admin),
    workspace_id: UUID = Depends(get_active_workspace_id),
    service: UserService = Depends(get_user_service),
) -> UserResponse:
    return await service.update(user_id, workspace_id, user_update)


@router.patch("/{user_id}/role", response_model=UserResponse)
async def update_user_role(
    user_id: UUID,
    role_update: UserRolePatch,
    _: UserDB = Depends(require_admin),
    workspace_id: UUID = Depends(get_active_workspace_id),
    service: UserService = Depends(get_user_service),
) -> UserResponse:
    return await service.update_role(user_id, workspace_id, role_update)


@router.patch("/{user_id}/team", response_model=UserResponse)
async def update_user_team(
    user_id: UUID,
    team_update: UserTeamPatch,
    _: UserDB = Depends(require_admin),
    workspace_id: UUID = Depends(get_active_workspace_id),
    service: UserService = Depends(get_user_service),
) -> UserResponse:
    return await service.update_team(user_id, workspace_id, team_update)


@router.delete("/{user_id}", status_code=204)
async def delete_user(
    user_id: UUID,
    _: UserDB = Depends(require_admin),
    workspace_id: UUID = Depends(get_active_workspace_id),
    service: UserService = Depends(get_user_service),
) -> None:
    await service.delete(user_id, workspace_id)
