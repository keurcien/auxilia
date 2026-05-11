"""Unit tests for RunWorker's finalisation branches.

We don't spin up the full pipeline (DB session + AgentRuntime + Postgres
checkpointer) here — those are covered by integration tests once the test
infrastructure lands. The branches we *can* exercise in isolation are the
ones that decide a terminal state given the supervisor's collected context.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

import pytest

from app.agents.runs.control import RunControl
from app.agents.runs.events import RunEvents
from app.agents.runs.queue import RunQueue
from app.agents.runs.registry import RunRegistry
from app.agents.runs.state import (
    CancellationReason,
    MultitaskStrategy,
    RunRecord,
    RunState,
    utcnow,
)
from app.agents.runs.worker import RunWorker


# --- minimal stub graph ----------------------------------------------------


@dataclass
class _FakeInterrupt:
    value: Any


@dataclass
class _FakeTask:
    interrupts: list[_FakeInterrupt] = field(default_factory=list)


@dataclass
class _FakeState:
    tasks: list[_FakeTask] = field(default_factory=list)
    values: dict[str, Any] = field(default_factory=dict)


class _StubGraph:
    """The narrow surface ``RunWorker._finalise*`` actually uses."""

    def __init__(self, *, interrupted: bool = False, messages: list | None = None):
        self._interrupted = interrupted
        self._messages = messages or []
        self.update_calls: list[dict] = []

    async def aget_state(self, _config):
        if self._interrupted:
            return _FakeState(
                tasks=[_FakeTask(interrupts=[_FakeInterrupt(value="approve?")])],
                values={"messages": self._messages},
            )
        return _FakeState(tasks=[], values={"messages": self._messages})

    async def aupdate_state(self, _config, values):
        self.update_calls.append(values)


# --- helpers ----------------------------------------------------------------


def _record(status: RunState = RunState.RUNNING) -> RunRecord:
    now = utcnow()
    return RunRecord(
        id=uuid4(),
        thread_id="thread-1",
        user_id=uuid4(),
        agent_id=uuid4(),
        status=status,
        multitask_strategy=MultitaskStrategy.REJECT,
        created_at=now,
        updated_at=now,
    )


def _worker(redis) -> RunWorker:
    return RunWorker(
        redis=redis,
        registry=RunRegistry(redis),
        events=RunEvents(redis),
        control=RunControl(redis),
        queue=RunQueue(redis),
        worker_id="test-worker",
    )


async def _drain_events(redis, run_id) -> list[dict]:
    """Read all events on the run stream without blocking forever."""
    raw = await redis.xrange(f"run:{run_id}:events")
    out: list[dict] = []
    for _id, fields in raw:
        data = fields.get("data") or fields.get(b"data")
        if isinstance(data, bytes):
            data = data.decode()
        if data is None:
            continue
        import json
        out.append(json.loads(data))
    return out


@pytest.fixture
def config():
    return {"configurable": {"thread_id": "thread-1"}}


# --- tests -----------------------------------------------------------------


@pytest.mark.asyncio
class TestFinaliseClean:
    async def test_completed_run_lands_success(self, redis, config):
        worker = _worker(redis)
        record = _record(RunState.RUNNING)
        await worker.registry.create(record)

        await worker._finalise_clean(record.id, record, _StubGraph(), config)

        loaded = await worker.registry.get(record.id)
        assert loaded.status is RunState.SUCCESS
        assert loaded.completed_at is not None

        events = await _drain_events(redis, record.id)
        assert events[-1] == {"type": "end", "status": "success"}

    async def test_interrupt_lands_interrupted(self, redis, config):
        worker = _worker(redis)
        record = _record(RunState.RUNNING)
        await worker.registry.create(record)

        await worker._finalise_clean(
            record.id, record, _StubGraph(interrupted=True), config
        )

        loaded = await worker.registry.get(record.id)
        assert loaded.status is RunState.INTERRUPTED
        assert loaded.interrupt == {"value": "approve?"}

        events = await _drain_events(redis, record.id)
        assert any(e.get("type") == "interrupt" for e in events)
        assert events[-1] == {"type": "end", "status": "interrupted"}


@pytest.mark.asyncio
class TestPatchAndTransition:
    async def test_cancel_path_writes_reason(self, redis, config):
        worker = _worker(redis)
        record = _record(RunState.RUNNING)
        await worker.registry.create(record)

        await worker._patch_and_transition(
            run_id=record.id,
            record=record,
            graph=_StubGraph(),
            config=config,
            event=__import__("app.agents.runs.state", fromlist=["RunEvent"]).RunEvent.CANCELLED,
            extras={"cancellation_reason": CancellationReason.USER},
        )

        loaded = await worker.registry.get(record.id)
        assert loaded.status is RunState.CANCELLED
        assert loaded.cancellation_reason is CancellationReason.USER

        events = await _drain_events(redis, record.id)
        assert events[-1]["status"] == "cancelled"
        assert events[-1]["cancellation_reason"] == CancellationReason.USER

    async def test_error_path_writes_error_dict(self, redis, config):
        worker = _worker(redis)
        record = _record(RunState.RUNNING)
        await worker.registry.create(record)

        from app.agents.runs.state import RunEvent

        await worker._patch_and_transition(
            run_id=record.id,
            record=record,
            graph=_StubGraph(),
            config=config,
            event=RunEvent.ERRORED,
            extras={"error": {"type": "RuntimeError", "message": "boom"}},
        )

        loaded = await worker.registry.get(record.id)
        assert loaded.status is RunState.ERROR
        assert loaded.error == {"type": "RuntimeError", "message": "boom"}

    async def test_dangling_calls_get_patched(self, redis, config):
        from langchain_core.messages import AIMessage

        worker = _worker(redis)
        record = _record(RunState.RUNNING)
        await worker.registry.create(record)

        graph = _StubGraph(
            messages=[
                AIMessage(
                    content="",
                    tool_calls=[{"name": "read", "args": {}, "id": "tc1"}],
                )
            ]
        )

        from app.agents.runs.state import RunEvent

        await worker._patch_and_transition(
            run_id=record.id,
            record=record,
            graph=graph,
            config=config,
            event=RunEvent.CANCELLED,
            extras={"cancellation_reason": CancellationReason.USER},
        )

        # patch_dangling_tool_calls should have called aupdate_state with one
        # synthetic ToolMessage for tc1.
        assert len(graph.update_calls) == 1
        patched = graph.update_calls[0]["messages"]
        assert len(patched) == 1
        assert patched[0].tool_call_id == "tc1"


@pytest.mark.asyncio
class TestReaperThresholds:
    """Regression: PENDING runs must not be reaped 30s after creation just
    because no worker has dequeued yet. They're queued, not orphaned."""

    async def test_pending_run_under_long_threshold_is_skipped(self, redis):
        from dataclasses import replace as _replace
        from datetime import timedelta as _td

        from app.agents.runs.reaper import RunReaper

        reg = RunRegistry(redis)
        # 5 minutes old PENDING — below the 10-minute pending threshold;
        # the worker just hasn't gotten to it yet.
        rec = _record(RunState.PENDING)
        rec = _replace(rec, created_at=rec.created_at - _td(minutes=5))
        await reg.create(rec)

        reaper = RunReaper(redis)
        reaped = await reaper.tick()
        assert reaped == 0
        assert (await reg.get(rec.id)).status is RunState.PENDING

    async def test_running_run_with_stale_heartbeat_is_reaped(self, redis):
        from dataclasses import replace as _replace
        from datetime import timedelta as _td

        from app.agents.runs.reaper import RunReaper

        reg = RunRegistry(redis)
        rec = _record(RunState.RUNNING)
        # Started 2 minutes ago, no heartbeat in that time.
        rec = _replace(
            rec,
            started_at=rec.created_at - _td(minutes=2),
            heartbeat_at=rec.created_at - _td(minutes=2),
        )
        await reg.create(rec)

        reaper = RunReaper(redis)
        reaped = await reaper.tick()
        assert reaped == 1
        assert (await reg.get(rec.id)).status is RunState.ERROR


