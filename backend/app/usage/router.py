from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.auth.dependencies import get_current_user, require_admin
from app.usage.repository import Granularity, UsageDimension
from app.usage.schemas import (
    UsageFilterOptionsResponse,
    UsageReportResponse,
    UsageScope,
    UsageSettingsResponse,
    UsageSettingsUpdate,
    UsageSummariesResponse,
    UsageSummaryResponse,
)
from app.usage.service import UsageService, get_usage_service
from app.users.models import UserDB
from app.workspaces.dependencies import get_active_workspace_id


router = APIRouter(prefix="/usage", tags=["usage"])


@router.get("/report")
async def get_usage_report(
    start: date | None = None,
    end: date | None = None,
    granularity: Granularity = Granularity.day,
    tz: str = "UTC",
    scope: UsageScope | None = None,
    agent_id: UUID | None = None,
    project_id: UUID | None = None,
    trigger_id: UUID | None = None,
    user_id: UUID | None = None,
    channel: str | None = None,
    model_id: str | None = Query(default=None, max_length=255),
    vendor: str | None = Query(default=None, max_length=100),
    user: UserDB = Depends(get_current_user),
    workspace_id: UUID = Depends(get_active_workspace_id),
    service: UsageService = Depends(get_usage_service),
) -> UsageReportResponse:
    """Totals, a time series and breakdowns over a date range (inclusive, in `tz`)."""
    resolved, usage_filter = service.resolve_scope(
        user,
        workspace_id,
        scope,
        agent_id=agent_id,
        project_id=project_id,
        trigger_id=trigger_id,
        user_id=user_id,
        channel=channel,
        model_id=model_id,
    )
    usage_filter = await service.restrict_to_vendor(usage_filter, vendor)
    return await service.report(
        resolved,
        usage_filter,
        workspace_id,
        start=start,
        end=end,
        granularity=granularity,
        tz=tz,
    )


@router.get("/filter-options")
async def get_usage_filter_options(
    q: str = Query(default="", max_length=100),
    scope: UsageScope | None = None,
    limit: int = Query(default=5, ge=1, le=20),
    user: UserDB = Depends(get_current_user),
    workspace_id: UUID = Depends(get_active_workspace_id),
    service: UsageService = Depends(get_usage_service),
) -> UsageFilterOptionsResponse:
    """Projects, vendors, models, users, agents and triggers with usage in the
    scope whose name matches `q`, at most `limit` of each, by all-time spend."""
    resolved, usage_filter = service.resolve_scope(user, workspace_id, scope)
    return await service.filter_options(resolved, usage_filter, workspace_id, q, limit)


@router.get("/summary")
async def get_usage_summary(
    tz: str = "UTC",
    scope: UsageScope | None = None,
    agent_id: UUID | None = None,
    project_id: UUID | None = None,
    trigger_id: UUID | None = None,
    user_id: UUID | None = None,
    user: UserDB = Depends(get_current_user),
    workspace_id: UUID = Depends(get_active_workspace_id),
    service: UsageService = Depends(get_usage_service),
) -> UsageSummaryResponse:
    """This month, last month, this year and all time for one scope."""
    resolved, usage_filter = service.resolve_scope(
        user,
        workspace_id,
        scope,
        agent_id=agent_id,
        project_id=project_id,
        trigger_id=trigger_id,
        user_id=user_id,
    )
    return await service.summary(resolved, usage_filter, workspace_id, tz)


@router.get("/summaries")
async def get_usage_summaries(
    dimension: UsageDimension,
    tz: str = "UTC",
    scope: UsageScope | None = None,
    ids: list[UUID] | None = Query(default=None, max_length=500),
    user: UserDB = Depends(get_current_user),
    workspace_id: UUID = Depends(get_active_workspace_id),
    service: UsageService = Depends(get_usage_service),
) -> UsageSummariesResponse:
    """`/summary` for every agent, project, trigger or user at once, keyed by id."""
    resolved, usage_filter = service.resolve_scope(user, workspace_id, scope)
    return await service.summaries(
        resolved, usage_filter, workspace_id, dimension, tz, ids
    )


@router.get("/settings")
async def get_usage_settings(
    _: UserDB = Depends(get_current_user),
    workspace_id: UUID = Depends(get_active_workspace_id),
    service: UsageService = Depends(get_usage_service),
) -> UsageSettingsResponse:
    return await service.get_settings(workspace_id)


@router.put("/settings")
async def update_usage_settings(
    data: UsageSettingsUpdate,
    _: UserDB = Depends(require_admin),
    workspace_id: UUID = Depends(get_active_workspace_id),
    service: UsageService = Depends(get_usage_service),
) -> UsageSettingsResponse:
    return await service.update_settings(workspace_id, data)
