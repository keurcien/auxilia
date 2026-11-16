import logging
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user
from app.database import get_db
from app.projects.schemas import (
    ProjectConfigResponse,
    ProjectConfigUpdate,
    ProjectContextFileCreate,
    ProjectContextFileResponse,
    ProjectContextFileSummary,
    ProjectContextFileUpdate,
    ProjectCreate,
    ProjectDetailResponse,
    ProjectFolderCreate,
    ProjectFolderPatch,
    ProjectFolderResponse,
    ProjectFolderSearchResponse,
    ProjectPatch,
    ProjectResponse,
    ProjectTreeResponse,
)
from app.projects.service import ProjectService, get_project_service
from app.threads.service import ThreadService, get_thread_service
from app.users.models import UserDB


logger = logging.getLogger(__name__)

router = APIRouter(prefix="/projects", tags=["projects"])


@router.get("/tree", response_model=list[ProjectTreeResponse])
async def get_project_tree(
    user: UserDB = Depends(get_current_user),
    service: ProjectService = Depends(get_project_service),
) -> list[ProjectTreeResponse]:
    return await service.tree(user)


@router.get("/", response_model=list[ProjectResponse])
async def list_projects(
    query: str | None = Query(default=None, max_length=255),
    limit: int | None = Query(default=None, ge=1, le=50),
    user: UserDB = Depends(get_current_user),
    service: ProjectService = Depends(get_project_service),
) -> list[ProjectResponse]:
    return await service.list(user, query=query, limit=limit)


@router.post("/", response_model=ProjectResponse, status_code=201)
async def create_project(
    data: ProjectCreate,
    user: UserDB = Depends(get_current_user),
    service: ProjectService = Depends(get_project_service),
) -> ProjectResponse:
    return await service.create(data, user)


@router.patch("/folders/{folder_id}", response_model=ProjectFolderResponse)
async def update_project_folder(
    folder_id: UUID,
    data: ProjectFolderPatch,
    user: UserDB = Depends(get_current_user),
    service: ProjectService = Depends(get_project_service),
) -> ProjectFolderResponse:
    return await service.update_folder(folder_id, data, user)


@router.delete("/folders/{folder_id}", status_code=204)
async def delete_project_folder(
    folder_id: UUID,
    user: UserDB = Depends(get_current_user),
    service: ProjectService = Depends(get_project_service),
) -> None:
    await service.delete_folder(folder_id, user)


@router.post("/folders/{folder_id}/empty", status_code=204)
async def empty_project_folder(
    folder_id: UUID,
    user: UserDB = Depends(get_current_user),
    service: ProjectService = Depends(get_project_service),
    thread_service: ThreadService = Depends(get_thread_service),
    db: AsyncSession = Depends(get_db),  # dependency-cached: the services' session
) -> None:
    thread_ids = await service.empty_folder(folder_id, user)
    # Commit the row deletes BEFORE purging checkpoints, as `DELETE /threads/{id}`
    # does: checkpoints live on a separate auto-committed connection, so purging
    # first and then failing to commit would leave rows whose history is gone.
    await db.commit()
    # Past the commit the content is gone; a purge failure only orphans
    # checkpoints, which are invisible and reclaimable.
    try:
        await thread_service.purge_checkpoints(thread_ids)
    except Exception:
        logger.exception(
            "Folder %s was emptied but the checkpoints of its %d thread(s) could "
            "not be purged; they are now orphaned",
            folder_id,
            len(thread_ids),
        )


@router.get(
    "/context-files/{file_id}",
    response_model=ProjectContextFileResponse,
)
async def get_project_context_file(
    file_id: UUID,
    user: UserDB = Depends(get_current_user),
    service: ProjectService = Depends(get_project_service),
) -> ProjectContextFileResponse:
    return await service.get_context_file(file_id, user)


@router.put(
    "/context-files/{file_id}",
    response_model=ProjectContextFileResponse,
)
async def update_project_context_file(
    file_id: UUID,
    data: ProjectContextFileUpdate,
    user: UserDB = Depends(get_current_user),
    service: ProjectService = Depends(get_project_service),
) -> ProjectContextFileResponse:
    return await service.update_context_file(file_id, data, user)


