import asyncio
from contextlib import suppress
from uuid import uuid4

import pytest

import app.agents.runs.worker as worker_mod
from app.agents.runs import keys
from app.agents.runs.events import RunEventStream
from app.agents.runs.liveness import DispatcherLiveness, RunLiveness
from app.agents.runs.models import RunDB
from app.agents.runs.service import RunService
from app.agents.runs.settings import run_settings
from app.agents.runs.state import RunStatus
from app.agents.runs.worker import RunDispatcher, RunWorker


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

    async def _authorized(*_):
        return False

    monkeypatch.setattr(RunWorker, "_is_interrupted", _no_interrupt)
    monkeypatch.setattr(worker_mod, "_mcp_unauthorized", _authorized)


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
    back = await service.get(record.id)
    assert back.status == RunStatus.error
    # The event log TTLs away; the record must keep the message for reloads.
    assert back.error == "boom"


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
async def test_worker_gates_unauthorized_mcp_before_building_agent(redis, monkeypatch):
    """Background-launched runs (trigger scanner, Slack) have no HTTP caller to
    receive a 401 — the worker must fail them fast with an actionable error
    instead of building the agent and dying inside the MCP session."""

    class _NeverBuiltAgent(_FakeAgent):
        @classmethod
        async def build(cls, *, thread, db):
            raise AssertionError("Agent.build must not run when MCP is unauthorized")

    gate_args: list = []

    async def _unauthorized(db, thread, user_id):
        gate_args.append(user_id)
        return True

    monkeypatch.setattr(worker_mod, "Agent", _NeverBuiltAgent)
    monkeypatch.setattr(worker_mod, "_mcp_unauthorized", _unauthorized)
    service = RunService(redis)
    record = await _create_and_claim(service, thread_id="t2c", input={"messages": []})
    await RunWorker(redis).run(record)
    back = await service.get(record.id)
    assert back.status == RunStatus.error
    assert "MCP authorization required" in back.error
    # Probing the wrong identity would authorize against the wrong user.
    assert gate_args == [str(record.user_id)]


async def test_mcp_unauthorized_delegates_to_the_http_preflight(monkeypatch):
    """One definition of "unauthorized" for every launch path: the helper is
    True exactly when the HTTP gate would 401."""
    from types import SimpleNamespace

    thread = SimpleNamespace(agent_id="a1")
    calls: list = []

    async def _blocked(db, agent_id, user_id):
        calls.append((agent_id, user_id))
        return "https://auth.example"

    async def _passes(db, agent_id, user_id):
        return None

    monkeypatch.setattr(RunService, "required_oauth_url", _blocked)
    assert await worker_mod._mcp_unauthorized(None, thread, "u1") is True
    assert calls == [("a1", "u1")]

    monkeypatch.setattr(RunService, "required_oauth_url", _passes)
    assert await worker_mod._mcp_unauthorized(None, thread, "u1") is False


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


@pytest.mark.usefixtures("patch_agent")
async def test_worker_forwards_output_schema_to_agent(redis, monkeypatch):
    captured: dict = {}

    class _RecordingAgent(_FakeAgent):
        async def stream(self, **kwargs):
            captured.update(kwargs)
            yield "event: messages\ndata: {}\n\n"

    monkeypatch.setattr(worker_mod, "Agent", _RecordingAgent)

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


# ---------------------------------------------------------------------------
# §5.1 — the heartbeat must survive a transient Redis error
# ---------------------------------------------------------------------------


async def test_heartbeat_survives_a_failing_stamp(redis, monkeypatch, until):
    """One transient error used to kill this loop silently. Liveness then
    expired and the reaper finalized a healthy streaming run as `error`."""
    monkeypatch.setattr(run_settings, "heartbeat_interval_seconds", 0)
    liveness = RunLiveness("r-hb", redis)
    events = RunEventStream("r-hb", redis)
    calls = 0

    async def _flaky(**_):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise ConnectionError("redis blipped")

    monkeypatch.setattr(liveness, "stamp", _flaky)
    task = asyncio.create_task(RunWorker(redis)._heartbeat(liveness, events))

    async def _ticked_again() -> bool:
        return calls >= 3

    try:
        # The regression is the loop dying at call 1; reaching call 3 proves it
        # kept ticking past the failure.
        await until(_ticked_again, what="the heartbeat to tick again")
    finally:
        task.cancel()


