"""RunService + RunRepository over a real (SQLite) database.

Covers the Postgres-backed lifecycle: create/reject, the single-claim
dispatch, guarded finalize + the `threads.last_run_status` stamp, the
reaper worklists, and retention pruning. Locking semantics (`SKIP LOCKED`,
the partial unique index) are Postgres-only and out of scope here.
"""

from datetime import datetime, timedelta
from uuid import uuid4

import pytest

from app.agents.runs.models import RunDB
from app.agents.runs.service import RunService
from app.agents.runs.state import RunStatus
from app.exceptions import DomainValidationError, NotFoundError
from app.threads.models import ThreadDB


pytestmark = pytest.mark.usefixtures("run_db")


def _user() -> str:
    return str(uuid4())


async def _add_thread(run_db, thread_id: str) -> None:
    async with run_db() as db:
        db.add(ThreadDB(id=thread_id, user_id=uuid4(), agent_id=uuid4()))
        await db.commit()


async def _get_thread(run_db, thread_id: str) -> ThreadDB | None:
    async with run_db() as db:
        return await db.get(ThreadDB, thread_id)


async def _add_run(run_db, **kwargs) -> RunDB:
    """Insert a run row directly (bypasses create-time guards) for tests that
    need explicit created_at/status."""
    run = RunDB(**kwargs)
    async with run_db() as db:
        db.add(run)
        await db.commit()
    return run


async def test_create_and_get_roundtrip(redis):
    service = RunService(redis)
    schema = {"type": "object"}
    record = await service.create(
        thread_id="t1",
        user_id=_user(),
        input={"messages": [{"type": "human", "content": "hi"}]},
        trigger="regenerate-message",
        output_schema=schema,
    )
    back = await service.get(record.id)
    assert back.status == RunStatus.pending
    assert back.input == record.input
    assert back.trigger == "regenerate-message"
    assert back.output_schema == schema
    assert back.created_at is not None


async def test_get_missing_run_raises(redis):
    with pytest.raises(NotFoundError):
        await RunService(redis).get("nope")


async def test_create_rejects_when_thread_has_active_run(redis):
    service = RunService(redis)
    await service.create(thread_id="t2", user_id=_user(), input={})
    with pytest.raises(DomainValidationError):
        await service.create(thread_id="t2", user_id=_user(), input={})


async def test_create_enqueue_allows_waiting_run(redis):
    service = RunService(redis)
    await service.create(thread_id="t3", user_id=_user(), input={})
    queued = await service.create(
        thread_id="t3", user_id=_user(), input={}, multitask_strategy="enqueue"
    )
    assert queued.status == RunStatus.pending


async def test_claim_next_is_fifo_across_threads(redis, run_db):
    service = RunService(redis)
    now = datetime.now()
    newer = await _add_run(run_db, thread_id="tb", user_id=uuid4(), created_at=now)
    older = await _add_run(
        run_db, thread_id="ta", user_id=uuid4(), created_at=now - timedelta(minutes=1)
    )
    first, second = await service.claim_next(), await service.claim_next()
    assert (first.id, second.id) == (older.id, newer.id)
    assert first.status == RunStatus.running
    assert await service.claim_next() is None


async def test_claim_next_skips_busy_thread_until_freed(redis, run_db):
    """The enqueue strategy in one test: a queued run waits out its sibling."""
    service = RunService(redis)
    now = datetime.now()
    first = await _add_run(run_db, thread_id="t4", user_id=uuid4(), created_at=now)
    waiting = await _add_run(
        run_db, thread_id="t4", user_id=uuid4(), created_at=now + timedelta(seconds=1)
    )
    claimed = await service.claim_next()
    assert claimed.id == first.id
    assert await service.claim_next() is None  # sibling is running — not claimable
    await service.finalize(first.id, RunStatus.success)
    assert (await service.claim_next()).id == waiting.id


async def test_finalize_stamps_thread_and_is_idempotent(redis, run_db):
    service = RunService(redis)
    await _add_thread(run_db, "t5")
    record = await service.create(thread_id="t5", user_id=_user(), input={})
    await service.finalize(record.id, RunStatus.error, error="boom")

    back = await service.get(record.id)
    assert back.status == RunStatus.error
    assert back.error == "boom"
    assert (await _get_thread(run_db, "t5")).last_run_status == "error"

    # Idempotent: a second finalize (reaper racing the worker) is a no-op.
    await service.finalize(record.id, RunStatus.success)
    assert (await service.get(record.id)).status == RunStatus.error
    assert (await _get_thread(run_db, "t5")).last_run_status == "error"


async def test_success_overwrites_previous_error_stamp(redis, run_db):
    service = RunService(redis)
    await _add_thread(run_db, "t6")
    failed = await service.create(thread_id="t6", user_id=_user(), input={})
    await service.finalize(failed.id, RunStatus.error, error="boom")
    retry = await service.create(thread_id="t6", user_id=_user(), input={})
    claimed = await service.claim_next()  # success is only legal from running
    assert claimed.id == retry.id
    await service.finalize(retry.id, RunStatus.success)
    assert (await _get_thread(run_db, "t6")).last_run_status == RunStatus.success


