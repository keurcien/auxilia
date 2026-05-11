"""Run worker.

Owns the entire lifecycle of a run: dequeue → build agent → stream → finalise.

The worker is the only module that calls ``agent.astream``. Everything else is
plumbing (Redis transport, state machine, audit logging, dangling-tool-call
patching) and lives in dedicated modules. This separation is the architecture
principle from PRD §5.5 — one responsibility per module.

Concurrency model
-----------------

A worker is a single asyncio task running ``run_forever``. It pulls one run at
a time off the queue. Inside ``_execute``, three coroutines run concurrently
under ``asyncio.wait``:

- the astream consumer (writes events to Redis),
- the cancel watcher (BLPOPs the control list),
- the heartbeat loop (HSETs ``heartbeat_at`` every 5s).

Cancellation flows through ``astream_task.cancel()`` so LangGraph's executor
gets a clean ``CancelledError`` and tears down in-flight tools cooperatively.
The post-cancellation patch step is wrapped in ``asyncio.shield`` so the
synthetic ToolMessages reach the checkpoint even though the parent supervisor
may itself be cancelled.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import socket
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from app.agents.runs.control import RunControl
from app.agents.runs.events import RunEvents
from app.agents.runs.patch import patch_dangling_tool_calls
from app.agents.runs.queue import RunQueue
from app.agents.runs.registry import RunRegistry
from app.agents.runs.state import (
    CancellationReason,
    IllegalTransitionError,
    RunEvent,
    RunState,
    is_terminal,
    transition,
    utcnow,
)
from app.agents.runtime import AgentRuntime
from app.agents.stream import LangGraphStreamAdapter
from app.database import AsyncSessionLocal, get_psycopg_conn_string
from app.threads.service import ThreadService


logger = logging.getLogger(__name__)


HEARTBEAT_INTERVAL_SECONDS: float = 5.0
INPUT_KEY_TTL_SECONDS: int = 30 * 60


def _input_key(run_id: UUID) -> str:
    return f"run:{run_id}:input"


def _utc(dt: datetime | None) -> datetime | None:
    """Best-effort tz-aware UTC normaliser."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


# --- input payload encoding -------------------------------------------------


async def store_input(redis, run_id: UUID, payload: dict[str, Any]) -> None:
    """Service-side helper to drop a run's POST payload into Redis before enqueuing."""
    await redis.set(
        _input_key(run_id),
        json.dumps(payload, default=str),
        ex=INPUT_KEY_TTL_SECONDS,
    )


async def load_input(redis, run_id: UUID) -> dict[str, Any]:
    raw = await redis.get(_input_key(run_id))
    if raw is None:
        return {}
    return json.loads(raw)


# --- worker ----------------------------------------------------------------


