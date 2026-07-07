"""RunService — the public API of the durable runtime.

Orchestrates Postgres (the run record — `RunRepository`) and Redis (the
per-run ephemera — event log, cancel channel, liveness) into the verbs the
router, worker, and reaper call.

Sessions: every verb opens its own short `AsyncSessionLocal()` transaction
rather than riding `get_db` — the service is called from outside any HTTP
request (worker, reaper, Slack, trigger scanner), and even router calls must
commit before the response starts streaming.
"""

import logging
from collections.abc import AsyncGenerator
from datetime import datetime
from uuid import UUID

from redis.asyncio import Redis

from app.agents.runs import keys
from app.agents.runs.control import RunControl
from app.agents.runs.events import RunEventStream, end_sentinel
from app.agents.runs.liveness import RunLiveness
from app.agents.runs.models import RunDB
from app.agents.runs.repository import RunRepository
from app.agents.runs.settings import run_settings
from app.agents.runs.state import RunStatus, is_terminal
from app.database import AsyncSessionLocal
from app.exceptions import DomainValidationError, NotFoundError
from app.redis_client import get_redis
from app.threads.repository import ThreadRepository


logger = logging.getLogger(__name__)


class RunService:
    def __init__(self, redis: Redis | None = None):
        self.redis: Redis = redis or get_redis()

    async def create(
        self,
        *,
        thread_id: str,
        user_id: str,
        input: dict | None = None,
        command: dict | None = None,
        trigger: str | None = None,
        config_overrides: dict | None = None,
        output_schema: dict | None = None,
        delivery: dict | None = None,
        multitask_strategy: str = "reject",
    ) -> RunDB:
        """Create a pending run. Caller has already authorized the thread.

        With the default `reject` strategy, creating a run while the thread has
        a pending/running one raises `DomainValidationError`. With `enqueue`,
        the run simply waits — the dispatcher only claims runs whose thread has
        no running run.

        `delivery` is an opaque push-target descriptor (e.g. Slack channel/
        thread) the worker hands to a delivery consumer; `None` means a pull
        subscriber rides the event log instead.
        """
        if input is not None and command is not None:
            raise DomainValidationError("Provide either input or command, not both.")
        async with AsyncSessionLocal() as db:
            repository = RunRepository(db)
            if (
                multitask_strategy == "reject"
                and await repository.get_active_for_thread(thread_id) is not None
            ):
                raise DomainValidationError("This thread already has an active run.")
            run = await repository.create(
                RunDB(
                    thread_id=thread_id,
                    user_id=UUID(user_id),
                    input=input,
                    command=command,
                    trigger=trigger,
                    config_overrides=config_overrides,
                    output_schema=output_schema,
                    delivery=delivery,
                    multitask_strategy=multitask_strategy,
                )
            )
            await db.commit()
        return run

    async def get(self, run_id: str) -> RunDB:
        async with AsyncSessionLocal() as db:
            record = await RunRepository(db).get(run_id)
        if record is None:
            raise NotFoundError("Run not found")
        return record

    async def list_for_thread(self, thread_id: str) -> list[RunDB]:
        async with AsyncSessionLocal() as db:
            return await RunRepository(db).list_for_thread(thread_id)

    async def get_active(self, thread_id: str) -> RunDB | None:
        async with AsyncSessionLocal() as db:
            return await RunRepository(db).get_active_for_thread(thread_id)

    async def list_active_for_user(self, user_id: str) -> list[RunDB]:
        """The user's pending/running runs — backs the sidebar activity poll."""
        async with AsyncSessionLocal() as db:
            return await RunRepository(db).list_active_for_user(UUID(user_id))

    async def claim_next(self) -> RunDB | None:
        """Atomically claim the next dispatchable run (the dispatcher's poll).
        Claiming *is* the pending → running transition."""
        async with AsyncSessionLocal() as db:
            run = await RunRepository(db).claim_next()
            await db.commit()
        return run

    async def cancel(self, run_id: str) -> RunDB:
        """Stop a run. A pending run is finalized directly; a running one gets
        a signal its worker picks up. Terminal runs are a no-op."""
        record = await self.get(run_id)
        if is_terminal(record.status):
            return record
        if record.status == RunStatus.pending:
            updated = await self.finalize(
                run_id, RunStatus.cancelled, expected=RunStatus.pending
            )
            if updated is not None and updated.status == RunStatus.cancelled:
                return updated
            # A dispatcher claimed it between our read and the guarded update —
            # fall through and cancel it like any running run.
        await RunControl(run_id, self.redis).request_cancel(
            ttl=run_settings.ttl_seconds
        )
        return record

    async def stream(
        self, run_id: str, last_event_id: str = "0"
    ) -> AsyncGenerator[str, None]:
        """Relay a run's SSE event log from `last_event_id` until it ends.

        A terminal run whose event log has expired (reattach later than the
        Redis TTL) yields a synthetic end sentinel instead of blocking forever
        on an empty stream — the record outlives the log now.
        """
        events = RunEventStream(run_id, self.redis)
        if not await events.exists():
            record = await self.get(run_id)
            if is_terminal(record.status):
                yield end_sentinel(record.status)
                return
        async for sse in events.subscribe(last_event_id):
            yield sse

    async def wait_for_terminal(self, run_id: str) -> RunDB:
        """Block until the run reaches a terminal state, then return its record.

        The synchronous `/runs/invoke` consumer: it rides the event log's
        blocking read (no polling) and discards the chunks — it only needs to
        know the run finished, then reads the result back from the checkpoint."""
        async for _ in self.stream(run_id):
            pass  # drain to the end sentinel
        return await self.get(run_id)

    async def finalize(
        self,
        run_id: str,
        status: RunStatus,
        *,
        error: str | None = None,
        expected: RunStatus | None = None,
    ) -> RunDB | None:
        """Move a run to a terminal state.

        One Postgres transaction covers the run's terminal update *and* the
        `threads.last_run_status` stamp, so they can never disagree. Then the
        `end` sentinel is published and the Redis ephemera get their TTL.
        Idempotent — a run that's already terminal is left untouched (worker
        and reaper may both call this). Returns the current record, or `None`
        if the run doesn't exist.
        """
        async with AsyncSessionLocal() as db:
            repository = RunRepository(db)
            thread_id = await repository.finalize_run(
                run_id, status, error=error, expected=expected
            )
            if thread_id is not None:
                await ThreadRepository(db).set_last_run_status(thread_id, status.value)
            await db.commit()
            record = await repository.get(run_id)
        if thread_id is not None:
            await RunEventStream(run_id, self.redis).publish_end(status)
            await self._expire_ephemera(run_id)
        return record

    # --- reaper support -----------------------------------------------------

    async def list_running(self) -> list[RunDB]:
        async with AsyncSessionLocal() as db:
            return await RunRepository(db).list_running()

    async def list_stuck_pending(self, older_than: datetime) -> list[RunDB]:
        async with AsyncSessionLocal() as db:
            return await RunRepository(db).list_stuck_pending(older_than)

    async def prune_terminal(self, older_than: datetime) -> int:
        async with AsyncSessionLocal() as db:
            count = await RunRepository(db).prune_terminal(older_than)
            await db.commit()
        return count

    async def _expire_ephemera(self, run_id: str) -> None:
        """TTL the finished run's event log + control key (the reattach/replay
        window) and drop its liveness key immediately."""
        async with self.redis.pipeline(transaction=True) as pipe:
            pipe.expire(keys.run_events_key(run_id), run_settings.ttl_seconds)
            pipe.expire(keys.run_control_key(run_id), run_settings.ttl_seconds)
            await pipe.execute()
        await RunLiveness(run_id, self.redis).clear()
