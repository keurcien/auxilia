"""Run execution: a single-run worker and the per-process dispatcher.

`RunWorker.run(record)` executes one already-claimed run by wrapping the
existing `Agent.stream(...)` and publishing each SSE chunk to the run's event
log, while watching for cancel and enforcing the wall-clock cap.
`RunDispatcher` polls Postgres for claimable pending runs (the trigger-scanner
`SKIP LOCKED` pattern — claiming *is* the pending → running transition) and
runs them, semaphore-capped at `RUN_WORKER_CONCURRENCY`.
"""

import asyncio
import logging
from contextlib import suppress

from sqlalchemy.exc import IntegrityError

from app.agents.runs.control import RunControl
from app.agents.runs.delivery import DeliveryFactory
from app.agents.runs.events import BufferedEventPublisher, RunEventStream
from app.agents.runs.liveness import DispatcherLiveness, RunLiveness
from app.agents.runs.models import RunDB
from app.agents.runs.service import RunService
from app.agents.runs.settings import run_settings
from app.agents.runs.state import MCP_REAUTH_ERROR, RunStatus
from app.agents.runtime import Agent
from app.agents.stream import decode_sse_blocks
from app.background import LoopHealth, register_loop
from app.database import AsyncSessionLocal, get_checkpointer
from app.exceptions import root_cause
from app.mcp.client.exceptions import OAuthAuthorizationRequired
from app.threads.models import ThreadDB
from app.threads.serialization import pending_interrupt


logger = logging.getLogger(__name__)

# `LangGraphStreamAdapter` swallows exceptions into an SSE error event rather
# than raising, so a clean stream that emitted one of these still failed.
_ERROR_EVENT_PREFIX = "event: error"


def _error_event_message(sse: str) -> str:
    """The `message` of an `event: error` SSE chunk ("" when malformed).

    The event log TTLs away, but the run record doesn't — persisting the
    message lets the UI surface the failure after a reload/reattach."""
    for event, data in decode_sse_blocks(sse):
        if event == "error":
            if isinstance(data, dict):
                return str(data.get("message") or "")
            return str(data or "")
    return ""


async def _cancel(task: asyncio.Task) -> None:
    """Cancel a background task and wait for it to unwind."""
    task.cancel()
    with suppress(asyncio.CancelledError):
        await task


async def _mcp_unauthorized(db, thread: ThreadDB, user_id: str) -> bool:
    """Pre-flight for background-launched runs (trigger scanner, Slack, HITL
    resume): True when a bound OAuth server is confirmed unauthorized for this
    user. HTTP run creation already 401s before the run exists; this is the
    net under every path that can't receive a 401 — the run fails fast with an
    actionable error instead of burning an MCP session build.

    Delegates to the HTTP preflight so every launch path shares one definition
    of "unauthorized": probes all OAuth servers regardless of tools state,
    fails open on infra errors, and commits to release the connection before
    its network IO."""
    try:
        await RunService.ensure_mcp_authorized(db, thread.agent_id, user_id)
    except OAuthAuthorizationRequired:
        return True
    return False


