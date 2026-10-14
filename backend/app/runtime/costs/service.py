import hashlib
import json
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import func, or_, select
from sqlalchemy.dialects.postgresql import insert as postgres_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col

from app.exceptions import AlreadyExistsError, DomainValidationError, NotFoundError
from app.model_providers.whitelist import SupportedModel, get_whitelist
from app.runtime.api.costs import ConversationCost
from app.runtime.costs.models import CostBackfillDB, ThreadCostDB
from app.runtime.costs.schemas import (
    BackfillRequest,
    BackfillResponse,
    CostAnalytics,
    StoredThreadCost,
)
from app.runtime.runs.models import RunDB
from app.threads.models import ThreadDB


def pricing_hash(catalog: dict[str, SupportedModel]) -> str:
    prices = {
        key: value.pricing.model_dump(mode="json") if value.pricing else None
        for key, value in catalog.items()
    }
    return hashlib.sha256(json.dumps(prices, sort_keys=True).encode()).hexdigest()


async def has_active_run(db: AsyncSession, thread_id: str) -> bool:
    return bool(
        await db.scalar(
            select(col(RunDB.id))
            .where(
                col(RunDB.thread_id) == thread_id,
                col(RunDB.status).in_(["pending", "running"]),
            )
            .limit(1)
        )
    )


async def save_summary(
    db: AsyncSession, thread: ThreadDB, cost: ConversationCost, fingerprint: str
) -> ThreadCostDB:
    values = {
        "thread_id": thread.id,
        "summary": cost.model_dump(mode="json", exclude={"messages"}),
        "total_cost": cost.total_cost,
        "known_cost": cost.known_cost,
        "complete": cost.complete,
        "pricing_hash": fingerprint,
        "calculated_at": datetime.now(UTC),
        "source_updated_at": thread.updated_at,
    }
    insert = (
        postgres_insert if db.get_bind().dialect.name == "postgresql" else sqlite_insert
    )
    stmt = insert(ThreadCostDB).values(**values)
    await db.execute(
        stmt.on_conflict_do_update(index_elements=["thread_id"], set_=values)
    )
    row = await db.get(ThreadCostDB, thread.id, populate_existing=True)
    assert row is not None
    return row


async def read_summary(db: AsyncSession, thread: ThreadDB) -> StoredThreadCost:
    row = await db.get(ThreadCostDB, thread.id)
    if row is None:
        raise NotFoundError("Thread cost has not been calculated")
    catalog = {model.model_id: model for model in await get_whitelist()}
    return StoredThreadCost(
        thread_id=thread.id,
        summary=row.summary,
        calculated_at=row.calculated_at,
        stale=row.pricing_hash != pricing_hash(catalog)
        or row.source_updated_at != thread.updated_at
        or await has_active_run(db, thread.id),
    )


def job_response(job: CostBackfillDB) -> BackfillResponse:
    return BackfillResponse.model_validate(job, from_attributes=True)


async def enqueue(db: AsyncSession, request: BackfillRequest) -> BackfillResponse:
    catalog = await get_whitelist()
    job = (
        await db.execute(
            select(CostBackfillDB).where(col(CostBackfillDB.id) == 1).with_for_update()
        )
    ).scalar_one()
    if job.status in {"pending", "running"}:
        raise AlreadyExistsError("A cost backfill is already active")
    job.job_id = uuid4()
    job.status = "pending"
    job.start_at = request.start_at
    job.end_at = request.end_at
    job.requested_at = datetime.now(UTC)
    job.cursor = None
    job.cursor_created_at = None
    job.processed = job.skipped = job.failed = job.incomplete = 0
    job.last_error = None
    job.catalog = [model.model_dump(mode="json") for model in catalog]
    db.add(job)
    await db.flush()
    return job_response(job)


async def cancel(db: AsyncSession) -> BackfillResponse:
    job = (
        await db.execute(
            select(CostBackfillDB).where(col(CostBackfillDB.id) == 1).with_for_update()
        )
    ).scalar_one()
    if job.status not in {"pending", "running"}:
        raise DomainValidationError("No active cost backfill")
    job.status = "cancelled"
    db.add(job)
    await db.flush()
    return job_response(job)


async def analytics(
    db: AsyncSession, user_id: UUID, dates: BackfillRequest
) -> CostAnalytics:
    catalog = {model.model_id: model for model in await get_whitelist()}
    fingerprint = pricing_hash(catalog)
    active = (
        select(col(RunDB.id))
        .where(
            col(RunDB.thread_id) == col(ThreadDB.id),
            col(RunDB.status).in_(["pending", "running"]),
        )
        .exists()
    )
    stale = or_(
        col(ThreadCostDB.pricing_hash) != fingerprint,
        col(ThreadCostDB.source_updated_at) != col(ThreadDB.updated_at),
        active,
    )
    stmt = (
        select(
            func.count(col(ThreadDB.id)),
            func.count(col(ThreadCostDB.thread_id)),
            func.count().filter(col(ThreadCostDB.complete).is_(False)),
            func.count().filter(stale),
            func.sum(ThreadCostDB.known_cost),
        )
        .outerjoin(ThreadCostDB, col(ThreadCostDB.thread_id) == col(ThreadDB.id))
        .where(col(ThreadDB.user_id) == user_id)
    )
    if dates.start_at:
        stmt = stmt.where(col(ThreadDB.created_at) >= dates.start_at)
    if dates.end_at:
        stmt = stmt.where(col(ThreadDB.created_at) < dates.end_at)
    total, calculated, incomplete, stale_count, known = (await db.execute(stmt)).one()
    known = known or Decimal(0)
    return CostAnalytics(
        threads=total,
        calculated_threads=calculated,
        incomplete_threads=incomplete,
        stale_threads=stale_count,
        total_cost=known
        if calculated == total and not incomplete and not stale_count
        else None,
        known_cost=known,
    )
