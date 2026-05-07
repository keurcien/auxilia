"""Unit tests for RunWorker's finalisation branches.

We don't spin up the full pipeline (DB session + AgentRuntime + Postgres
checkpointer) here — those are covered by integration tests once the test
infrastructure lands. The branches we *can* exercise in isolation are the
ones that decide a terminal state given the supervisor's collected context.
"""

from __future__ import annotations

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