async def test_heartbeat_refreshes_the_event_log_ttl(redis, monkeypatch, until):
    """A run longer than the safety TTL must not expire its own live stream."""
    monkeypatch.setattr(run_settings, "heartbeat_interval_seconds", 0)
    events = RunEventStream("r-hb2", redis)
    await events.publish("a")
    await redis.expire(events._key, 5)

    task = asyncio.create_task(
        RunWorker(redis)._heartbeat(RunLiveness("r-hb2", redis), events)
    )

    async def _ttl_pushed_out() -> bool:
        return await redis.ttl(events._key) > 5

    try:
        await until(_ttl_pushed_out, what="the heartbeat to push the event-log TTL out")
    finally:
        task.cancel()


# ---------------------------------------------------------------------------
# §5.2 — the dispatcher announces cluster liveness independently of its claim
# loop, which blocks on a saturated semaphore
# ---------------------------------------------------------------------------


@pytest.fixture
def isolated_registry(monkeypatch):
    """`RunDispatcher` registers its health in the process-wide registry on
    construction, and a cancelled task never reaches the cleanup that marks it
    stopped — so without this, later tests (and /health) see a dispatcher that
    does not exist.

    Patching `app.background.registry` is enough only because registration goes
    through `register_loop()`, which resolves that global at call time. The
    first version of this fixture patched the attribute while `worker.py` held
    the registry object it had imported by value, so it isolated nothing —
    hence the seam.
    """
    from app.background import LoopRegistry

    registry = LoopRegistry()
    monkeypatch.setattr("app.background.registry", registry)
    return registry


async def test_the_isolated_registry_fixture_actually_isolates(
    redis, isolated_registry
):
    """Guards the fixture itself: it silently isolated nothing while `worker.py`
    used its own imported reference to the registry."""
    from app.background import registry as process_registry

    RunDispatcher(redis)

    assert [loop.name for loop in isolated_registry.loops] == ["run-dispatcher"]
    assert process_registry is isolated_registry


async def test_dispatcher_announces_liveness_while_saturated(
    redis, monkeypatch, until, isolated_registry
):
    """The claim loop blocks on `_semaphore.acquire()` when every slot is busy —
    precisely the backlog the reaper must not mistake for "nothing dispatching".
    So the announcement runs on its own timer."""
    monkeypatch.setattr(run_settings, "heartbeat_interval_seconds", 0)
    monkeypatch.setattr(run_settings, "worker_concurrency", 1)
    dispatcher = RunDispatcher(redis)
    await dispatcher._semaphore.acquire()  # saturate

    task = asyncio.create_task(dispatcher.run())
    try:
        await until(
            DispatcherLiveness(redis).any_alive,
            what="a saturated dispatcher to announce itself",
        )
    finally:
        await dispatcher.stop(drain_timeout=0.1)
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task


# ---------------------------------------------------------------------------
# §5.4 — ephemera must get a TTL even when the run row is gone
# ---------------------------------------------------------------------------


async def test_finalize_expires_ephemera_even_when_the_run_row_is_gone(redis):
    """A thread deleted mid-run CASCADEs its runs away, so the terminal UPDATE
    matches nothing. That used to skip `_expire_ephemera` entirely and leave the
    event log and control key in Redis for ever — and nothing will ever finalize
    this run again, so there is no second chance."""
    service = RunService(redis)
    run_id = "run-with-no-row"
    events = RunEventStream(run_id, redis)
    await events.publish("event: messages\ndata: 1\n\n")
    await redis.rpush(keys.run_control_key(run_id), "cancel")
    # The safety TTL from the first publish is the *other* half of this fix;
    # strip it so this test only observes what finalize does.
    await redis.persist(events._key)
    assert await redis.ttl(events._key) == -1
    assert await redis.ttl(keys.run_control_key(run_id)) == -1

    assert await service.finalize(run_id, RunStatus.error, error="orphaned") is None

    assert await redis.ttl(events._key) > 0
    assert await redis.ttl(keys.run_control_key(run_id)) > 0