@router.delete("/context-files/{file_id}", status_code=204)
async def delete_project_context_file(
    file_id: UUID,
    revision: int = Query(ge=1),
    user: UserDB = Depends(get_current_user),
    service: ProjectService = Depends(get_project_service),
) -> None:
    await service.delete_context_file(file_id, revision, user)


@router.get("/{project_id}", response_model=ProjectResponse)
async def get_project(
    project_id: UUID,
    user: UserDB = Depends(get_current_user),
    service: ProjectService = Depends(get_project_service),
) -> ProjectResponse:
    return await service.get(project_id, user)


@router.get("/{project_id}/detail", response_model=ProjectDetailResponse)
async def get_project_detail(
    project_id: UUID,
    user: UserDB = Depends(get_current_user),
    service: ProjectService = Depends(get_project_service),
) -> ProjectDetailResponse:
    return await service.detail(project_id, user)


@router.get("/{project_id}/tree", response_model=ProjectTreeResponse)
async def get_single_project_tree(
    project_id: UUID,
    user: UserDB = Depends(get_current_user),
    service: ProjectService = Depends(get_project_service),
) -> ProjectTreeResponse:
    return await service.get_tree(project_id, user)


@router.put("/{project_id}/config", response_model=ProjectConfigResponse)
@router.patch("/{project_id}/config", response_model=ProjectConfigResponse)
async def update_project_config(
    project_id: UUID,
    data: ProjectConfigUpdate,
    user: UserDB = Depends(get_current_user),
    service: ProjectService = Depends(get_project_service),
) -> ProjectConfigResponse:
    return await service.update_config(project_id, data, user)


@router.get(
    "/{project_id}/context-files",
    response_model=list[ProjectContextFileSummary],
)
async def list_project_context_files(
    project_id: UUID,
    user: UserDB = Depends(get_current_user),
    service: ProjectService = Depends(get_project_service),
) -> list[ProjectContextFileSummary]:
    return await service.list_context_files(project_id, user)


@router.post(
    "/{project_id}/context-files",
    response_model=ProjectContextFileResponse,
    status_code=201,
)
async def create_project_context_file(
    project_id: UUID,
    data: ProjectContextFileCreate,
    user: UserDB = Depends(get_current_user),
    service: ProjectService = Depends(get_project_service),
) -> ProjectContextFileResponse:
    return await service.create_context_file(project_id, data, user)


@router.patch("/{project_id}", response_model=ProjectResponse)
async def update_project(
    project_id: UUID,
    data: ProjectPatch,
    user: UserDB = Depends(get_current_user),
    service: ProjectService = Depends(get_project_service),
) -> ProjectResponse:
    return await service.update(project_id, data, user)


@router.delete("/{project_id}", status_code=204)
async def delete_project(
    project_id: UUID,
    user: UserDB = Depends(get_current_user),
    service: ProjectService = Depends(get_project_service),
) -> None:
    await service.delete(project_id, user)


@router.post(
    "/{project_id}/folders",
    response_model=ProjectFolderResponse,
    status_code=201,
)
async def create_project_folder(
    project_id: UUID,
    data: ProjectFolderCreate,
    user: UserDB = Depends(get_current_user),
    service: ProjectService = Depends(get_project_service),
) -> ProjectFolderResponse:
    return await service.create_folder(project_id, data, user)


@router.get(
    "/{project_id}/folders",
    response_model=list[ProjectFolderSearchResponse],
)
async def search_project_folders(
    project_id: UUID,
    query: str = Query(default="", max_length=255),
    limit: int = Query(default=20, ge=1, le=50),
    user: UserDB = Depends(get_current_user),
    service: ProjectService = Depends(get_project_service),
) -> list[ProjectFolderSearchResponse]:
    return await service.search_folders(
        project_id,
        user,
        query=query,
        limit=limit,
    )