class RunWorker:
    """Executes a single claimed run end to end."""

    def __init__(self, redis=None, delivery_factory: DeliveryFactory | None = None):
        self.service = RunService(redis)
        self.redis = self.service.redis
        self._delivery_factory = delivery_factory

    async def run(self, record: RunDB) -> None:
        """Execute a run the dispatcher just claimed (already `running`)."""
        events = RunEventStream(record.id, self.redis)
        liveness = RunLiveness(record.id, self.redis)
        # Stamp before anything else: the reaper treats a running run with no
        # liveness key (past the grace window) as a dead worker.
        await liveness.stamp(ttl=run_settings.heartbeat_timeout_seconds)
        heartbeat = asyncio.create_task(self._heartbeat(liveness, events))
        cancel_watch = asyncio.create_task(
            RunControl(record.id, self.redis).wait_for_cancel(
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
        except Exception as exc:
            logger.exception("Run %s failed", record.id)
            status, error = RunStatus.error, str(root_cause(exc))
        finally:
            await _cancel(heartbeat)
            await _cancel(cancel_watch)
        await self.service.finalize(record.id, status, error=error)
        if delivery is not None:
            await delivery  # the sentinel is published; let the consumer finish

    def _start_delivery(self, record: RunDB) -> asyncio.Task | None:
        """Spawn the push-delivery consumer for this run, if one applies.

        Building the consumer is best-effort: a factory that raises must not
        abort the run before it executes/finalizes, so failures are logged and
        treated as no delivery.
        """
        if self._delivery_factory is None:
            return None
        try:
            consumer = self._delivery_factory(record)
        except Exception:
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
        except Exception:
            logger.exception("Delivery failed for run %s", run_id)

    async def _execute(
        self, record: RunDB, events: RunEventStream, cancel_watch: asyncio.Task
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
            await _cancel(stream_task)
            return RunStatus.timeout, None

        # A genuine cancel: the watcher completed cleanly with a signal. A failed
        # watcher (e.g. a transient Redis error) must NOT cancel a healthy run.
        if (
            cancel_watch in done
            and not cancel_watch.cancelled()
            and cancel_watch.exception() is None
        ):
            await _cancel(stream_task)
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
            return RunStatus.error, str(root_cause(exc))
        if (stream_error := stream_task.result()) is not None:
            # An error SSE was emitted — persist its message on the record so
            # the failure survives the event log's TTL.
            return RunStatus.error, stream_error or None
        if await self._is_interrupted(record.thread_id):
            return RunStatus.interrupted, None
        return RunStatus.success, None

    async def _stream(self, record: RunDB, events: RunEventStream) -> str | None:
        """Run the agent, publishing each SSE chunk. Returns the message of the
        first error event emitted, or None if the stream was clean."""
        error_message: str | None = None
        async with AsyncSessionLocal() as db:
            thread = await db.get(ThreadDB, record.thread_id)
            if thread is None:
                raise RuntimeError(f"Thread {record.thread_id} not found")
            if await _mcp_unauthorized(db, thread, str(record.user_id)):
                raise RuntimeError(MCP_REAUTH_ERROR)
            agent = await Agent.build(thread=thread, db=db)
            # Buffered: one awaited XADD per chunk is one Redis round trip per
            # token, serialized with the agent stream. Exiting the buffer drains
            # it, which is what keeps the last chunks ahead of `finalize`'s end
            # sentinel.
            async with BufferedEventPublisher(events) as publisher:
                async for sse in agent.stream(
                    agent_input=record.input,
                    command=record.command,
                    trigger=record.trigger,
                    config_overrides=record.config_overrides,
                    output_schema=record.output_schema,
                ):
                    if error_message is None and sse.startswith(_ERROR_EVENT_PREFIX):
                        error_message = _error_event_message(sse)
                    await publisher.publish(sse)
        return error_message

    async def _heartbeat(self, liveness: RunLiveness, events: RunEventStream) -> None:
        """Keep the liveness key fresh, and the event log's safety TTL pushed
        out, while the run executes.

        Every tick is wrapped: a single transient Redis error used to kill this
        loop silently, after which liveness expired and the reaper finalized a
        perfectly healthy streaming run as `error`. The cancel watcher already
        got this treatment (`_execute` tolerates a failed watcher); the
        heartbeat did not.
        """
        while True:
            await asyncio.sleep(run_settings.heartbeat_interval_seconds)
            try:
                await liveness.stamp(ttl=run_settings.heartbeat_timeout_seconds)
                await events.touch_ttl()
            except Exception:  # noqa: BLE001 — a blip must not end the heartbeat
                logger.warning(
                    "Heartbeat for run %s failed; retrying next tick",
                    liveness.run_id,
                    exc_info=True,
                )

    async def _is_interrupted(self, thread_id: str) -> bool:
        async with get_checkpointer() as checkpointer:
            checkpoint = await checkpointer.aget_tuple(
                config={"configurable": {"thread_id": thread_id}}
            )
        return checkpoint is not None and pending_interrupt(checkpoint) is not None


class RunDispatcher:
    """Claims pending runs off Postgres and runs them, capped at
    `RUN_WORKER_CONCURRENCY` concurrent runs per process."""

    def __init__(self, redis=None, delivery_factory: DeliveryFactory | None = None):
        self.worker = RunWorker(redis, delivery_factory=delivery_factory)
        self.service = self.worker.service
        self.liveness = DispatcherLiveness(self.service.redis)
        self._semaphore = asyncio.Semaphore(run_settings.worker_concurrency)
        self._stopping = asyncio.Event()
        self._tasks: set[asyncio.Task] = set()
        self._heartbeat: asyncio.Task | None = None
        # Not a `PeriodicLoop`: this loop is not periodic — it blocks on the
        # semaphore for as long as every slot is busy, which can be the whole
        # length of an agent turn. Health is therefore ticked by
        # `_announce_liveness`, not by the claim loop, and sized to that
        # cadence. Ticking from the claim loop would make a *fully occupied*
        # dispatcher look dead within a minute and get a healthy, busy worker
        # recycled mid-run — worse than the failure /health exists to catch.
        self.health = register_loop(
            LoopHealth(
                name="run-dispatcher",
                interval=run_settings.heartbeat_interval_seconds,
            )
        )

    async def run(self) -> None:
        logger.info(
            "run dispatcher started: concurrency=%s claim_interval=%ss",
            run_settings.worker_concurrency,
            run_settings.claim_interval_seconds,
        )
        self.health.started = True
        self.health.mark_tick()
        self._heartbeat = asyncio.create_task(self._announce_liveness())
        try:
            # Acquire a slot *before* claiming so at most `concurrency` runs are
            # ever in flight; the loop blocks on `acquire` when saturated.
            while not self._stopping.is_set():
                try:
                    await self._claim_and_dispatch()
                except Exception as exc:
                    # `_claim_one` already absorbs claim failures; reaching here
                    # means the loop's own machinery broke. Without this the
                    # dispatcher died for good and the instance kept serving 200s
                    # while no run ever executed again (design review §2.3).
                    self.health.mark_failure(exc)
                    logger.exception("Run dispatch loop failed; retrying")
                    await self._sleep(min(run_settings.claim_interval_seconds * 4, 5.0))
        finally:
            # The heartbeat is what ticks health, so it must not outlive this
            # loop: an orphaned heartbeat would keep reporting a dispatcher that
            # is no longer dispatching. `stopped` is set only for a shutdown we
            # asked for — leaving any other exit to go stale and fail /health.
            if self._heartbeat is not None:
                await _cancel(self._heartbeat)
                self._heartbeat = None
            self.health.stopped = self._stopping.is_set()

    async def _claim_and_dispatch(self) -> None:
        """One pass: take a slot, claim a run, start it."""
        await self._semaphore.acquire()
        record = None if self._stopping.is_set() else await self._claim_one()
        if record is None:
            self._semaphore.release()
            await self._sleep(run_settings.claim_interval_seconds)
            return
        task = asyncio.create_task(self._run_one(record))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _announce_liveness(self) -> None:
        """Tell the cluster a dispatcher is up, on an independent timer.

        Not stamped from the claim loop above: that loop blocks on
        `_semaphore.acquire()` while every slot is busy, which is precisely the
        backlog the reaper must not mistake for "nothing is dispatching".
        """
        while not self._stopping.is_set():
            try:
                await self.liveness.stamp(ttl=run_settings.heartbeat_timeout_seconds)
            except Exception as exc:  # noqa: BLE001 — a blip must not end the heartbeat
                self.health.mark_failure(exc)
                logger.warning("Dispatcher liveness stamp failed", exc_info=True)
            else:
                # This, not the claim loop, is the dispatcher's health signal —
                # see the note on `self.health` above.
                self.health.mark_tick()
            await self._sleep(run_settings.heartbeat_interval_seconds)

    async def _claim_one(self) -> RunDB | None:
        """Claim the next dispatchable run; a claim failure (e.g. a transient
        DB error) must not kill the loop."""
        try:
            return await self.service.claim_next()
        except IntegrityError:
            # Another instance claimed a run on the same thread in the same
            # instant and won the one-running-per-thread index — not ours.
            logger.debug("Run claim lost a cross-instance race")
            return None
        except Exception:
            logger.exception("Run claim failed")
            return None

    async def _run_one(self, record: RunDB) -> None:
        try:
            await self.worker.run(record)
        except Exception:
            logger.exception("Unhandled error running %s", record.id)
        finally:
            self._semaphore.release()

    async def _sleep(self, seconds: float) -> None:
        """Idle between claim polls, but wake immediately on stop."""
        with suppress(TimeoutError):
            await asyncio.wait_for(self._stopping.wait(), timeout=seconds)

    async def stop(self, *, drain_timeout: float = 10.0) -> None:
        """Stop accepting work, drain in-flight runs, then cancel stragglers.

        Cancelling the leftovers (before the caller closes Redis) lets them
        unwind deterministically rather than failing mid-finalize against a
        closed connection; the reaper recovers anything left non-terminal.
        """
        self._stopping.set()
        if self._heartbeat is not None:
            await _cancel(self._heartbeat)
            self._heartbeat = None
        if not self._tasks:
            return
        _, pending = await asyncio.wait(self._tasks, timeout=drain_timeout)
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
