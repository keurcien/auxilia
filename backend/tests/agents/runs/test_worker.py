import asyncio

import pytest

import app.agents.runs.worker as worker_mod
from app.agents.runs.service import RunService
from app.agents.runs.settings import run_settings
from app.agents.runs.state import RunStatus
from app.agents.runs.worker import RunWorker
from app.exceptions import DomainValidationError


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


@pytest.mark.usefixtures("patch_agent")
async def test_worker_runs_to_success_and_releases_mutex(redis):
    service = RunService(redis)
    record = await service.create(
        thread_id="t1",
        user_id="u1",
        input={"messages": [{"type": "human", "content": "hi"}]},
    )
    await RunWorker(redis).run(record.id)

    assert (await service.get(record.id)).status == RunStatus.success
    chunks = [c async for c in service.stream(record.id, "0")]
    assert any('"t": 1' in c for c in chunks)
    assert any("event: end" in c for c in chunks)
    assert await service.get_active("t1") is None


@pytest.mark.usefixtures("patch_agent")
async def test_worker_marks_error_on_error_event(redis, monkeypatch):
    monkeypatch.setattr(worker_mod, "Agent", _ErrorAgent)
    service = RunService(redis)
    record = await service.create(thread_id="t2", user_id="u1", input={"messages": []})
    await RunWorker(redis).run(record.id)
    assert (await service.get(record.id)).status == RunStatus.error


@pytest.mark.usefixtures("patch_agent")
async def test_worker_detects_interrupt(redis, monkeypatch):
    async def _interrupted(*_):
        return True

    monkeypatch.setattr(RunWorker, "_is_interrupted", _interrupted)
    service = RunService(redis)
    record = await service.create(thread_id="t3", user_id="u1", input={"messages": []})
    await RunWorker(redis).run(record.id)
    assert (await service.get(record.id)).status == RunStatus.interrupted


@pytest.mark.usefixtures("patch_agent")
async def test_cancel_mid_run_stops_and_releases(redis, monkeypatch):
    class _SlowAgent(_FakeAgent):
        async def stream(self, **kwargs):
            yield 'event: messages\ndata: {"t": 1}\n\n'
            await asyncio.sleep(10)  # long-running; cancel should interrupt here

    monkeypatch.setattr(worker_mod, "Agent", _SlowAgent)
    monkeypatch.setattr(run_settings, "cancel_poll_seconds", 0.02)

    service = RunService(redis)
    record = await service.create(thread_id="t5", user_id="u1", input={"messages": []})
    run_task = asyncio.create_task(RunWorker(redis).run(record.id))

    for _ in range(200):  # wait until the worker marks it running
        await asyncio.sleep(0.01)
        if (await service.get(record.id)).status == RunStatus.running:
            break

    await service.cancel(record.id)
    await asyncio.wait_for(run_task, timeout=5)

    assert (await service.get(record.id)).status == RunStatus.cancelled
    assert await service.get_active("t5") is None


@pytest.mark.usefixtures("patch_agent")
async def test_wait_for_terminal_returns_terminal_record(redis):
    service = RunService(redis)
    record = await service.create(thread_id="t6", user_id="u1", input={"messages": []})
    await RunWorker(redis).run(record.id)
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
    record = await service.create(
        thread_id="t7", user_id="u1", input={"messages": []}, output_schema=schema
    )
    await RunWorker(redis).run(record.id)
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
    record = await service.create(
        thread_id="td1",
        user_id="u1",
        input={"messages": []},
        delivery={"channel": "slack", "channel_id": "C"},
    )
    await RunWorker(redis, delivery_factory=factory).run(record.id)

    assert seen == [record.id]
    assert (await service.get(record.id)).status == RunStatus.success


@pytest.mark.usefixtures("patch_agent")
async def test_worker_skips_delivery_for_plain_records(redis):
    seen: list[str] = []

    def factory(record):
        seen.append(record.id)  # called, but returns None for pull runs
        return None

    service = RunService(redis)
    record = await service.create(thread_id="td2", user_id="u1", input={"messages": []})
    await RunWorker(redis, delivery_factory=factory).run(record.id)

    assert (await service.get(record.id)).status == RunStatus.success


@pytest.mark.usefixtures("patch_agent")
async def test_worker_succeeds_when_delivery_consumer_crashes(redis):
    class _BoomConsumer:
        def __init__(self, record):
            pass

        async def run(self):
            raise RuntimeError("delivery boom")

    service = RunService(redis)
    record = await service.create(
        thread_id="td3",
        user_id="u1",
        input={"messages": []},
        delivery={"channel": "slack"},
    )
    await RunWorker(redis, delivery_factory=_BoomConsumer).run(record.id)

    # Delivery is best-effort: a crash must not change the run's terminal status.
    assert (await service.get(record.id)).status == RunStatus.success


async def test_create_rejects_when_thread_has_active_run(redis):
    service = RunService(redis)
    await service.registry.claim_active("t9", "other-run", ttl=30)
    with pytest.raises(DomainValidationError):
        await service.create(thread_id="t9", user_id="u1", input={})


async def test_create_rejects_both_input_and_command(redis):
    service = RunService(redis)
    with pytest.raises(DomainValidationError):
        await service.create(
            thread_id="tx",
            user_id="u1",
            input={"messages": []},
            command={"resume": "x"},
        )


async def test_cancel_pending_run_finalizes_immediately(redis):
    service = RunService(redis)
    record = await service.create(thread_id="t4", user_id="u1", input={})
    out = await service.cancel(record.id)
    assert out.status == RunStatus.cancelled
    assert await service.get_active("t4") is None
