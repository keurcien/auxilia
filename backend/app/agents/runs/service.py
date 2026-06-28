"""RunService — the public API of the durable runtime.

Orchestrates the Redis primitives (registry / queue / events / control) into the
verbs the router, worker, and reaper call. Redis-backed, so it deliberately does
not extend `BaseService[ModelDB, Repository]` (see `SPEC.md`); the primitives are
its data-access layer.
"""

import logging
from collections.abc import AsyncGenerator
from uuid import uuid4

from redis.asyncio import Redis

from app.agents.runs.control import RunControl
from app.agents.runs.events import RunEventStream
from app.agents.runs.queue import RunQueue
from app.agents.runs.registry import RunRegistry
from app.agents.runs.settings import run_settings
from app.agents.runs.state import RunRecord, RunStatus, is_terminal
from app.exceptions import DomainValidationError, NotFoundError
from app.redis_client import get_redis


logger = logging.getLogger(__name__)


class RunService:
    def __init__(self, redis: Redis | None = None):
        self.redis: Redis = redis or get_redis()
        self.registry = RunRegistry(self.redis)
        self.queue = RunQueue(self.redis)

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
        multitask_strategy: str = "reject",
    ) -> RunRecord:
        """Create + enqueue a run. Caller has already authorized the thread.

        With the default `reject` strategy, creating a run while the thread has an
        active one raises `DomainValidationError`.
        """
        if multitask_strategy == "reject" and await self.registry.get_active_id(
            thread_id
        ):
            raise DomainValidationError("This thread already has an active run.")
        record = RunRecord(
            id=str(uuid4()),
            thread_id=thread_id,
            user_id=user_id,
            input=input,
            command=command,
            trigger=trigger,
            config_overrides=config_overrides,
            output_schema=output_schema,
            multitask_strategy=multitask_strategy,
        )
        await self.registry.create(record, ttl=run_settings.ttl_seconds)
        await self.queue.enqueue(record.id)
        return record

    async def get(self, run_id: str) -> RunRecord:
        record = await self.registry.get(run_id)
        if record is None:
            raise NotFoundError("Run not found")
        return record

    async def list_for_thread(self, thread_id: str) -> list[RunRecord]:
        return await self.registry.list_for_thread(thread_id)

    async def get_active(self, thread_id: str) -> RunRecord | None:
        run_id = await self.registry.get_active_id(thread_id)
        return await self.registry.get(run_id) if run_id else None

    async def cancel(self, run_id: str) -> RunRecord:
        """Stop a run. A pending run is finalized directly; a running one gets a
        signal its worker picks up. Terminal runs are a no-op."""
        record = await self.get(run_id)
        if is_terminal(record.status):
            return record
        if record.status == RunStatus.pending:
            return await self.finalize(run_id, RunStatus.cancelled) or record
        await RunControl(run_id, self.redis).request_cancel(
            ttl=run_settings.ttl_seconds
        )
        return record

    async def stream(
        self, run_id: str, last_event_id: str = "0"
    ) -> AsyncGenerator[str, None]:
        """Relay a run's SSE event log from `last_event_id` until it ends."""
        async for sse in RunEventStream(run_id, self.redis).subscribe(last_event_id):
            yield sse

    async def wait_for_terminal(self, run_id: str) -> RunRecord:
        """Block until the run reaches a terminal state, then return its record.

        The synchronous `/runs/invoke` consumer: it rides the event log's blocking
        read (no polling) and discards the chunks — it only needs to know the run
        finished, then reads the result back from the checkpoint."""
        async for _ in RunEventStream(run_id, self.redis).subscribe():
            pass  # drain to the end sentinel
        return await self.get(run_id)

    async def finalize(
        self, run_id: str, status: RunStatus, *, error: str | None = None
    ) -> RunRecord | None:
        """Move a run to a terminal state: set status, emit the `end` sentinel,
        release the thread mutex, and TTL the keys. Idempotent — a run that's
        already terminal is left untouched (worker/reaper may both call this)."""
        record = await self.registry.get(run_id)
        if record is None or is_terminal(record.status):
            return record
        updated = await self.registry.set_status(run_id, status, error=error)
        await RunEventStream(run_id, self.redis).publish_end(status)
        await self.registry.release_active(record.thread_id, run_id)
        await self.registry.set_ttl(run_id, run_settings.ttl_seconds)
        return updated
