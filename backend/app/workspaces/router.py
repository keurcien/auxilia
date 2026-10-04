import logging
from typing import Literal, cast
from uuid import UUID

from fastapi import APIRouter, Depends, File, Header, UploadFile
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user
from app.auth.settings import auth_settings
from app.database import get_db
from app.mcp.client.storage import TokenStorageFactory
from app.redis_client import get_redis
from app.threads.service import ThreadService
from app.users.models import UserDB
from app.utils.images import image_response, process_uploaded_image
from app.workspaces.constants import ACTIVE_WORKSPACE_COOKIE
from app.workspaces.models import WorkspaceRole
from app.workspaces.schemas import (
    WorkspaceCreate,
    WorkspaceDelete,
    WorkspaceDeleteResponse,
    WorkspacePatch,
    WorkspaceResponse,
)
from app.workspaces.service import WorkspaceService, get_workspace_service


logger = logging.getLogger(__name__)
router = APIRouter(prefix="/workspaces", tags=["workspaces"])


def set_active_workspace_cookie(response: Response, workspace_id: UUID) -> None:
    response.set_cookie(
        key=ACTIVE_WORKSPACE_COOKIE,
        value=str(workspace_id),
        httponly=True,
        secure=auth_settings.COOKIE_SECURE,
        samesite=cast(
            Literal["lax", "strict", "none"],
            auth_settings.COOKIE_SAMESITE,
        ),
        domain=auth_settings.COOKIE_DOMAIN,
        max_age=auth_settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )


def clear_active_workspace_cookie(response: Response) -> None:
    response.delete_cookie(
        key=ACTIVE_WORKSPACE_COOKIE,
        secure=auth_settings.COOKIE_SECURE,
        samesite=cast(
            Literal["lax", "strict", "none"],
            auth_settings.COOKIE_SAMESITE,
        ),
        domain=auth_settings.COOKIE_DOMAIN,
    )


@router.get("/", response_model=list[WorkspaceResponse])
async def list_workspaces(
    current_user: UserDB = Depends(get_current_user),
    service: WorkspaceService = Depends(get_workspace_service),
) -> list[WorkspaceResponse]:
    return await service.list_for_user(current_user.id)


@router.post("/", response_model=WorkspaceResponse, status_code=201)
async def create_workspace(
    data: WorkspaceCreate,
    response: Response,
    current_user: UserDB = Depends(get_current_user),
    service: WorkspaceService = Depends(get_workspace_service),
) -> WorkspaceResponse:
    workspace = await service.create(data, current_user)
    set_active_workspace_cookie(response, workspace.id)
    return WorkspaceResponse.model_validate(
        workspace,
        update={"role": WorkspaceRole.admin},
    )


@router.patch("/{workspace_id}", response_model=WorkspaceResponse)
async def update_workspace(
    workspace_id: UUID,
    data: WorkspacePatch,
    current_user: UserDB = Depends(get_current_user),
    service: WorkspaceService = Depends(get_workspace_service),
) -> WorkspaceResponse:
    return await service.update(workspace_id, current_user.id, data)


@router.delete("/{workspace_id}", response_model=WorkspaceDeleteResponse)
async def delete_workspace(
    workspace_id: UUID,
    data: WorkspaceDelete,
    response: Response,
    current_user: UserDB = Depends(get_current_user),
    service: WorkspaceService = Depends(get_workspace_service),
    db: AsyncSession = Depends(get_db),
) -> WorkspaceDeleteResponse:
    # Gate before reading cross-module rows belonging to the target workspace.
    await service.require_admin(workspace_id, current_user.id)
    thread_service = ThreadService(db, workspace_id)
    thread_ids = await thread_service.list_ids()
    active_workspace_id = await service.delete_workspace(
        workspace_id,
        current_user.id,
        current_user.active_workspace_id,
        data,
    )

    # The checkpoint store and Redis are separate, auto-committed systems.
    # Commit the relational cascade first so a failed DB delete cannot leave
    # visible threads without their history.
    await db.commit()
    if active_workspace_id is None:
        clear_active_workspace_cookie(response)
    else:
        set_active_workspace_cookie(response, active_workspace_id)

    try:
        await thread_service.purge_checkpoints(thread_ids)
    except Exception:
        logger.exception(
            "Workspace %s was deleted but checkpoints for %d thread(s) could "
            "not be purged; they are now orphaned",
            workspace_id,
            len(thread_ids),
        )
    try:
        await TokenStorageFactory().clear_workspace_data(str(workspace_id))
        redis = get_redis()
        async for key in redis.scan_iter(match=f"workspace:{workspace_id}:run:*"):
            await redis.delete(key)
    except Exception:
        logger.exception(
            "Workspace %s was deleted but its ephemeral Redis data could not be purged",
            workspace_id,
        )

    return WorkspaceDeleteResponse(active_workspace_id=active_workspace_id)


@router.get("/{workspace_id}/image", response_class=Response)
async def get_workspace_image(
    workspace_id: UUID,
    if_none_match: str | None = Header(default=None),
    current_user: UserDB = Depends(get_current_user),
    service: WorkspaceService = Depends(get_workspace_service),
) -> Response:
    image = await service.get_image(workspace_id, current_user.id)
    return image_response(
        data=image.data,
        media_type=image.media_type,
        digest=image.sha256,
        if_none_match=if_none_match,
    )


@router.put("/{workspace_id}/image")
async def set_workspace_image(
    workspace_id: UUID,
    file: UploadFile = File(...),
    current_user: UserDB = Depends(get_current_user),
    service: WorkspaceService = Depends(get_workspace_service),
) -> dict[str, UUID]:
    image = await process_uploaded_image(file)
    revision = await service.set_image(workspace_id, current_user.id, image)
    return {"image_revision": revision}


@router.delete("/{workspace_id}/image", status_code=204)
async def delete_workspace_image(
    workspace_id: UUID,
    current_user: UserDB = Depends(get_current_user),
    service: WorkspaceService = Depends(get_workspace_service),
) -> None:
    await service.delete_image(workspace_id, current_user.id)


@router.post("/{workspace_id}/select", status_code=204)
async def select_workspace(
    workspace_id: UUID,
    response: Response,
    current_user: UserDB = Depends(get_current_user),
    service: WorkspaceService = Depends(get_workspace_service),
) -> None:
    await service.require_membership(workspace_id, current_user.id)
    set_active_workspace_cookie(response, workspace_id)