async def test_finalize_publishes_end_sentinel(redis):
    service = RunService(redis)
    record = await service.create(thread_id="t7", user_id=_user(), input={})
    await service.finalize(record.id, RunStatus.cancelled)
    chunks = [c async for c in service.stream(record.id, "0")]
    assert any("event: end" in c and "cancelled" in c for c in chunks)


async def test_cancel_pending_finalizes_immediately(redis):
    service = RunService(redis)
    record = await service.create(thread_id="t8", user_id=_user(), input={})
    out = await service.cancel(record.id)
    assert out.status == RunStatus.cancelled
    assert await service.get_active("t8") is None


async def test_cancel_expected_guard_spares_claimed_run(redis):
    """finalize(expected=pending) must not cancel a run a dispatcher claimed."""
    service = RunService(redis)
    record = await service.create(thread_id="t9", user_id=_user(), input={})
    claimed = await service.claim_next()
    assert claimed.id == record.id
    updated = await service.finalize(
        record.id, RunStatus.cancelled, expected=RunStatus.pending
    )
    assert updated.status == RunStatus.running  # guard held; still running


async def test_finalize_refuses_illegal_source_status(redis):
    """A pending (unclaimed) run can never be reported success/timeout/
    interrupted — the SQL guard mirrors the transition table."""
    service = RunService(redis)
    record = await service.create(thread_id="t9b", user_id=_user(), input={})
    for illegal in (RunStatus.success, RunStatus.timeout, RunStatus.interrupted):
        updated = await service.finalize(record.id, illegal)
        assert updated.status == RunStatus.pending
    # ...but the legal pending transitions still apply.
    updated = await service.finalize(record.id, RunStatus.error, error="zombie")
    assert updated.status == RunStatus.error


async def test_stream_missing_sentinel_backstop(redis, run_db):
    """A worker crash between the Postgres commit and publishing the end
    sentinel must not hang subscribers: an idle read on a terminal run yields
    a synthetic end."""
    service = RunService(redis)
    record = await service.create(thread_id="t9c", user_id=_user(), input={})
    claimed = await service.claim_next()
    from app.agents.runs.events import RunEventStream
    from app.agents.runs.repository import RunRepository

    await RunEventStream(record.id, redis).publish("event: messages\ndata: {}\n\n")
    # Simulate the crash: terminal in Postgres, no sentinel in Redis.
    async with run_db() as db:
        await RunRepository(db).finalize_run(claimed.id, RunStatus.error, error="x")
        await db.commit()
    chunks = [c async for c in service.stream(record.id, "0", block_ms=50)]
    assert any("event: messages" in c for c in chunks)
    assert "event: end" in chunks[-1] and "error" in chunks[-1]


async def test_stream_expired_events_yields_synthetic_end(redis):
    """Reattaching to a terminal run after the event log TTL'd must terminate
    immediately instead of blocking on an empty stream."""
    service = RunService(redis)
    record = await service.create(thread_id="t10", user_id=_user(), input={})
    await service.finalize(record.id, RunStatus.cancelled)
    await redis.flushall()  # simulate the Redis TTL wiping the ephemera
    chunks = [c async for c in service.stream(record.id, "0")]
    assert len(chunks) == 1
    assert "event: end" in chunks[0] and "cancelled" in chunks[0]


async def test_list_active_for_user(redis):
    service = RunService(redis)
    user = _user()
    mine = await service.create(thread_id="t11", user_id=user, input={})
    await service.create(thread_id="t12", user_id=_user(), input={})
    done = await service.create(thread_id="t13", user_id=user, input={})
    await service.finalize(done.id, RunStatus.cancelled)
    active = await service.list_active_for_user(user)
    assert [r.id for r in active] == [mine.id]


async def test_stuck_pending_excludes_enqueue_waiters(redis, run_db):
    service = RunService(redis)
    old = datetime.now() - timedelta(hours=1)
    zombie = await _add_run(run_db, thread_id="t14", user_id=uuid4(), created_at=old)
    await _add_run(  # legitimate waiter: sibling is running
        run_db, thread_id="t15", user_id=uuid4(), created_at=old
    )
    await _add_run(
        run_db,
        thread_id="t15",
        user_id=uuid4(),
        created_at=old,
        status=RunStatus.running,
    )
    stuck = await service.list_stuck_pending(datetime.now() - timedelta(minutes=10))
    assert [r.id for r in stuck] == [zombie.id]


async def test_prune_terminal_keeps_recent_and_active(redis, run_db):
    service = RunService(redis)
    old = datetime.now() - timedelta(days=120)
    pruned = await _add_run(
        run_db,
        thread_id="t16",
        user_id=uuid4(),
        created_at=old,
        status=RunStatus.success,
    )
    old_but_running = await _add_run(
        run_db,
        thread_id="t17",
        user_id=uuid4(),
        created_at=old,
        status=RunStatus.running,
    )
    recent = await _add_run(
        run_db,
        thread_id="t18",
        user_id=uuid4(),
        created_at=datetime.now(),
        status=RunStatus.success,
    )
    count = await service.prune_terminal(datetime.now() - timedelta(days=90))
    assert count == 1
    with pytest.raises(NotFoundError):
        await service.get(pruned.id)
    assert (await service.get(old_but_running.id)).status == RunStatus.running
    assert (await service.get(recent.id)).status == RunStatus.success
