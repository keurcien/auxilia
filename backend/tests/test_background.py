"""Supervised background loops and the health they publish (design review §2.3).

The failure being prevented: a loop dies, logs one ERROR, and the instance keeps
answering 200s while nothing executes runs or fires triggers ever again — and on
Cloud Run keeps passing its health check, so nothing recycles it.
"""

import asyncio
from contextlib import suppress

import pytest

from app.background import MAX_BACKOFF_SECONDS, LoopHealth, LoopRegistry, PeriodicLoop


@pytest.fixture(autouse=True)
def isolated_registry(monkeypatch):
    """Loops register themselves on construction; keep tests out of each
    other's registry (and out of the process-wide one)."""
    registry = LoopRegistry()
    monkeypatch.setattr("app.background.registry", registry)
    # `main` imports the registry by value, so the endpoint's reference has to
    # be swapped too.
    monkeypatch.setattr("app.main.background_loops", registry)
    return registry


async def _run_briefly(loop: PeriodicLoop, until, condition, *, what: str) -> None:
    """Run the loop until `condition` holds, then stop it.

    `stop()` wakes the loop out of its sleep, so it usually exits on its own;
    the cancel is only there for the case where it does not.
    """
    task = asyncio.create_task(loop.run())
    try:
        await until(condition, what=what)
    finally:
        loop.stop()
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task


# ---------------------------------------------------------------------------
# supervision
# ---------------------------------------------------------------------------


async def test_a_raising_tick_is_retried_rather_than_ending_the_loop(until):
    calls = 0

    async def tick() -> None:
        nonlocal calls
        calls += 1
        if calls < 3:
            raise RuntimeError("postgres failing over")

    loop = PeriodicLoop("flaky", 0.001, tick)

    async def _recovered() -> bool:
        return calls >= 3

    await _run_briefly(loop, until, _recovered, what="the loop to recover")

    assert loop.health.consecutive_failures == 0
    assert loop.health.last_error is None


async def test_a_persistent_failure_backs_off_instead_of_spinning(until, monkeypatch):
    """Without backoff a permanently broken dependency turns the loop into a
    tight error-logging spin — the second-worst outcome after dying.

    The waits are captured rather than timed: asserting on real elapsed time
    would make this test a flake generator on a loaded CI box.
    """
    waits: list[float] = []

    async def tick() -> None:
        raise RuntimeError("still broken")

    loop = PeriodicLoop("broken", 0.001, tick)
    real_sleep = loop._sleep

    async def _recording_sleep(seconds: float) -> None:
        waits.append(seconds)
        await real_sleep(0)

    monkeypatch.setattr(loop, "_sleep", _recording_sleep)

    async def _backed_off_thrice() -> bool:
        return len(waits) >= 3

    await _run_briefly(loop, until, _backed_off_thrice, what="three backoffs")

    assert waits[:3] == [0.001, 0.002, 0.004]  # doubling
    assert loop.health.consecutive_failures >= 3
    assert loop.health.last_error == "RuntimeError"


async def test_backoff_is_capped(until, monkeypatch):
    """A loop broken for an hour must still retry, just not often."""
    waits: list[float] = []

    async def tick() -> None:
        raise RuntimeError("still broken")

    loop = PeriodicLoop("broken", MAX_BACKOFF_SECONDS, tick)

    async def _recording_sleep(seconds: float) -> None:
        waits.append(seconds)
        # Must yield: a coroutine with no await never hands control back, so the
        # loop would spin without the poller below ever getting to run.
        await asyncio.sleep(0)

    monkeypatch.setattr(loop, "_sleep", _recording_sleep)

    async def _backed_off_twice() -> bool:
        return len(waits) >= 2

    await _run_briefly(loop, until, _backed_off_twice, what="two backoffs")

    assert set(waits) == {MAX_BACKOFF_SECONDS}


async def test_failures_are_visible_in_health_while_they_last(until):
    async def tick() -> None:
        raise RuntimeError("boom")

    loop = PeriodicLoop("boom", 0.001, tick)

    async def _failed() -> bool:
        return loop.health.consecutive_failures > 0

    await _run_briefly(loop, until, _failed, what="a recorded failure")

    snapshot = loop.health.snapshot()
    assert snapshot["last_error_type"] == "RuntimeError"


# ---------------------------------------------------------------------------
# health reporting
# ---------------------------------------------------------------------------


def test_a_loop_that_never_started_is_not_reported_unhealthy():
    """`RUN_DISPATCHER_ENABLED=false` is a supported deployment, not a degraded
    one."""
    assert LoopHealth(name="idle", interval=1).is_healthy() is True


def test_a_stopped_loop_is_healthy():
    """Shutdown is not failure."""
    health = LoopHealth(name="done", interval=1, started=True, stopped=True)

    assert health.is_healthy() is True