@pytest.mark.asyncio
class TestDispatcher:
    """The dispatcher pops runs and runs up to ``max_concurrent`` concurrently.

    We stub ``RunWorker._execute`` so we don't need a real DB or LangGraph —
    only the concurrency control is under test here.
    """

    async def _patched_dispatcher(self, redis, monkeypatch, max_concurrent: int):
        from app.agents.runs.worker import RunDispatcher, RunWorker

        active = 0
        peak = 0
        held: list[asyncio.Event] = []

        async def fake_execute(self, _run_id):  # noqa: ARG001
            nonlocal active, peak
            active += 1
            peak = max(peak, active)
            evt = asyncio.Event()
            held.append(evt)
            try:
                await evt.wait()
            finally:
                active -= 1

        monkeypatch.setattr(RunWorker, "_execute", fake_execute)
        dispatcher = RunDispatcher(
            redis=redis,
            max_concurrent_runs=max_concurrent,
            instance_id="test",
        )
        return dispatcher, held, lambda: peak

    async def test_caps_concurrent_executions_at_semaphore_limit(
        self, redis, monkeypatch
    ):
        dispatcher, held, peak = await self._patched_dispatcher(
            redis, monkeypatch, max_concurrent=3
        )

        # Enqueue 5 runs; cap is 3, so only 3 should run at once.
        for _ in range(5):
            await dispatcher.queue.enqueue(uuid4())

        stop = asyncio.Event()
        loop_task = asyncio.create_task(dispatcher.run_forever(stop_event=stop))

        # Wait until the dispatcher has hit the cap.
        for _ in range(50):
            await asyncio.sleep(0.02)
            if peak() >= 3:
                break
        assert peak() == 3, f"expected peak=3 (cap), got {peak()}"

        # Release everything; dispatcher drains the remaining 2.
        for e in list(held):
            e.set()
        # Give the loop time to dequeue the rest.
        for _ in range(50):
            await asyncio.sleep(0.02)
            if len(held) >= 5:
                break
        for e in list(held):
            e.set()

        stop.set()
        await asyncio.wait_for(loop_task, timeout=5)
        assert len(held) == 5  # all 5 runs eventually executed

    async def test_re_enqueues_run_when_stopping_after_pop(
        self, redis, monkeypatch
    ):
        """If we pop a run but the stop signal fires before we spawn it, the
        run is pushed back onto the queue so another instance can pick it up.

        Simulated here by acquiring the semaphore externally so the dispatcher
        blocks at ``await semaphore.acquire()``, then setting the stop event.
        """
        from app.agents.runs.worker import RunDispatcher, RunWorker

        async def fake_execute(self, _run_id):  # noqa: ARG001
            return None

        monkeypatch.setattr(RunWorker, "_execute", fake_execute)

        dispatcher = RunDispatcher(
            redis=redis, max_concurrent_runs=1, instance_id="test"
        )
        # Saturate the semaphore so the dispatcher will block after the pop.
        await dispatcher._semaphore.acquire()
        await dispatcher.queue.enqueue(uuid4())

        stop = asyncio.Event()
        loop_task = asyncio.create_task(dispatcher.run_forever(stop_event=stop))

        # Give the loop time to BRPOP and start waiting on the semaphore.
        await asyncio.sleep(0.5)
        stop.set()
        dispatcher._semaphore.release()  # unblock so the loop sees stop_event

        await asyncio.wait_for(loop_task, timeout=5)

        # The popped run should be back on the queue, unprocessed.
        assert await dispatcher.queue.length() == 1


@pytest.mark.asyncio
class TestEmitEnd:
    async def test_terminal_status_sets_stream_ttl(self, redis):
        worker = _worker(redis)
        rid = uuid4()
        await worker._emit_end(rid, RunState.SUCCESS)
        ttl = await redis.ttl(f"run:{rid}:events")
        assert ttl > 0

    async def test_non_terminal_status_no_ttl(self, redis):
        worker = _worker(redis)
        rid = uuid4()
        await worker._emit_end(rid, RunState.INTERRUPTED)
        # Stream key may exist (we appended) but should have no TTL set.
        ttl = await redis.ttl(f"run:{rid}:events")
        assert ttl == -1