class RunWorker:
    """Executes one run when handed a ``run_id`` by the dispatcher.

    No persistent loop here — the dispatcher (below) does the dequeueing and
    spawns a fresh ``asyncio.Task`` per run with a new ``RunWorker``. The
    worker carries just enough state for one execution (``worker_id`` for log
    correlation) plus the shared Redis-backed dependencies.
    """

    def __init__(
        self,
        *,
        redis,
        registry: RunRegistry,
        events: RunEvents,
        control: RunControl,
        queue: RunQueue,
        worker_id: str | None = None,
    ):
        self.redis = redis
        self.registry = registry
        self.events = events
        self.control = control
        self.queue = queue
        self.worker_id = worker_id or f"{socket.gethostname()}-{uuid4().hex[:8]}"

    # ---- per-run pipeline ----

    async def _execute(self, run_id: UUID) -> None:
        logger.info("worker %s dequeued run %s", self.worker_id, run_id)
        record = await self.registry.get(run_id)
        if record is None:
            logger.warning("run %s missing from registry, skipping", run_id)
            return
        if record.status != RunState.PENDING:
            logger.warning(
                "run %s is %s (not pending), skipping", run_id, record.status
            )
            return

        # Build the runtime in a short-lived DB session. The session is closed
        # before we open the long-lived checkpointer connection so we don't pin
        # a Postgres pool slot for the whole run.
        logger.debug("run %s: building runtime", run_id)
        async with AsyncSessionLocal() as db:
            try:
                thread = await ThreadService(db).get_thread(record.thread_id)
                runtime = await AgentRuntime.build(thread=thread, db=db)
            finally:
                await db.commit()

        payload = await load_input(self.redis, run_id)
        logger.debug("run %s: opening checkpointer", run_id)

        async with AsyncPostgresSaver.from_conn_string(
            get_psycopg_conn_string()
        ) as checkpointer:
            graph = runtime._build_agent(checkpointer)
            stream_input = runtime._resolve_input(
                payload.get("input"), payload.get("command")
            )
            config = await runtime._resolve_config(
                graph,
                payload.get("trigger"),
                payload.get("config_overrides"),
            )

            await self._supervise(
                run_id=run_id,
                record=record,
                graph=graph,
                stream_input=stream_input,
                config=config,
            )

    async def _supervise(
        self,
        *,
        run_id: UUID,
        record,
        graph,
        stream_input,
        config: dict,
    ) -> None:
        # PENDING -> RUNNING
        try:
            new_status = transition(record.status, RunEvent.DEQUEUED)
        except IllegalTransitionError:
            logger.warning("cannot transition %s from %s", run_id, record.status)
            return
        record = await self.registry.update(
            run_id,
            status=new_status,
            started_at=utcnow(),
            worker_id=self.worker_id,
        )

        astream_task = asyncio.create_task(
            self._consume(run_id, graph, stream_input, config),
            name=f"astream:{run_id}",
        )
        cancel_task = asyncio.create_task(
            self.control.watch_cancel(run_id),
            name=f"cancel-watch:{run_id}",
        )
        heartbeat_task = asyncio.create_task(
            self._heartbeat_loop(run_id),
            name=f"heartbeat:{run_id}",
        )

        cancel_reason: CancellationReason | None = None
        run_error: BaseException | None = None
        try:
            done, _pending = await asyncio.wait(
                {astream_task, cancel_task},
                return_when=asyncio.FIRST_COMPLETED,
            )
            if cancel_task in done:
                cancel_reason = cancel_task.result()
                astream_task.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await astream_task
            else:
                cancel_task.cancel()
                exc = astream_task.exception()
                if exc is not None:
                    run_error = exc
        finally:
            heartbeat_task.cancel()
            cancel_task.cancel()
            with contextlib.suppress(BaseException):
                await heartbeat_task
            with contextlib.suppress(BaseException):
                await cancel_task

        # asyncio.shield: even if the worker itself is being torn down (e.g.
        # SIGTERM during shutdown), the patch + final-event writes get to run.
        await asyncio.shield(
            self._finalise(
                run_id=run_id,
                record=record,
                graph=graph,
                config=config,
                cancel_reason=cancel_reason,
                run_error=run_error,
            )
        )

    # ---- supervised pieces ----

    async def _consume(
        self,
        run_id: UUID,
        graph,
        stream_input,
        config: dict,
    ) -> None:
        """Iterate ``graph.astream`` and append every chunk to the event stream.

        The adapter produces SSE-encoded strings; we wrap each in an envelope
        so the consumer can distinguish stream chunks from terminal events.
        """
        adapter = LangGraphStreamAdapter(subgraphs=True)
        langchain_stream = graph.astream(
            stream_input,
            config=config,
            stream_mode=["messages", "values", "updates"],
            subgraphs=True,
        )
        first = True
        async for chunk in adapter.stream(langchain_stream):
            if first:
                logger.info("run %s: first chunk emitted", run_id)
                first = False
            stream_id = await self.events.append(
                run_id, {"type": "chunk", "data": chunk}
            )
            await self.redis.hset(
                f"run:{run_id}",
                mapping={"last_event_id": stream_id, "heartbeat_at": utcnow().isoformat()},
            )
        if first:
            logger.warning("run %s: astream completed without emitting any chunks", run_id)

    async def _heartbeat_loop(self, run_id: UUID) -> None:
        try:
            while True:
                await asyncio.sleep(HEARTBEAT_INTERVAL_SECONDS)
                await self.registry.heartbeat(run_id)
        except asyncio.CancelledError:
            return

    # ---- finalisation ----

    async def _finalise(
        self,
        *,
        run_id: UUID,
        record,
        graph,
        config: dict,
        cancel_reason: CancellationReason | None,
        run_error: BaseException | None,
    ) -> None:
        """Pick a terminal state, patch dangling tools if needed, emit ``end``."""
        try:
            if cancel_reason is not None:
                await self._patch_and_transition(
                    run_id=run_id,
                    record=record,
                    graph=graph,
                    config=config,
                    event=RunEvent.CANCELLED,
                    extras={"cancellation_reason": cancel_reason},
                )
            elif run_error is not None:
                await self._patch_and_transition(
                    run_id=run_id,
                    record=record,
                    graph=graph,
                    config=config,
                    event=RunEvent.ERRORED,
                    extras={
                        "error": {
                            "type": type(run_error).__name__,
                            "message": str(run_error),
                        }
                    },
                )
            else:
                await self._finalise_clean(run_id, record, graph, config)
        finally:
            await self.control.clear(run_id)
            await self.registry.clear_active_if_match(record.thread_id, run_id)

    async def _finalise_clean(self, run_id: UUID, record, graph, config: dict) -> None:
        """astream returned without raising. Determine if we landed on an interrupt."""
        state = await graph.aget_state(config)
        interrupted = bool(
            state and state.tasks and any(t.interrupts for t in state.tasks)
        )
        if interrupted:
            interrupt_payload = self._extract_interrupt(state)
            new_status = transition(record.status, RunEvent.INTERRUPT_EMITTED)
            await self.registry.update(
                run_id,
                status=new_status,
                interrupt=interrupt_payload,
            )
            await self.events.append(
                run_id, {"type": "interrupt", "value": interrupt_payload}
            )
            await self._emit_end(run_id, new_status)
        else:
            new_status = transition(record.status, RunEvent.COMPLETED)
            await self.registry.update(
                run_id,
                status=new_status,
                completed_at=utcnow(),
            )
            await self._emit_end(run_id, new_status)

    async def _patch_and_transition(
        self,
        *,
        run_id: UUID,
        record,
        graph,
        config: dict,
        event: RunEvent,
        extras: dict[str, Any],
    ) -> None:
        try:
            patched = await patch_dangling_tool_calls(graph, config)
            if patched:
                logger.info("patched %d dangling tool calls for run %s", patched, run_id)
        except Exception:  # noqa: BLE001
            logger.exception("patch_dangling_tool_calls failed for run %s", run_id)

        new_status = transition(record.status, event)
        await self.registry.update(
            run_id,
            status=new_status,
            completed_at=utcnow(),
            **extras,
        )
        await self._emit_end(run_id, new_status, extras=extras)

    async def _emit_end(
        self,
        run_id: UUID,
        status: RunState,
        *,
        extras: dict[str, Any] | None = None,
    ) -> None:
        payload: dict[str, Any] = {"type": "end", "status": status.value}
        if extras:
            payload.update({k: v for k, v in extras.items() if v is not None})
        await self.events.append(run_id, payload)
        if is_terminal(status):
            await self.events.expire(run_id)

    @staticmethod
    def _extract_interrupt(state) -> dict[str, Any] | None:
        for task in state.tasks or []:
            for interrupt in task.interrupts or []:
                if hasattr(interrupt, "value"):
                    return {"value": interrupt.value}
                return {"value": interrupt}
        return None


