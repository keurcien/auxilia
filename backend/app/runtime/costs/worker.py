"""Slow, single-connection backfill, restartable between threads.

The session advisory lock prevents concurrent workers across instances, while
allowing short commits. All checkpoint reads, summaries and progress updates
use the same SQLAlchemy session bound to the one checked-out connection.
"""

import asyncio
import logging
import math
from datetime import UTC, datetime
from decimal import Decimal

from pydantic import field_validator
from pydantic_settings import BaseSettings
from sqlalchemy import and_, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col

from app.database import engine
from app.model_providers.whitelist import SupportedModel
from app.runtime.api.costs import CostService
from app.runtime.costs.models import CostBackfillDB, ThreadCostDB
from app.runtime.costs.service import has_active_run, pricing_hash, save_summary
from app.settings import settings_config
from app.threads.models import ThreadDB


logger = logging.getLogger(__name__)
_LOCK_ID = 783614229


class CostSettings(BaseSettings):
    thread_pause_seconds: float = 0.25
    chunk_pause_seconds: float = 0.05
    poll_seconds: float = 5
    model_config = settings_config(env_prefix="cost_backfill_")

    @field_validator("thread_pause_seconds", "chunk_pause_seconds", "poll_seconds")
    @classmethod
    def bounded_pause(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("pause must be finite")
        return max(value, 0.01)


cost_settings = CostSettings()


class CostBackfillWorker:
    async def pause(self) -> None:
        await asyncio.sleep(cost_settings.thread_pause_seconds)

    async def run(self) -> None:
        while True:
            try:
                await self.tick()
            except Exception:
                logger.exception("Cost backfill worker failed; will retry")
            await asyncio.sleep(cost_settings.poll_seconds)

    async def tick(self) -> None:
        # Exactly one checkout. Never get_checkpointer or AsyncSessionLocal here.
        async with engine.connect() as connection:
            postgres = connection.dialect.name == "postgresql"
            if postgres:
                locked = await connection.scalar(
                    text("SELECT pg_try_advisory_lock(:key)"), {"key": _LOCK_ID}
                )
                await connection.commit()
                if not locked:
                    return
            try:
                async with AsyncSession(bind=connection, expire_on_commit=False) as db:
                    await self.process(db)
            finally:
                if postgres:
                    await connection.execute(
                        text("SELECT pg_advisory_unlock(:key)"), {"key": _LOCK_ID}
                    )
                    await connection.commit()

    async def process(self, db: AsyncSession) -> None:
        job = await db.get(CostBackfillDB, 1)
        if job is None or job.status not in {"pending", "running"}:
            await db.rollback()
            return
        job_id = job.job_id
        catalog = {
            model.model_id: model
            for model in (SupportedModel.model_validate(value) for value in job.catalog)
        }
        fingerprint = pricing_hash(catalog)
        job.status = "running"
        await db.commit()
        while True:
            await db.refresh(job)
            if job.job_id != job_id or job.status != "running":
                await db.rollback()
                return
            stmt = (
                select(ThreadDB)
                .where(col(ThreadDB.created_at) <= job.requested_at)
                .order_by(col(ThreadDB.created_at), ThreadDB.id)
                .limit(1)
            )
            if job.start_at:
                stmt = stmt.where(col(ThreadDB.created_at) >= job.start_at)
            if job.end_at:
                stmt = stmt.where(col(ThreadDB.created_at) < job.end_at)
            if job.cursor and job.cursor_created_at:
                stmt = stmt.where(
                    or_(
                        col(ThreadDB.created_at) > job.cursor_created_at,
                        and_(
                            col(ThreadDB.created_at) == job.cursor_created_at,
                            col(ThreadDB.id) > job.cursor,
                        ),
                    )
                )
            thread = (await db.execute(stmt)).scalar_one_or_none()
            if thread is None:
                # Lock the singleton only briefly; never across a history scan.
                await db.refresh(job, with_for_update=True)
                if job.job_id == job_id and job.status == "running":
                    job.status = "complete"
                    job.finished_at = datetime.now(UTC)
                await db.commit()
                return
            thread_id = thread.id
            watermark = thread.updated_at
            created_at = thread.created_at
            failed = skipped = incomplete = False
            error = None
            previous_cost = new_cost = Decimal(0)
            unpriced: set[str] = set()
            try:
                if await has_active_run(db, thread_id):
                    skipped = True
                else:
                    cost = await CostService(db).conversation(
                        thread_id,
                        thread.model_id,
                        catalog=catalog,
                        pause_seconds=cost_settings.chunk_pause_seconds,
                    )
                    await db.refresh(thread)
                    if thread.updated_at != watermark or await has_active_run(
                        db, thread_id
                    ):
                        skipped = True
                    else:
                        # Lock progress only AFTER calculation. A cancellation
                        # or newer job must not receive this one's result.
                        await db.refresh(job, with_for_update=True)
                        if job.job_id != job_id or job.status != "running":
                            await db.rollback()
                            return
                        previous_cost = await db.scalar(
                            select(col(ThreadCostDB.known_cost)).where(
                                col(ThreadCostDB.thread_id) == thread_id
                            )
                        ) or Decimal(0)
                        await save_summary(db, thread, cost, fingerprint)
                        incomplete = not cost.complete
                        new_cost = cost.known_cost
                        unpriced = {
                            message.model_id or "unknown"
                            for message in cost.messages
                            if message.reason == "missing_pricing"
                        }
            except Exception as exc:
                await db.rollback()
                failed = True
                error = str(exc)[:500]
                logger.exception("Cost backfill failed for thread %s", thread_id)
            await db.refresh(job, with_for_update=True)
            if job.job_id != job_id or job.status != "running":
                await db.rollback()
                return
            job.cursor = thread_id
            job.cursor_created_at = created_at
            job.processed += int(not failed and not skipped)
            job.skipped += int(skipped)
            job.failed += int(failed)
            job.incomplete += int(incomplete)
            job.previous_cost += previous_cost
            job.new_cost += new_cost
            if unpriced - set(job.unpriced_models):
                # Reassign: a JSON column does not track in-place mutation.
                job.unpriced_models = sorted({*job.unpriced_models, *unpriced})
            if error:
                job.last_error = error
            # Summary and cursor commit together: restart cannot skip a result.
            await db.commit()
            await self.pause()
