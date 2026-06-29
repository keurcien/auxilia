"""Run execution: a single-run worker and the per-process dispatcher.

`RunWorker.run(run_id)` executes one run by wrapping the existing
`Agent.stream(...)` and publishing each SSE chunk to the run's event log, while
watching for cancel and enforcing the wall-clock cap. `RunDispatcher` is the
BRPOP loop that pulls run_ids off the shared queue and runs them, semaphore-
capped at `RUN_WORKER_CONCURRENCY`.
"""

import asyncio
import logging
from contextlib import suppress

from app.agents.runs.control import RunControl
from app.agents.runs.delivery import DeliveryFactory
from app.agents.runs.events import RunEventStream
from app.agents.runs.service import RunService
from app.agents.runs.settings import run_settings
from app.agents.runs.state import RunRecord, RunStatus
from app.agents.runtime import Agent
from app.database import AsyncSessionLocal, get_checkpointer
from app.threads.models import ThreadDB
from app.threads.serialization import pending_interrupt


logger = logging.getLogger(__name__)

# `LangGraphStreamAdapter` swallows exceptions into an SSE error event rather
# than raising, so a clean stream that emitted one of these still failed.
_ERROR_EVENT_PREFIX = "event: error"


class RunWorker:
    """Executes a single run end to end."""

    def __init__(self, redis=None, delivery_factory: DeliveryFactory | None = None):
        self.service = RunService(redis)
        self.registry = self.service.registry
        self.redis = self.service.redis
        self._delivery_factory = delivery_factory

    async def run(self, run_id: str) -> None:
        record = await self.registry.get(run_id)
        if record is None or record.status != RunStatus.pending:
            return  # already handled, reaped, or cancelled before dispatch

        if not await self.registry.claim_active(
            record.thread_id, run_id, ttl=run_settings.heartbeat_timeout_seconds
        ):
            await self._handle_contention(record)
            return

        await self.registry.set_status(run_id, RunStatus.running)
        events = RunEventStream(run_id, self.redis)
        heartbeat = asyncio.create_task(self._heartbeat(record))
        cancel_watch = asyncio.create_task(
            RunControl(run_id, self.redis).wait_for_cancel(
                poll_seconds=run_settings.cancel_poll_seconds
            )
        )
        # A push consumer (e.g. Slack) relays the event log concurrently; it reads
        # from id 0, so there's no race with the chunks we publish below, and it
        # ends when `finalize` writes the sentinel.
        delivery = self._start_delivery(record)
        status, error = RunStatus.success, None
        try:
            status, error = await self._execute(record, events, cancel_watch)
        except Exception as exc:  # noqa: BLE001 — any failure finalizes as error
            logger.exception("Run %s failed", run_id)
            status, error = RunStatus.error, str(exc)
        finally:
            await self._stop(heartbeat)
            await self._stop(cancel_watch)
        await self.service.finalize(run_id, status, error=error)
        if delivery is not None:
            await delivery  # the sentinel is published; let the consumer finish

    def _start_delivery(self, record: RunRecord) -> asyncio.Task | None:
        """Spawn the push-delivery consumer for this run, if one applies.

        Building the consumer is best-effort: a factory that raises must not abort
        the run before it executes/finalizes (which would leave the mutex held and
        the heartbeat orphaned), so failures are logged and treated as no delivery.
        """
        if self._delivery_factory is None:
            return None
        try:
            consumer = self._delivery_factory(record)
        except Exception:  # noqa: BLE001 — delivery is best-effort
            logger.exception("Delivery factory failed for run %s", record.id)
            return None
        if consumer is None:
            return None
        return asyncio.create_task(self._deliver(record.id, consumer))

    @staticmethod
    async def _deliver(run_id: str, consumer) -> None:
        """Run a delivery consumer; a delivery failure never fails the run."""
        try:
            await consumer.run()
        except Exception:  # noqa: BLE001 — delivery is best-effort
            logger.exception("Delivery failed for run %s", run_id)

    async def _execute(
        self, record: RunRecord, events: RunEventStream, cancel_watch: asyncio.Task
    ) -> tuple[RunStatus, str | None]:
        """Race the stream against cancellation and the wall-clock cap; return
        the terminal status and any error text."""
        stream_task = asyncio.create_task(self._stream(record, events))
        done, _ = await asyncio.wait(
            {stream_task, cancel_watch},
            return_when=asyncio.FIRST_COMPLETED,
            timeout=run_settings.max_duration_seconds or None,
        )
        if not done:  # wall-clock cap elapsed
            await self._stop(stream_task)
            return RunStatus.timeout, None

        # A genuine cancel: the watcher completed cleanly with a signal. A failed
        # watcher (e.g. a transient Redis error) must NOT cancel a healthy run.
        if (
            cancel_watch in done
            and not cancel_watch.cancelled()
            and cancel_watch.exception() is None
        ):
            await self._stop(stream_task)
            return RunStatus.cancelled, None
        if cancel_watch in done and cancel_watch.exception() is not None:
            logger.warning(
                "Cancel watcher failed for run %s; continuing: %r",
                record.id,
                cancel_watch.exception(),
            )

        # The stream is the source of truth — make sure it has finished.
        if not stream_task.done():
            await stream_task
        exc = stream_task.exception()
        if exc is not None:
            return RunStatus.error, str(exc)
        if stream_task.result():  # an error SSE was emitted
            return RunStatus.error, None
        if await self._is_interrupted(record.thread_id):
            return RunStatus.interrupted, None
        return RunStatus.success, None

    async def _stream(self, record: RunRecord, events: RunEventStream) -> bool:
        """Run the agent, publishing each SSE chunk. Returns True if an error
        event was emitted."""
        error_seen = False
        async with AsyncSessionLocal() as db:
            thread = await db.get(ThreadDB, record.thread_id)
            if thread is None:
                raise RuntimeError(f"Thread {record.thread_id} not found")
            agent = await Agent.build(thread=thread, db=db)
            async for sse in agent.stream(
                agent_input=record.input,
                command=record.command,
                trigger=record.trigger,
                config_overrides=record.config_overrides,
                output_schema=record.output_schema,
            ):
                if sse.startswith(_ERROR_EVENT_PREFIX):
                    error_seen = True
                await events.publish(sse)
        return error_seen

    async def _heartbeat(self, record: RunRecord) -> None:
        """Stamp liveness and keep the thread mutex alive while running."""
        while True:
            await asyncio.sleep(run_settings.heartbeat_interval_seconds)
            await self.registry.heartbeat(record.id)
            await self.registry.refresh_active(
                record.thread_id, record.id, ttl=run_settings.heartbeat_timeout_seconds
            )

    async def _is_interrupted(self, thread_id: str) -> bool:
        async with get_checkpointer() as checkpointer:
            checkpoint = await checkpointer.aget_tuple(
                config={"configurable": {"thread_id": thread_id}}
            )
        return checkpoint is not None and pending_interrupt(checkpoint) is not None

    async def _handle_contention(self, record: RunRecord) -> None:
        """Another run holds the thread mutex. `enqueue` waits and retries;
        `reject` (the create-time default) finalizes as error if it ever lands here."""
        if record.multitask_strategy == "enqueue":
            await asyncio.sleep(0.5)
            await self.service.queue.enqueue(record.id)
            return
        await self.service.finalize(
            record.id, RunStatus.error, error="Thread already has an active run."
        )

    @staticmethod
    async def _stop(task: asyncio.Task) -> None:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task


