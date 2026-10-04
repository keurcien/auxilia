from uuid import UUID

from fastapi import APIRouter, Depends

from app.auth.dependencies import require_admin
from app.observability.schemas import (
    WorkspaceObservabilityResponse,
    WorkspaceObservabilityUpdate,
)
from app.observability.service import (
    WorkspaceObservabilityService,
    get_workspace_observability_service,
)
from app.users.models import UserDB
from app.workspaces.dependencies import get_active_workspace_id


router = APIRouter(prefix="/observability", tags=["observability"])


@router.get("/", response_model=WorkspaceObservabilityResponse)
async def get_observability_settings(
    _: UserDB = Depends(require_admin),
    workspace_id: UUID = Depends(get_active_workspace_id),
    service: WorkspaceObservabilityService = Depends(
        get_workspace_observability_service
    ),
) -> WorkspaceObservabilityResponse:
    return await service.get_response(workspace_id)


@router.put("/", response_model=WorkspaceObservabilityResponse)
async def update_observability_settings(
    data: WorkspaceObservabilityUpdate,
    _: UserDB = Depends(require_admin),
    workspace_id: UUID = Depends(get_active_workspace_id),
    service: WorkspaceObservabilityService = Depends(
        get_workspace_observability_service
    ),
) -> WorkspaceObservabilityResponse:
    return await service.update(workspace_id, data)


@router.delete("/", response_model=WorkspaceObservabilityResponse)
async def delete_observability_settings(
    _: UserDB = Depends(require_admin),
    workspace_id: UUID = Depends(get_active_workspace_id),
    service: WorkspaceObservabilityService = Depends(
        get_workspace_observability_service
    ),
) -> WorkspaceObservabilityResponse:
    return await service.clear(workspace_id)
