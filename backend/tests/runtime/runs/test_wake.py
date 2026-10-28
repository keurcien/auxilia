"""The Redis wake-up: `RunService` signals, the stream session listens.

Postgres is queried only when something changed (a wake token for the
dispatcher, the thread's `latest_run` marker for a stream session) plus a
slow fallback poll. The dispatcher side lives in `test_worker.py`.
"""

import asyncio
from datetime import UTC, datetime
from uuid import uuid4

import pytest

import app.runtime.api.protocol_service as protocol_mod
from app.runtime.api.protocol_schemas import EventStreamBody
from app.runtime.api.protocol_service import ProtocolService
from app.runtime.runs import keys
from app.runtime.runs.models import RunDB
from app.runtime.runs.service import WAKE_LIST_CAP, RunService
from app.runtime.runs.settings import run_settings
from app.runtime.runs.state import RunStatus


pytestmark = pytest.mark.usefixtures("run_db")


def _user() -> str:
    return str(uuid4())


# --- the signal ----------------------------------------------------------------


async def test_create_pushes_a_wake_token_and_records_the_threads_newest_run(redis):
    service = RunService(redis)

    run = await service.create(thread_id="t1", user_id=_user())

    assert await redis.llen(keys.dispatch_wake_key()) == 1
    assert await redis.ttl(keys.dispatch_wake_key()) > 0
    assert await service.latest_run_marker("t1") == run.id
    assert await redis.ttl(keys.thread_latest_run_key("t1")) > 0


async def test_finalize_pushes_a_wake_token_only_when_it_moved_the_run(redis):
    service = RunService(redis)
    run = await service.create(thread_id="t1", user_id=_user())
    await service.claim_next()
    await redis.delete(keys.dispatch_wake_key())

    await service.finalize(run.id, RunStatus.success)
    assert await redis.llen(keys.dispatch_wake_key()) == 1

    await service.finalize(run.id, RunStatus.success)  # already terminal: no-op
    assert await redis.llen(keys.dispatch_wake_key()) == 1


async def test_a_redis_failure_inside_the_signal_does_not_fail_create(
    redis, monkeypatch
):
    service = RunService(redis)

    def _down(*_, **__):
        raise ConnectionError("redis down")

    monkeypatch.setattr(redis, "pipeline", _down)

    run = await service.create(thread_id="t1", user_id=_user())

    assert (await service.get(run.id)).status == RunStatus.pending


async def test_the_wake_list_is_capped(redis):
    await redis.rpush(keys.dispatch_wake_key(), *["1"] * (WAKE_LIST_CAP + 20))

    await RunService(redis)._signal_dispatch()

    assert await redis.llen(keys.dispatch_wake_key()) == WAKE_LIST_CAP


# --- the stream session --------------------------------------------------------


@pytest.fixture
def session(redis, monkeypatch):
    """A `ProtocolService` with a fast idle poll, a far fallback, and a spy
    counting Postgres `next_for_thread` calls."""
    monkeypatch.setattr(protocol_mod, "_IDLE_POLL_SECONDS", 0.01)
    monkeypatch.setattr(run_settings, "claim_fallback_seconds", 60.0)
    service = ProtocolService(redis)
    calls = []
    inner = service.runs.next_for_thread

    async def _spy(*args, **kwargs):
        calls.append(1)
        return await inner(*args, **kwargs)

    monkeypatch.setattr(service.runs, "next_for_thread", _spy)
    service.pg_calls = calls
    return service


async def _keep_alives(gen, n: int) -> None:
    for _ in range(n):
        assert await anext(gen) == protocol_mod._KEEP_ALIVE


async def _next_frame(gen) -> str:
    async with asyncio.timeout(1):
        while (frame := await anext(gen)) == protocol_mod._KEEP_ALIVE:
            pass
    return frame


async def test_an_idle_session_stays_off_postgres(session):
    gen = session.stream_events("t1", EventStreamBody(channels=["lifecycle"]))
    try:
        await _keep_alives(gen, 10)
    finally:
        await gen.aclose()

    assert len(session.pg_calls) == 1


async def test_a_marker_change_triggers_the_query_and_the_run_is_streamed(session):
    gen = session.stream_events("t1", EventStreamBody(channels=["lifecycle"]))
    try:
        await _keep_alives(gen, 3)
        run = await session.runs.create(thread_id="t1", user_id=_user())
        await session.runs.claim_next()
        await session.runs.finalize(run.id, RunStatus.success)

        frame = await _next_frame(gen)
    finally:
        await gen.aclose()

    assert run.id in frame
    assert len(session.pg_calls) == 2


async def test_the_fallback_finds_a_run_created_behind_redis_back(
    session, run_db, monkeypatch
):
    monkeypatch.setattr(run_settings, "claim_fallback_seconds", 0.03)
    gen = session.stream_events("t1", EventStreamBody(channels=["lifecycle"]))
    try:
        await _keep_alives(gen, 1)
        # Inserted without a signal (no marker, no token).
        run = RunDB(
            thread_id="t1",
            user_id=uuid4(),
            status=RunStatus.success,
            created_at=datetime.now(UTC),
        )
        async with run_db() as db:
            db.add(run)
            await db.commit()

        frame = await _next_frame(gen)
    finally:
        await gen.aclose()

    assert run.id in frame


async def test_a_redis_error_on_the_marker_falls_back_to_postgres(
    session, redis, monkeypatch
):
    async def _down(*_, **__):
        raise ConnectionError("redis down")

    monkeypatch.setattr(redis, "get", _down)
    gen = session.stream_events("t1", EventStreamBody(channels=["lifecycle"]))
    try:
        await _keep_alives(gen, 3)
    finally:
        await gen.aclose()

    assert len(session.pg_calls) >= 3
