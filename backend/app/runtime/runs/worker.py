"""Run execution: a single-run worker and the per-process dispatcher.

`RunWorker.run(record)` executes one already-claimed run by wrapping the
existing `Agent.stream(...)` and publishing each protocol event to the run's
event log, while watching for cancel and enforcing the wall-clock cap.
`RunDispatcher` claims pending runs off Postgres (the trigger-scanner
`SKIP LOCKED` pattern — claiming *is* the pending → running transition) and
runs them, semaphore-capped at `RUN_WORKER_CONCURRENCY`. It is woken through a
Redis list (`RunService._signal_dispatch`) and only falls back to a slow
Postgres poll, so an idle instance costs Postgres nothing.
"""

import asyncio
import logging
import time
from contextlib import aclosing, suppress

from sqlalchemy.exc import IntegrityError

from app.background import LoopHealth, register_loop
from app.database import AsyncSessionLocal, get_checkpointer
from app.exceptions import root_cause
from app.mcp.client.exceptions import as_oauth_required
from app.runtime.agent import Agent
from app.runtime.hitl import pending_interrupt
from app.runtime.protocol.wire import encode_event
from app.runtime.runs.control import RunControl
from app.runtime.runs.delivery import DeliveryFactory
from app.runtime.runs.events import BufferedEventPublisher, RunEventStream
from app.runtime.runs.liveness import DispatcherLiveness, RunLiveness
from app.runtime.runs.models import RunDB
from app.runtime.runs.service import RunService
from app.runtime.runs.settings import run_settings
from app.runtime.runs.state import MCP_REAUTH_ERROR, RunStatus
from app.threads.models import ThreadDB


logger = logging.getLogger(__name__)


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
    return await RunService.required_oauth_url(db, thread.agent_id, user_id) is not None


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
        # from id 0, so there's no race with the events we publish below, and it
        # ends when `finalize` writes the terminal entry.
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
            await delivery  # the terminal is published; let the consumer finish

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
            # A server whose stored token was revoked only fails once the run
            # opens its sessions. `str()` of that exception is a bare authorize
            # URL, which tells a Slack or web reader nothing — stamp the same
            # error the pre-flight uses, so the reconnect affordance appears on
            # both paths.
            if as_oauth_required(exc) is not None:
                return RunStatus.error, MCP_REAUTH_ERROR
            # Some failures stringify to "" (CancelledError leaks, closed
            # resources) — fall back to the type name so the UI and the run
            # record never carry a blank error. The record outlives the event
            # log's TTL, so this is what a reload/reattach shows.
            cause = root_cause(exc)
            return RunStatus.error, str(cause) or type(cause).__name__
        if await self._is_interrupted(record.thread_id):
            return RunStatus.interrupted, None
        return RunStatus.success, None

    async def _stream(self, record: RunDB, events: RunEventStream) -> None:
        """Run the agent, publishing each protocol event to the log. A graph
        failure propagates (the stream raises after its buffered events)."""
        async with AsyncSessionLocal() as db:
            thread = await db.get(ThreadDB, record.thread_id)
            if thread is None:
                raise RuntimeError(f"Thread {record.thread_id} not found")
            if await _mcp_unauthorized(db, thread, str(record.user_id)):
                raise RuntimeError(MCP_REAUTH_ERROR)
            agent = await Agent.build(thread=thread, db=db)
            # Commit here, on purpose (CLAUDE.md, transactions, exception 2):
            # holding this pooled connection open for the length of an agent
            # run risks pool starvation, so `build`'s transaction ends before
            # the stream starts.
            await db.commit()
            # Buffered: one awaited XADD per event is one Redis round trip per
            # token, serialized with the agent stream. Exiting the buffer drains
            # it, which is what keeps the last events ahead of `finalize`'s
            # terminal entry.
            # `aclosing`: a cancel usually lands in `publish`, outside the
            # generator; closing it here, not whenever it is collected, is
            # what runs its cleanup (the interrupted-answer save) before
            # `finalize` lets the next run start.
            async with (
                BufferedEventPublisher(events) as publisher,
                aclosing(
                    agent.stream(
                        agent_input=record.input,
                        command=record.command,
                        trigger=record.trigger,
                        config_overrides=record.config_overrides,
                        output_schema=record.output_schema,
                    )
                ) as stream,
            ):
                async for event in stream:
                    await publisher.publish(encode_event(event))

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
        # The fallback is already due, so the first pass claims whatever was
        # created while no dispatcher was up.
        self._last_claim_at = float("-inf")
        self._claimed_last = False
        self._wake_failing = False
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
            "run dispatcher started: concurrency=%s wake_poll=%ss claim_fallback=%ss",
            run_settings.worker_concurrency,
            run_settings.wake_poll_seconds,
            run_settings.claim_fallback_seconds,
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
                    await self._sleep(min(run_settings.wake_poll_seconds * 4, 5.0))
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
        """One pass: take a slot, claim a run if anything says one may be
        there, start it."""
        await self._semaphore.acquire()
        if self._stopping.is_set():
            self._semaphore.release()
            return
        # Postgres is queried only after a successful claim (keep draining),
        # on a wake token, or when the fallback is due. The token is popped
        # with a slot held, so a saturated instance never consumes a wake-up
        # it cannot act on — and on every pass that holds one, so a burst's
        # tokens are used up by the passes that drain it rather than left to
        # trigger idle claims later. A pass whose fallback is already due
        # skips the pop: a stalled Redis must not postpone the scheduled
        # Postgres claim, and the token waits for the next pass.
        due = (
            time.monotonic() - self._last_claim_at
            >= run_settings.claim_fallback_seconds
        )
        woken = not due and await self._pop_wake()
        if not (self._claimed_last or woken or due):
            self._semaphore.release()
            await self._sleep(run_settings.wake_poll_seconds)
            return
        self._last_claim_at = time.monotonic()
        record = await self._claim_one()
        self._claimed_last = record is not None
        if record is None:
            self._semaphore.release()
            await self._sleep(run_settings.wake_poll_seconds)
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

    async def _pop_wake(self) -> bool:
        """Take one wake token; a Redis error reads as "no token" and the
        fallback poll carries dispatch. Bounded by the fallback interval, so a
        Redis that hangs rather than fails delays that poll by one period at
        most instead of pinning the loop."""
        try:
            woken = await asyncio.wait_for(
                self.service.pop_wake(), timeout=run_settings.claim_fallback_seconds
            )
        except Exception:  # noqa: BLE001 — a blip must not end the loop
            # Once per outage, not twice a second with a traceback.
            if not self._wake_failing:
                logger.warning("Wake token pop failed; polling instead", exc_info=True)
            self._wake_failing = True
            return False
        self._wake_failing = False
        return woken

    async def _claim_one(self) -> RunDB | None:
        """Claim the next dispatchable run; a claim failure (e.g. a transient
        DB error) must not kill the loop. It re-arms the fallback, so the next
        pass retries promptly instead of letting the token it consumed count
        as "nothing to claim"."""
        try:
            return await self.service.claim_next()
        except IntegrityError:
            # Another instance claimed a run on the same thread in the same
            # instant and won the one-running-per-thread index — not ours.
            logger.debug("Run claim lost a cross-instance race")
        except Exception:
            logger.exception("Run claim failed")
        self._last_claim_at = float("-inf")
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
