from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Query
from pydantic import AwareDatetime
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user, require_admin
from app.database import get_db
from app.exceptions import DomainValidationError
from app.model_providers.whitelist import get_whitelist
from app.runtime.api.costs import CostService
from app.runtime.costs.models import CostBackfillDB
from app.runtime.costs.schemas import (
    BackfillRequest,
    BackfillResponse,
    CostAnalytics,
    StoredThreadCost,
    ThreadCount,
)
from app.runtime.costs.service import (
    analytics,
    cancel,
    count_threads,
    enqueue,
    has_active_run,
    job_response,
    pricing_hash,
    read_summary,
    save_summary,
)
from app.threads.dependencies import authorize_thread_read
from app.threads.models import ThreadDB
from app.users.models import UserDB


router = APIRouter(tags=["thread-costs"])


def get_date_range(
    start_at: AwareDatetime | None = Query(None),
    end_at: AwareDatetime | None = Query(None),
) -> BackfillRequest:
    if start_at and end_at and start_at >= end_at:
        raise DomainValidationError("start_at must be before end_at")
    return BackfillRequest(start_at=start_at, end_at=end_at)


@router.get("/threads/{thread_id}/cost/summary")
async def stored_cost(
    thread: ThreadDB = Depends(authorize_thread_read),
    db: AsyncSession = Depends(get_db),
) -> StoredThreadCost:
    return await read_summary(db, thread)


@router.post("/threads/{thread_id}/cost/refresh")
async def refresh_cost(
    thread: ThreadDB = Depends(authorize_thread_read),
    db: AsyncSession = Depends(get_db),
) -> StoredThreadCost:
    if await has_active_run(db, thread.id):
        raise DomainValidationError("Wait for the thread's active run to finish")
    watermark = thread.updated_at
    catalog = {model.model_id: model for model in await get_whitelist()}
    cost = await CostService(db).conversation(
        thread.id, thread.model_id, catalog=catalog
    )
    await db.refresh(thread)
    if thread.updated_at != watermark or await has_active_run(db, thread.id):
        raise DomainValidationError(
            "Thread changed during calculation; retry after its run finishes"
        )
    await save_summary(db, thread, cost, pricing_hash(catalog))
    return await read_summary(db, thread)


@router.get("/thread-costs/analytics")
async def personal_cost_analytics(
    dates: BackfillRequest = Depends(get_date_range),
    user: UserDB = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CostAnalytics:
    """Lifetime costs for the user's threads created in [start_at, end_at)."""
    return await analytics(db, user.id, dates)


@router.get("/thread-costs/backfill/count")
async def backfill_count(
    dates: BackfillRequest = Depends(get_date_range),
    _: UserDB = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> ThreadCount:
    """How many threads a backfill over [start_at, end_at) would recalculate."""
    return await count_threads(db, dates, datetime.now(UTC))


@router.post("/thread-costs/backfill", status_code=202)
async def start_backfill(
    request: BackfillRequest,
    _: UserDB = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> BackfillResponse:
    """Queue replacement summaries for threads created in [start_at, end_at)."""
    return await enqueue(db, request)


@router.get("/thread-costs/backfill")
async def backfill_status(
    _: UserDB = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> BackfillResponse:
    job = await db.get(CostBackfillDB, 1)
    assert job is not None  # singleton seeded by migration
    return job_response(job)


@router.delete("/thread-costs/backfill")
async def cancel_backfill(
    _: UserDB = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> BackfillResponse:
    return await cancel(db)
