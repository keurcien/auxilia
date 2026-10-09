from uuid import UUID

from fastapi import APIRouter, Depends

from app.auth.dependencies import require_admin
from app.notifications.schemas import (
    SlackNotificationSettingsResponse,
    SlackNotificationSettingsUpdate,
)
from app.notifications.service import (
    SlackNotificationSettingsService,
    get_slack_notification_settings_service,
)
from app.users.models import UserDB
from app.workspaces.dependencies import get_active_workspace_id


router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.get("/slack", response_model=SlackNotificationSettingsResponse)
async def get_slack_settings(
    _: UserDB = Depends(require_admin),
    workspace_id: UUID = Depends(get_active_workspace_id),
    service: SlackNotificationSettingsService = Depends(
        get_slack_notification_settings_service
    ),
) -> SlackNotificationSettingsResponse:
    return await service.get_response(workspace_id)


@router.put("/slack", response_model=SlackNotificationSettingsResponse)
async def update_slack_settings(
    data: SlackNotificationSettingsUpdate,
    _: UserDB = Depends(require_admin),
    workspace_id: UUID = Depends(get_active_workspace_id),
    service: SlackNotificationSettingsService = Depends(
        get_slack_notification_settings_service
    ),
) -> SlackNotificationSettingsResponse:
    return await service.update(workspace_id, data)


@router.delete("/slack", response_model=SlackNotificationSettingsResponse)
async def delete_slack_settings(
    _: UserDB = Depends(require_admin),
    workspace_id: UUID = Depends(get_active_workspace_id),
    service: SlackNotificationSettingsService = Depends(
        get_slack_notification_settings_service
    ),
) -> SlackNotificationSettingsResponse:
    return await service.clear(workspace_id)