# --- dispatcher -------------------------------------------------------------


class RunDispatcher:
    """One BRPOP loop, task-per-run, semaphore-capped.

    Replaces the previous "N persistent workers each BRPOP'ing" shape, which
    capped concurrency at ``N`` and held ``N`` Redis connections at idle.
    Here a single coroutine pops runs and ``asyncio.create_task``s execution;
    a semaphore (size ``max_concurrent_runs``) caps how many run concurrently.

    Behaviour at saturation:
    - All semaphore slots in use → the dispatcher blocks on ``acquire()``,
      stops popping new runs from the queue.
    - Other Cloud Run instances continue popping the same queue, so the
      cluster keeps making progress.
    - When a local slot frees, the dispatcher resumes popping immediately.

    Behaviour at idle:
    - One blocked BRPOP, zero in-flight tasks. (vs N idle BRPOPs before.)
    """

    def __init__(
        self,
        *,
        redis,
        max_concurrent_runs: int,
        instance_id: str | None = None,
    ):
        self.redis = redis
        self.max_concurrent_runs = max_concurrent_runs
        self.instance_id = (
            instance_id or f"{socket.gethostname()}-{uuid4().hex[:8]}"
        )
        self.registry = RunRegistry(redis)
        self.events = RunEvents(redis)
        self.control = RunControl(redis)
        self.queue = RunQueue(redis)
        self._semaphore = asyncio.Semaphore(max_concurrent_runs)
        self._in_flight: set[asyncio.Task] = set()
        self._seq = 0

    async def run_forever(self, *, stop_event: asyncio.Event) -> None:
        logger.info(
            "starting run dispatcher: instance=%s max_concurrent=%d",
            self.instance_id,
            self.max_concurrent_runs,
        )
        try:
            while not stop_event.is_set():
                try:
                    run_id = await self.queue.dequeue(timeout_seconds=2)
                except Exception:  # noqa: BLE001 — never crash the loop
                    logger.exception("dequeue failed")
                    await asyncio.sleep(1)
                    continue
                if run_id is None:
                    continue

                # Block here when saturated. While we wait, no other dequeue
                # happens *from this instance* — but the run is still in the
                # queue, so peer instances are free to pop it.
                await self._semaphore.acquire()
                if stop_event.is_set():
                    # We took a run while shutting down — push it back so a
                    # surviving instance picks it up. ``LPUSH`` keeps queue
                    # ordering intact since we ``BRPOP`` from the other end.
                    await self.queue.enqueue(run_id)
                    self._semaphore.release()
                    break

                self._seq += 1
                worker = RunWorker(
                    redis=self.redis,
                    registry=self.registry,
                    events=self.events,
                    control=self.control,
                    queue=self.queue,
                    worker_id=f"{self.instance_id}-{self._seq}",
                )
                task = asyncio.create_task(
                    self._execute_one(worker, run_id), name=f"run:{run_id}"
                )
                self._in_flight.add(task)
                task.add_done_callback(self._in_flight.discard)
        finally:
            await self._drain()
            logger.info(
                "run dispatcher stopped: instance=%s (drained %d in-flight)",
                self.instance_id,
                len(self._in_flight),
            )

    async def _execute_one(self, worker: RunWorker, run_id: UUID) -> None:
        try:
            await worker._execute(run_id)
        except Exception:  # noqa: BLE001 — never let a single run kill the pool
            logger.exception("execute %s failed", run_id)
        finally:
            self._semaphore.release()

    async def _drain(self) -> None:
        """Wait for in-flight runs to finish their post-cancel cleanup.

        On SIGTERM, the lifespan flips ``stop_event`` and the dispatcher loop
        exits. Already-spawned tasks need to settle so ``patch_dangling_tool_calls``
        gets to write its synthetic ToolMessages (worker uses ``asyncio.shield``
        around that path). Bounded by the Cloud Run grace period; anything that
        doesn't finish in time will be picked up by the reaper on the next
        instance.
        """
        if not self._in_flight:
            return
        logger.info("draining %d in-flight runs", len(self._in_flight))
        await asyncio.gather(*self._in_flight, return_exceptions=True)


async def run_dispatcher(
    *,
    redis,
    max_concurrent_runs: int,
    stop_event: asyncio.Event,
) -> None:
    """Lifespan entrypoint. Equivalent to ``RunDispatcher(...).run_forever()``."""
    dispatcher = RunDispatcher(
        redis=redis,
        max_concurrent_runs=max_concurrent_runs,
    )
    await dispatcher.run_forever(stop_event=stop_event)


__all__ = [
    "RunDispatcher",
    "RunWorker",
    "load_input",
    "run_dispatcher",
    "store_input",
]


# Suppress "imported but not used" for AsyncIterator (kept for type clarity in
# future API additions).
_ = AsyncIterator
