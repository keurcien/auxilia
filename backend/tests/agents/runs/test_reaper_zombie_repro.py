"""Repro for "An error occurred. Worker stopped responding." on a healthy run.

The reaper's only evidence of a live worker is the `run:{id}:alive` Redis key.
When that key is missing on two consecutive sweeps (Redis eviction/restart, a
CPU-starved Cloud Run instance whose heartbeat task never gets scheduled, an
instance killed mid-run), the run is finalized `error` and the client receives
the terminal `lifecycle: failed` — the red box in the UI.

Nothing tells the *worker* about it. If the worker was in fact alive (starved,
not dead), it keeps streaming: it appends events to a log whose terminal entry
has already been written, keeps writing LangGraph checkpoints, and its own
`finalize(success)` at the end is discarded by the transition guard. The thread
therefore shows the error while a refresh (which hydrates from the checkpoint)
shows the agent "continued to produce tokens".

These tests pin the current behaviour; a fix (e.g. `finalize` pushing a cancel
onto the run's control channel so the zombie stops) inverts the last asserts.
"""

import asyncio
from datetime import UTC, datetime, timedelta

import pytest

import app.agents.runs.worker as worker_mod
from app.agents.runs import keys
from app.agents.runs.liveness import RunLiveness
from app.agents.runs.reaper import RunReaper
from app.agents.runs.service import RunService
from app.agents.runs.settings import run_settings
from app.agents.runs.state import RunStatus
from app.agents.runs.worker import RunWorker
from tests.agents.runs.test_worker import (  # noqa: F401 — patch_agent is a fixture
    _create_and_claim,
    _event,
    _FakeAgent,
    patch_agent,
)


pytestmark = pytest.mark.usefixtures("run_db", "patch_agent")


def _after_heartbeat_grace() -> datetime:
    # Same trick as test_reaper.py: SQLite stores naive UTC, `updated_at`
    # cannot be backdated, so move the reaper's "now" forward instead.
    return datetime.now(UTC).replace(tzinfo=None) + timedelta(
        seconds=run_settings.heartbeat_timeout_seconds + 60
    )


async def test_a_reaped_run_leaves_a_zombie_worker_streaming(redis, monkeypatch):
    started = asyncio.Event()
    finished = asyncio.Event()

    class _LongAgent(_FakeAgent):
        async def stream(self, **kwargs):
            yield _event(1)
            started.set()
            for n in range(2, 60):
                await asyncio.sleep(0.01)
                yield _event(n)
            finished.set()

    monkeypatch.setattr(worker_mod, "Agent", _LongAgent)
    monkeypatch.setattr(run_settings, "cancel_poll_seconds", 0.02)

    service = RunService(redis)
    record = await _create_and_claim(
        service, thread_id="t-zombie", input={"messages": []}
    )
    run_task = asyncio.create_task(RunWorker(redis).run(record))
    await asyncio.wait_for(started.wait(), timeout=5)

    # The worker is alive, but its evidence of life goes missing.
    liveness = RunLiveness(record.id, redis)
    reaper = RunReaper(redis)
    now = _after_heartbeat_grace()
    await liveness.clear()
    await reaper._reap_dead_running(now)  # first sweep: suspect
    await liveness.clear()
    await reaper._reap_dead_running(now)  # second sweep: reaped

    reaped = await service.get(record.id)
    assert reaped.status == RunStatus.error
    assert reaped.error == "Worker stopped responding."
    # The terminal `failed` entry is already in the log — this is what the
    # client renders as the red error box.
    entries = await redis.xrange(keys.run_events_key(record.id))
    end_positions = [i for i, (_, fields) in enumerate(entries) if "end" in fields]
    assert len(end_positions) == 1

    # ...and yet the worker was never told. It is still streaming.
    assert not run_task.done(), "the reaped run's worker kept running"
    # A new run on the same thread is now accepted: the per-thread mutex is
    # gone, so a user who "recovers" by re-sending races the zombie for the
    # same LangGraph checkpoint.
    assert await service.get_active("t-zombie") is None
    second = await service.create(
        thread_id="t-zombie", user_id=str(record.user_id), input={"messages": []}
    )
    assert second.status == RunStatus.pending

    await asyncio.wait_for(run_task, timeout=10)
    assert finished.is_set(), "the agent ran to completion after being declared dead"

    # Its events landed *after* the terminal entry — no session relays them.
    entries = await redis.xrange(keys.run_events_key(record.id))
    end_index = next(i for i, (_, fields) in enumerate(entries) if "end" in fields)
    published_after_end = len(entries) - end_index - 1
    assert published_after_end > 0

    # And its own `success` was discarded: the record still says error.
    final = await service.get(record.id)
    assert final.status == RunStatus.error
    assert final.error == "Worker stopped responding."
