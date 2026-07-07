import asyncio
from uuid import uuid4

import pytest

import app.agents.runs.worker as worker_mod
from app.agents.runs.models import RunDB
from app.agents.runs.service import RunService
from app.agents.runs.settings import run_settings
from app.agents.runs.state import RunStatus
from app.agents.runs.worker import RunWorker


pytestmark = pytest.mark.usefixtures("run_db")


class _FakeAgent:
    """Stands in for the real Agent — yields SSE without touching an LLM."""

    @classmethod
    async def build(cls, *, thread, db):
        return cls()

    async def stream(self, **kwargs):
        yield 'event: messages\ndata: {"t": 1}\n\n'
        yield 'event: messages\ndata: {"t": 2}\n\n'


class _ErrorAgent(_FakeAgent):
    async def stream(self, **kwargs):
        yield 'event: error\ndata: {"message": "boom"}\n\n'


class _FakeSession:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def get(self, model, pk):
        return object()  # a non-None ThreadDB stand-in


@pytest.fixture
def patch_agent(monkeypatch):
    monkeypatch.setattr(worker_mod, "Agent", _FakeAgent)
    monkeypatch.setattr(worker_mod, "AsyncSessionLocal", lambda: _FakeSession())

    async def _no_interrupt(*_):
        return False

    monkeypatch.setattr(RunWorker, "_is_interrupted", _no_interrupt)


async def _create_and_claim(service: RunService, **kwargs) -> RunDB:
    """Create a run and claim it, as the dispatcher would before `worker.run`."""
    kwargs.setdefault("user_id", str(uuid4()))
    record = await service.create(**kwargs)
    claimed = await service.claim_next()
    assert claimed is not None and claimed.id == record.id
    return claimed


@pytest.mark.usefixtures("patch_agent")
async def test_worker_runs_to_success_and_frees_thread(redis):
    service = RunService(redis)
    record = await _create_and_claim(
        service,
        thread_id="t1",
        input={"messages": [{"type": "human", "content": "hi"}]},
    )
    await RunWorker(redis).run(record)

    assert (await service.get(record.id)).status == RunStatus.success
    chunks = [c async for c in service.stream(record.id, "0")]
    assert any('"t": 1' in c for c in chunks)
    assert any("event: end" in c for c in chunks)
    assert await service.get_active("t1") is None


@pytest.mark.usefixtures("patch_agent")
async def test_worker_marks_error_on_error_event(redis, monkeypatch):
    monkeypatch.setattr(worker_mod, "Agent", _ErrorAgent)
    service = RunService(redis)
    record = await _create_and_claim(service, thread_id="t2", input={"messages": []})
    await RunWorker(redis).run(record)
    assert (await service.get(record.id)).status == RunStatus.error


@pytest.mark.usefixtures("patch_agent")
async def test_worker_marks_error_when_agent_raises(redis, monkeypatch):
    class _RaisingAgent(_FakeAgent):
        async def stream(self, **kwargs):
            raise RuntimeError("model exploded")
            yield  # pragma: no cover — makes this an async generator

    monkeypatch.setattr(worker_mod, "Agent", _RaisingAgent)
    service = RunService(redis)
    record = await _create_and_claim(service, thread_id="t2b", input={"messages": []})
    await RunWorker(redis).run(record)
    back = await service.get(record.id)
    assert back.status == RunStatus.error
    assert "model exploded" in back.error


@pytest.mark.usefixtures("patch_agent")
async def test_worker_unwraps_exception_groups(redis, monkeypatch):
    """A TaskGroup-wrapped failure (e.g. MCP OAuth) must store the root cause,
    not "unhandled errors in a TaskGroup"."""

    class _GroupRaisingAgent(_FakeAgent):
        async def stream(self, **kwargs):
            raise ExceptionGroup(
                "unhandled errors in a TaskGroup",
                [ExceptionGroup("nested", [RuntimeError("oauth registration 404")])],
            )
            yield  # pragma: no cover — makes this an async generator

    monkeypatch.setattr(worker_mod, "Agent", _GroupRaisingAgent)
    service = RunService(redis)
    record = await _create_and_claim(service, thread_id="t2c", input={"messages": []})
    await RunWorker(redis).run(record)
    back = await service.get(record.id)
    assert back.status == RunStatus.error
    assert back.error == "oauth registration 404"


@pytest.mark.usefixtures("patch_agent")
async def test_worker_detects_interrupt(redis, monkeypatch):
    async def _interrupted(*_):
        return True

    monkeypatch.setattr(RunWorker, "_is_interrupted", _interrupted)
    service = RunService(redis)
    record = await _create_and_claim(service, thread_id="t3", input={"messages": []})
    await RunWorker(redis).run(record)
    assert (await service.get(record.id)).status == RunStatus.interrupted