def test_a_started_loop_that_never_ticked_is_unhealthy():
    """The case that matters most: a loop that dies on its very first tick."""
    health = LoopHealth(name="stillborn", interval=1, started=True)

    assert health.is_healthy() is False


def test_a_loop_that_stopped_ticking_is_unhealthy():
    health = LoopHealth(name="wedged", interval=1, started=True)
    health.mark_tick()
    health.last_tick_at -= MAX_BACKOFF_SECONDS + 100

    assert health.is_healthy() is False


def test_a_loop_ticking_on_schedule_is_healthy():
    health = LoopHealth(name="fine", interval=1, started=True)
    health.mark_tick()

    assert health.is_healthy() is True


def test_a_slow_but_ticking_loop_gets_slack_for_its_backoff():
    """A loop retrying with backoff is still working; the deadline has to leave
    room for a full backoff or every transient failure reads as a dead loop."""
    health = LoopHealth(name="retrying", interval=1, started=True)
    health.mark_tick()
    health.last_tick_at -= MAX_BACKOFF_SECONDS - 1

    assert health.is_healthy() is True


def test_the_registry_is_unhealthy_if_any_loop_is(isolated_registry):
    isolated_registry.register(LoopHealth(name="ok", interval=1))
    dead = isolated_registry.register(LoopHealth(name="dead", interval=1, started=True))

    assert isolated_registry.healthy is False
    assert [loop["name"] for loop in isolated_registry.snapshot()] == ["ok", "dead"]
    assert dead.is_healthy() is False


def test_an_empty_registry_is_healthy(isolated_registry):
    assert isolated_registry.healthy is True


# ---------------------------------------------------------------------------
# /health — what Cloud Run acts on
# ---------------------------------------------------------------------------


def test_health_is_ok_when_every_loop_is_ticking(client, isolated_registry):
    health = isolated_registry.register(LoopHealth(name="run-dispatcher", interval=1))
    health.started = True
    health.mark_tick()

    response = client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["loops"][0]["name"] == "run-dispatcher"


def test_health_is_503_when_a_loop_has_stopped_ticking(client, isolated_registry):
    """The whole point: a dead dispatcher used to leave an instance answering
    200s while no run ever executed again, so nothing recycled it."""
    health = isolated_registry.register(LoopHealth(name="run-dispatcher", interval=1))
    health.started = True
    health.mark_tick()
    health.last_tick_at -= MAX_BACKOFF_SECONDS + 100

    response = client.get("/health")

    assert response.status_code == 503
    assert response.json()["status"] == "degraded"


def test_health_is_ok_on_a_request_only_instance(client, isolated_registry):
    """`RUN_DISPATCHER_ENABLED=false` registers no loops — a supported
    deployment, not a degraded one."""
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["loops"] == []


async def test_health_never_exposes_raw_exception_text(until):
    """`/health` is unauthenticated, so anything kept here is world-readable —
    and an exception repr can carry a DSN, a query, or a token from whatever
    raised. The type is enough to triage; the rest belongs in the logs."""

    async def tick() -> None:
        raise RuntimeError("postgresql://admin:hunter2@db.internal:5432/prod")

    loop = PeriodicLoop("leaky", 0.001, tick)

    async def _failed() -> bool:
        return loop.health.consecutive_failures > 0

    await _run_briefly(loop, until, _failed, what="a recorded failure")

    assert "hunter2" not in repr(loop.health.snapshot())
    assert loop.health.snapshot()["last_error_type"] == "RuntimeError"


def test_the_loop_intervals_that_sleep_directly_are_clamped():
    """`PeriodicLoop`'s floor does not reach the dispatcher's and the run
    heartbeat's loops — they sleep directly — so the settings clamp at source.
    Zero would otherwise burn a core for the life of the process."""
    from app.agents.runs.settings import RunSettings

    settings = RunSettings(
        heartbeat_interval_seconds=0,
        reaper_interval_seconds=0,
        claim_interval_seconds=0,
        cancel_poll_seconds=-1,
        _env_file=None,
    )

    assert settings.heartbeat_interval_seconds == 1
    assert settings.reaper_interval_seconds == 1
    assert settings.claim_interval_seconds > 0
    assert settings.cancel_poll_seconds > 0
    # The whole-second fields must stay whole — they are typed `int`.
    assert isinstance(settings.heartbeat_interval_seconds, int)
    assert isinstance(settings.reaper_interval_seconds, int)


def test_register_loop_resolves_the_registry_at_call_time(monkeypatch):
    """The seam that makes registry isolation possible at all: callers that did
    `from app.background import registry` kept writing to the original."""
    swapped = LoopRegistry()
    monkeypatch.setattr("app.background.registry", swapped)

    from app.background import register_loop

    register_loop(LoopHealth(name="somewhere-else", interval=1))

    assert [loop.name for loop in swapped.loops] == ["somewhere-else"]