# ---------------------------------------------------------------------------
# §3.4 — the worker publishes through the buffer, not chunk by chunk
# ---------------------------------------------------------------------------


@pytest.mark.usefixtures("patch_agent")
async def test_a_chatty_run_does_not_pay_a_round_trip_per_chunk(
    redis, monkeypatch, count_appends
):
    """The regression this guards is the worker quietly going back to
    `events.publish(sse)` in the stream loop: correct, fully tested by every
    other test here, and one Redis RTT per token."""

    class _ChattyAgent(_FakeAgent):
        async def stream(self, **kwargs):
            for i in range(50):
                yield f'event: messages\ndata: {{"t": {i}}}\n\n'

    monkeypatch.setattr(worker_mod, "Agent", _ChattyAgent)
    monkeypatch.setattr(run_settings, "event_buffer_max_chunks", 25)
    service = RunService(redis)
    record = await _create_and_claim(
        service, thread_id="t-chatty", input={"messages": []}
    )
    appends = count_appends(redis)

    await RunWorker(redis).run(record)

    # Only the end sentinel goes through a direct XADD; the 50 stream chunks
    # ride in pipelines.
    assert appends["xadd"] == 1
    chunks = [c async for c in service.stream(record.id, "0")]
    assert len([c for c in chunks if "event: messages" in c]) == 50


async def test_a_losing_finalize_does_not_disturb_a_live_run(redis):
    """A pending cancel (or a reaper sweep) can lose a race with a dispatcher
    claim: the guarded UPDATE matches nothing while the run is now `running`.
    Clearing its liveness key there fakes a dead worker for the reaper — the
    exact failure the two-sample rule exists to prevent."""
    service = RunService(redis)
    record = await service.create(
        thread_id="t-race", user_id=str(uuid4()), input={"messages": []}
    )
    claimed = await service.claim_next()
    assert claimed is not None
    liveness = RunLiveness(record.id, redis)
    await liveness.stamp(ttl=60)

    # The reaper reaps a *pending* zombie; the dispatcher already claimed it.
    result = await service.finalize(
        record.id,
        RunStatus.error,
        error="Run was never dispatched.",
        expected=RunStatus.pending,
    )

    assert result.status == RunStatus.running  # untouched
    assert await liveness.is_alive() is True


async def test_an_already_terminal_finalize_still_expires_ephemera(redis):
    """The idempotent re-finalize (worker and reaper may both call it) must
    still leave the ephemera on a TTL."""
    service = RunService(redis)
    record = await service.create(
        thread_id="t-twice", user_id=str(uuid4()), input={"messages": []}
    )
    await service.claim_next()
    await service.finalize(record.id, RunStatus.success)
    await redis.persist(keys.run_events_key(record.id))

    await service.finalize(record.id, RunStatus.success)

    assert await redis.ttl(keys.run_events_key(record.id)) > 0


async def test_a_saturated_dispatcher_stays_healthy(
    redis, monkeypatch, until, isolated_registry
):
    """The regression: health used to be ticked by the claim loop, which blocks
    on the semaphore for the whole length of an agent turn. A fully occupied
    dispatcher went stale in about a minute, so /health returned 503 and the
    platform recycled a healthy, busy worker mid-run — worse than the failure
    /health exists to catch."""
    monkeypatch.setattr(run_settings, "heartbeat_interval_seconds", 0)
    monkeypatch.setattr(run_settings, "worker_concurrency", 1)
    dispatcher = RunDispatcher(redis)
    await dispatcher._semaphore.acquire()  # every slot busy on a long run

    task = asyncio.create_task(dispatcher.run())
    try:
        # Two ticks, so this cannot pass on the single mark_tick() in `run()`.
        ticks = []

        async def _ticked_twice() -> bool:
            ticks.append(dispatcher.health.last_tick_at)
            return len({t for t in ticks if t is not None}) >= 2

        await until(_ticked_twice, what="a saturated dispatcher to keep ticking health")
    finally:
        await dispatcher.stop(drain_timeout=0.1)
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task

    assert dispatcher.health.is_healthy() is True