class RunDispatcher:
    """Pulls run_ids off the shared queue and runs them, capped at
    `RUN_WORKER_CONCURRENCY` concurrent runs per process."""

    def __init__(self, redis=None, delivery_factory: DeliveryFactory | None = None):
        self.worker = RunWorker(redis, delivery_factory=delivery_factory)
        self.queue = self.worker.service.queue
        self._semaphore = asyncio.Semaphore(run_settings.worker_concurrency)
        self._stopping = asyncio.Event()
        self._tasks: set[asyncio.Task] = set()

    async def run(self) -> None:
        logger.info(
            "run dispatcher started: concurrency=%s", run_settings.worker_concurrency
        )
        # Acquire a slot *before* dequeuing so at most `concurrency` runs are ever
        # in flight; the loop blocks on `acquire` when saturated.
        while not self._stopping.is_set():
            await self._semaphore.acquire()
            run_id = (
                None
                if self._stopping.is_set()
                else await self.queue.dequeue(timeout=5.0)
            )
            if run_id is None:
                self._semaphore.release()
                continue
            task = asyncio.create_task(self._run_one(run_id))
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)

    async def _run_one(self, run_id: str) -> None:
        try:
            await self.worker.run(run_id)
        except Exception:  # noqa: BLE001 — never let one run kill the dispatcher
            logger.exception("Unhandled error running %s", run_id)
        finally:
            self._semaphore.release()

    async def stop(self, *, drain_timeout: float = 10.0) -> None:
        """Stop accepting work, drain in-flight runs, then cancel stragglers.

        Cancelling the leftovers (before the caller closes Redis) lets them
        unwind deterministically rather than failing mid-finalize against a
        closed connection; the reaper recovers anything left non-terminal.
        """
        self._stopping.set()
        if not self._tasks:
            return
        _, pending = await asyncio.wait(self._tasks, timeout=drain_timeout)
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
