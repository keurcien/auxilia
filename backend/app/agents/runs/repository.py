"""RunRepository — SQL for run records.

The dispatch queue and the per-thread mutex live here too: claiming is an
atomic `UPDATE ... WHERE id IN (SELECT ... FOR UPDATE SKIP LOCKED)`, and "one
running run per thread" is enforced by a partial unique index (see the
`add_runs_table` migration). Never raises domain exceptions — returns
`None` / `[]`.
"""

from datetime import datetime
from uuid import UUID

from sqlalchemy import delete, exists, func, or_, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased
from sqlmodel import select

from app.agents.runs.models import RunDB
from app.agents.runs.state import (
    TERMINAL_STATUSES,
    RunStatus,
    legal_source_statuses,
)
from app.repository import BaseRepository


ACTIVE_STATUSES: tuple[RunStatus, ...] = (RunStatus.pending, RunStatus.running)


class RunRepository(BaseRepository[RunDB]):
    def __init__(self, db: AsyncSession):
        super().__init__(RunDB, db)

    async def create(self, run: RunDB) -> RunDB:
        """Persist a new run row (server-side timestamps populated on refresh)."""
        self.db.add(run)
        await self.db.flush()
        await self.db.refresh(run)
        return run

    async def get(self, run_id: str) -> RunDB | None:
        stmt = select(RunDB).where(RunDB.id == run_id)
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def list_for_thread(self, thread_id: str) -> list[RunDB]:
        """Runs for a thread, newest first."""
        stmt = (
            select(RunDB)
            .where(RunDB.thread_id == thread_id)
            .order_by(RunDB.created_at.desc())
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def lock_thread_runs(self, thread_id: str) -> None:
        """Serialize run creation for a thread within this transaction
        (advisory xact lock, auto-released at commit/rollback) so two
        concurrent `reject` creates can't both pass the active-run check.
        No-op outside Postgres (the test suite runs on SQLite)."""
        if self.db.bind.dialect.name != "postgresql":
            return
        stmt = select(func.pg_advisory_xact_lock(func.hashtext(thread_id)))
        await self.db.execute(stmt)

    async def get_active_for_thread(self, thread_id: str) -> RunDB | None:
        """The thread's current non-terminal run (running first, then newest
        pending), or None."""
        stmt = (
            select(RunDB)
            .where(RunDB.thread_id == thread_id, RunDB.status.in_(ACTIVE_STATUSES))
            .order_by(RunDB.status != RunStatus.running, RunDB.created_at.desc())
            .limit(1)
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def list_active_for_user(
        self, user_id: UUID, *, finished_after: datetime | None = None
    ) -> list[RunDB]:
        """The user's pending/running runs — backs the sidebar activity poll.

        `finished_after` additionally includes runs that reached a terminal
        status since that instant, so a poller can observe outcomes that
        would otherwise fall between two polls. Ordered by `updated_at` so
        the latest outcome per thread comes last.
        """
        activity = RunDB.status.in_(ACTIVE_STATUSES)
        if finished_after is not None:
            activity = or_(activity, RunDB.updated_at >= finished_after)
        stmt = (
            select(RunDB)
            .where(RunDB.user_id == user_id, activity)
            .order_by(RunDB.updated_at)
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def claim_next(self) -> RunDB | None:
        """Atomically move the oldest claimable pending run to `running`.

        A pending run is claimable only while its thread has no running run —
        that's both the per-thread mutex and the whole of the `enqueue`
        strategy (a queued run simply waits until its thread frees up).
        `SKIP LOCKED` lets concurrent dispatchers claim disjoint runs.

        Single-row on purpose: a multi-row claim could pick two pending runs of
        the *same* thread in one statement (the NOT EXISTS evaluates against
        the pre-update snapshot) and trip the one-running-per-thread unique
        index. Cross-instance races on the same thread can still collide on
        that index — callers treat `IntegrityError` as "nothing to claim".
        """
        running = aliased(RunDB)
        claimable = (
            select(RunDB.id)
            .where(
                RunDB.status == RunStatus.pending,
                ~exists(
                    select(running.id).where(
                        running.thread_id == RunDB.thread_id,
                        running.status == RunStatus.running,
                    )
                ),
            )
            .order_by(RunDB.created_at)
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        stmt = (
            update(RunDB)
            .where(RunDB.id.in_(claimable))
            .values(status=RunStatus.running)
            .returning(RunDB.id)
        )
        result = await self.db.execute(stmt)
        claimed_id = result.scalar_one_or_none()
        if claimed_id is None:
            return None
        return await self.get(claimed_id)

    async def finalize_run(
        self,
        run_id: str,
        status: RunStatus,
        *,
        error: str | None = None,
        expected: RunStatus | None = None,
    ) -> str | None:
        """Guarded terminal transition. Returns the run's `thread_id` when the
        update applied, `None` when the current status made the transition
        illegal — already terminal (idempotent — worker and reaper may both
        call), or a source the transition table forbids (a `pending` run can
        never be finalized `success`).

        `expected` narrows the guard to one source status (e.g. cancelling or
        reaping a `pending` run must not finalize it if a dispatcher claimed
        it meanwhile).
        """
        sources = legal_source_statuses(status)
        if expected is not None:
            sources = sources & {expected}
        stmt = (
            update(RunDB)
            .where(RunDB.id == run_id, RunDB.status.in_(sources))
            .values(status=status, error=error)
            .returning(RunDB.thread_id)
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def list_running(self) -> list[RunDB]:
        """All `running` runs — the reaper's liveness worklist."""
        stmt = select(RunDB).where(RunDB.status == RunStatus.running)
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def list_stuck_pending(self, older_than: datetime) -> list[RunDB]:
        """Pending runs past the dispatch timeout whose thread isn't busy.

        A pending run behind a *running* run is a legitimate `enqueue` waiter,
        however old — only never-dispatched zombies qualify.
        """
        running = aliased(RunDB)
        stmt = select(RunDB).where(
            RunDB.status == RunStatus.pending,
            RunDB.created_at < older_than,
            ~exists(
                select(running.id).where(
                    running.thread_id == RunDB.thread_id,
                    running.status == RunStatus.running,
                )
            ),
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def prune_terminal(self, older_than: datetime) -> int:
        """Delete terminal runs created before `older_than`; returns the count.
        Safe by construction: `threads.last_run_status` is denormalized, so
        pruning never breaks the thread badge."""
        stmt = delete(RunDB).where(
            RunDB.status.in_(TERMINAL_STATUSES), RunDB.created_at < older_than
        )
        result = await self.db.execute(stmt)
        return result.rowcount or 0
