from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.auth.dependencies import get_current_user, require_editor
from app.triggers.schedule import compute_next_run_ats, ensure_valid_schedule
from app.triggers.schemas import (
    SchedulePreviewResponse,
    TriggerCreate,
    TriggerPatch,
    TriggerResponse,
    TriggerRunResponse,
    TriggerThreadResponse,
)
from app.triggers.service import TriggerService, get_trigger_service
from app.users.models import UserDB


router = APIRouter(prefix="/triggers", tags=["triggers"])


@router.get("/", response_model=list[TriggerResponse])
async def list_triggers(
    user: UserDB = Depends(get_current_user),
    service: TriggerService = Depends(get_trigger_service),
) -> list[TriggerResponse]:
    return await service.list(user)


@router.post("/", response_model=TriggerResponse, status_code=201)
async def create_trigger(
    data: TriggerCreate,
    user: UserDB = Depends(require_editor),
    service: TriggerService = Depends(get_trigger_service),
) -> TriggerResponse:
    return await service.create(data, owner=user)


@router.get("/schedule/preview", response_model=SchedulePreviewResponse)
async def preview_schedule(
    cron_expression: str = Query(...),
    timezone: str = Query("UTC"),
    count: int = Query(5, ge=1, le=20),
    _: UserDB = Depends(get_current_user),
) -> SchedulePreviewResponse:
    """Compute the next occurrences of a schedule without persisting anything —
    backs the schedule designer's "next runs" preview."""
    ensure_valid_schedule(cron_expression, timezone)
    return SchedulePreviewResponse(
        next_run_ats=compute_next_run_ats(
            cron_expression, timezone, after=datetime.now(UTC), count=count
        )
    )


@router.get("/{trigger_id}/threads", response_model=list[TriggerThreadResponse])
async def list_trigger_threads(
    trigger_id: UUID,
    user: UserDB = Depends(get_current_user),
    service: TriggerService = Depends(get_trigger_service),
) -> list[TriggerThreadResponse]:
    """Run history: the threads this trigger's firings created (last 30 days)."""
    return await service.list_threads(trigger_id, user)


@router.get("/{trigger_id}", response_model=TriggerResponse)
async def get_trigger(
    trigger_id: UUID,
    user: UserDB = Depends(get_current_user),
    service: TriggerService = Depends(get_trigger_service),
) -> TriggerResponse:
    return await service.get(trigger_id, user)


@router.patch("/{trigger_id}", response_model=TriggerResponse)
async def update_trigger(
    trigger_id: UUID,
    data: TriggerPatch,
    user: UserDB = Depends(get_current_user),
    service: TriggerService = Depends(get_trigger_service),
) -> TriggerResponse:
    return await service.update(trigger_id, data, user)


@router.post("/{trigger_id}/run", response_model=TriggerRunResponse, status_code=201)
async def run_trigger(
    trigger_id: UUID,
    user: UserDB = Depends(get_current_user),
    service: TriggerService = Depends(get_trigger_service),
) -> TriggerRunResponse:
    """Fire one occurrence now (test run) — paused triggers included; the
    schedule is untouched. Follow the run via the returned thread's runs API."""
    return await service.run_now(trigger_id, user)


@router.delete("/{trigger_id}", status_code=204)
async def delete_trigger(
    trigger_id: UUID,
    user: UserDB = Depends(get_current_user),
    service: TriggerService = Depends(get_trigger_service),
) -> None:
    await service.delete(trigger_id, user)