@pytest.mark.usefixtures("patch_agent")
async def test_cancel_mid_run_stops_and_frees_thread(redis, monkeypatch):
    started = asyncio.Event()

    class _SlowAgent(_FakeAgent):
        async def stream(self, **kwargs):
            yield 'event: messages\ndata: {"t": 1}\n\n'
            started.set()
            await asyncio.sleep(10)  # long-running; cancel should interrupt here

    monkeypatch.setattr(worker_mod, "Agent", _SlowAgent)
    monkeypatch.setattr(run_settings, "cancel_poll_seconds", 0.02)

    service = RunService(redis)
    record = await _create_and_claim(service, thread_id="t5", input={"messages": []})
    run_task = asyncio.create_task(RunWorker(redis).run(record))
    await asyncio.wait_for(started.wait(), timeout=5)

    await service.cancel(record.id)
    await asyncio.wait_for(run_task, timeout=5)

    assert (await service.get(record.id)).status == RunStatus.cancelled
    assert await service.get_active("t5") is None


@pytest.mark.usefixtures("patch_agent")
async def test_wait_for_terminal_returns_terminal_record(redis):
    service = RunService(redis)
    record = await _create_and_claim(service, thread_id="t6", input={"messages": []})
    await RunWorker(redis).run(record)
    # Run already finished; wait_for_terminal drains the log and returns at once.
    final = await service.wait_for_terminal(record.id)
    assert final.status == RunStatus.success


async def test_worker_forwards_output_schema_to_agent(redis, monkeypatch):
    captured: dict = {}

    class _RecordingAgent(_FakeAgent):
        async def stream(self, **kwargs):
            captured.update(kwargs)
            yield "event: messages\ndata: {}\n\n"

    monkeypatch.setattr(worker_mod, "Agent", _RecordingAgent)
    monkeypatch.setattr(worker_mod, "AsyncSessionLocal", lambda: _FakeSession())

    async def _no_interrupt(*_):
        return False

    monkeypatch.setattr(RunWorker, "_is_interrupted", _no_interrupt)

    service = RunService(redis)
    schema = {"type": "object"}
    record = await _create_and_claim(
        service, thread_id="t7", input={"messages": []}, output_schema=schema
    )
    await RunWorker(redis).run(record)
    assert captured.get("output_schema") == schema


@pytest.mark.usefixtures("patch_agent")
async def test_worker_invokes_delivery_consumer_for_delivery_records(redis):
    seen: list[str] = []

    class _Consumer:
        def __init__(self, record):
            self.record = record

        async def run(self):
            # The sentinel is published by finalize before the worker awaits us,
            # so a real consumer would drain the log here.
            seen.append(self.record.id)

    def factory(record):
        return _Consumer(record) if record.delivery else None

    service = RunService(redis)
    record = await _create_and_claim(
        service,
        thread_id="td1",
        input={"messages": []},
        delivery={"channel": "slack", "channel_id": "C"},
    )
    await RunWorker(redis, delivery_factory=factory).run(record)

    assert seen == [record.id]
    assert (await service.get(record.id)).status == RunStatus.success


@pytest.mark.usefixtures("patch_agent")
async def test_worker_skips_delivery_for_plain_records(redis):
    def factory(record):
        return None  # called, but returns None for pull runs

    service = RunService(redis)
    record = await _create_and_claim(service, thread_id="td2", input={"messages": []})
    await RunWorker(redis, delivery_factory=factory).run(record)

    assert (await service.get(record.id)).status == RunStatus.success


@pytest.mark.usefixtures("patch_agent")
async def test_worker_succeeds_when_delivery_factory_raises(redis):
    def factory(_record):
        raise RuntimeError("factory boom")

    service = RunService(redis)
    record = await _create_and_claim(
        service,
        thread_id="td4",
        input={"messages": []},
        delivery={"channel": "slack"},
    )
    await RunWorker(redis, delivery_factory=factory).run(record)

    # A factory crash must not abort the run before finalize/cleanup.
    assert (await service.get(record.id)).status == RunStatus.success
    assert await service.get_active("td4") is None


@pytest.mark.usefixtures("patch_agent")
async def test_worker_succeeds_when_delivery_consumer_crashes(redis):
    class _BoomConsumer:
        def __init__(self, record):
            pass

        async def run(self):
            raise RuntimeError("delivery boom")

    service = RunService(redis)
    record = await _create_and_claim(
        service,
        thread_id="td3",
        input={"messages": []},
        delivery={"channel": "slack"},
    )
    await RunWorker(redis, delivery_factory=_BoomConsumer).run(record)

    # Delivery is best-effort: a crash must not change the run's terminal status.
    assert (await service.get(record.id)).status == RunStatus.success


@pytest.mark.usefixtures("patch_agent")
async def test_worker_clears_liveness_key_on_finish(redis):
    from app.agents.runs.liveness import RunLiveness

    service = RunService(redis)
    record = await _create_and_claim(service, thread_id="t8", input={"messages": []})
    await RunWorker(redis).run(record)
    assert not await RunLiveness(record.id, redis).is_alive()
