"""RunReaper — recovery of orphaned runs, and the two ways it used to destroy
healthy ones (design review §5.2, §5.3).

The reaper had no tests. It is also the only component in the system that
finalizes runs *it did not start*, so a false positive here is indistinguishable
from a crash as far as the user is concerned.

The two reap passes are driven directly rather than through `_sweep`, and given
an explicit `now` in the future instead of backdated rows. Two reasons: the
SQLite lane stores `DateTime(timezone=True)` as naive (so a `datetime.now(UTC)`
computed inside the reaper can't be subtracted from a column value — the same
reason `test_repository.py` uses naive datetimes), and `updated_at` carries an
`onupdate=func.now()`, so it cannot be backdated by an UPDATE anyway. Moving
`now` forward tests the identical thresholds from the other side.
"""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from app.agents.runs.liveness import DispatcherLiveness, RunLiveness
from app.agents.runs.reaper import RunReaper
from app.agents.runs.service import RunService
from app.agents.runs.settings import run_settings
from app.agents.runs.state import RunStatus


pytestmark = pytest.mark.usefixtures("run_db")


def _db_now() -> datetime:
    """ "Now" on the same clock the row timestamps are on.

    The columns are filled by `server_default=func.now()`, which SQLite renders
    as `CURRENT_TIMESTAMP` — **UTC**, and naive. A plain `datetime.now()` is
    local time, so on any machine east of Greenwich it reads as hours in the
    future and every young run looks stale.
    """
    return datetime.now(UTC).replace(tzinfo=None)


def _after_heartbeat_grace() -> datetime:
    return _db_now() + timedelta(seconds=run_settings.heartbeat_timeout_seconds + 60)


def _after_pending_timeout() -> datetime:
    return _db_now() + timedelta(seconds=run_settings.pending_timeout_seconds + 60)


async def _claimed(service: RunService, thread_id: str) -> str:
    record = await service.create(
        thread_id=thread_id, user_id=str(uuid4()), input={"messages": []}
    )
    claimed = await service.claim_next()
    assert claimed is not None and claimed.id == record.id
    return claimed.id


# ---------------------------------------------------------------------------
# §5.3 — a Redis restart must not mass-reap running runs
# ---------------------------------------------------------------------------


async def test_a_dead_looking_run_survives_its_first_sweep(redis):
    """One missing liveness key is not proof of death: a Redis restart drops
    every key at once, and a single-sample rule would kill the whole cluster's
    in-flight runs."""
    service = RunService(redis)
    run_id = await _claimed(service, "t-first")

    await RunReaper(redis)._reap_dead_running(_after_heartbeat_grace())

    assert (await service.get(run_id)).status == RunStatus.running


async def test_a_dead_run_is_reaped_on_the_second_consecutive_sweep(redis):
    service = RunService(redis)
    run_id = await _claimed(service, "t-second")
    reaper = RunReaper(redis)

    await reaper._reap_dead_running(_after_heartbeat_grace())
    await reaper._reap_dead_running(_after_heartbeat_grace())

    record = await service.get(run_id)
    assert record.status == RunStatus.error
    assert record.error == "Worker stopped responding."


async def test_a_run_that_comes_back_to_life_resets_the_suspicion(redis):
    """The Redis-restart scenario end to end: keys vanish, the reaper notices,
    the workers stamp again on their next heartbeat, and nothing is reaped."""
    service = RunService(redis)
    run_id = await _claimed(service, "t-revived")
    reaper = RunReaper(redis)

    await reaper._reap_dead_running(_after_heartbeat_grace())  # first sighting
    await RunLiveness(run_id, redis).stamp(ttl=60)  # worker heartbeats again
    await reaper._reap_dead_running(_after_heartbeat_grace())  # alive — cleared
    await RunLiveness(run_id, redis).clear()
    await reaper._reap_dead_running(_after_heartbeat_grace())  # a *first* sighting

    assert (await service.get(run_id)).status == RunStatus.running


async def test_a_live_run_is_never_reaped(redis):
    service = RunService(redis)
    run_id = await _claimed(service, "t-live")
    await RunLiveness(run_id, redis).stamp(ttl=60)
    reaper = RunReaper(redis)

    await reaper._reap_dead_running(_after_heartbeat_grace())
    await reaper._reap_dead_running(_after_heartbeat_grace())

    assert (await service.get(run_id)).status == RunStatus.running


async def test_a_recently_claimed_run_is_inside_the_grace_window(redis):
    """The claim → first-stamp gap must not look like death."""
    service = RunService(redis)
    run_id = await _claimed(service, "t-fresh")
    reaper = RunReaper(redis)

    await reaper._reap_dead_running(_db_now())
    await reaper._reap_dead_running(_db_now())

    assert (await service.get(run_id)).status == RunStatus.running


# ---------------------------------------------------------------------------
# §5.2 — a backlog must not look like an undispatched zombie
# ---------------------------------------------------------------------------


async def test_queued_runs_survive_while_a_dispatcher_is_alive(redis):
    """The regression: ~30 trigger firings, each on a fresh thread, queue behind
    a saturated worker pool. "Pending, old, no running run on its thread" is
    exactly their shape, and they used to be killed mid-queue."""
    service = RunService(redis)
    queued = [
        (
            await service.create(
                thread_id=f"t-queue-{i}", user_id=str(uuid4()), input={"messages": []}
            )
        ).id
        for i in range(3)
    ]
    await DispatcherLiveness(redis).stamp(ttl=60)

    await RunReaper(redis)._reap_undispatched_pending(_after_pending_timeout())

    for run_id in queued:
        assert (await service.get(run_id)).status == RunStatus.pending


async def test_pending_runs_are_reaped_once_no_dispatcher_is_alive(redis):
    """The case the rule is actually for: nothing in the cluster can claim."""
    service = RunService(redis)
    record = await service.create(
        thread_id="t-orphan", user_id=str(uuid4()), input={"messages": []}
    )

    await RunReaper(redis)._reap_undispatched_pending(_after_pending_timeout())

    back = await service.get(record.id)
    assert back.status == RunStatus.error
    assert back.error == "Run was never dispatched."


async def test_a_young_pending_run_is_never_reaped(redis):
    service = RunService(redis)
    record = await service.create(
        thread_id="t-young", user_id=str(uuid4()), input={"messages": []}
    )

    await RunReaper(redis)._reap_undispatched_pending(_db_now())

    assert (await service.get(record.id)).status == RunStatus.pending


async def test_dispatcher_liveness_expires_so_a_dead_cluster_is_detectable(redis):
    """The gate is a self-expiring key, not a flag: a dispatcher that dies
    without cleaning up must stop counting as alive on its own."""
    liveness = DispatcherLiveness(redis)
    await liveness.stamp(ttl=60)
    assert await liveness.any_alive() is True

    await redis.delete("run:dispatchers:alive")

    assert await liveness.any_alive() is False
