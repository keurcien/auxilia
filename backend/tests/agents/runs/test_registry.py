from datetime import datetime, timezone
from uuid import uuid4

import pytest

from app.agents.runs.registry import RunRegistry
from app.agents.runs.state import (
    CancellationReason,
    MultitaskStrategy,
    RunRecord,
    RunState,
    utcnow,
)


def _make_record(**overrides) -> RunRecord:
    now = utcnow()
    defaults = dict(
        id=uuid4(),
        thread_id="thread-1",
        user_id=uuid4(),
        agent_id=uuid4(),
        status=RunState.PENDING,
        multitask_strategy=MultitaskStrategy.REJECT,
        created_at=now,
        updated_at=now,
    )
    defaults.update(overrides)
    return RunRecord(**defaults)


@pytest.mark.asyncio
class TestCreateAndGet:
    async def test_round_trip(self, redis):
        reg = RunRegistry(redis)
        original = _make_record(
            interrupt={"value": "approve?"},
            input_summary={"text": "hello", "files": 0},
            model_id="claude-opus-4-7",
        )
        await reg.create(original)
        loaded = await reg.get(original.id)
        assert loaded == original

    async def test_get_missing_returns_none(self, redis):
        reg = RunRegistry(redis)
        assert await reg.get(uuid4()) is None

    async def test_create_sets_ttl(self, redis):
        reg = RunRegistry(redis)
        record = _make_record()
        await reg.create(record, ttl_seconds=60)
        ttl = await redis.ttl(f"run:{record.id}")
        assert 0 < ttl <= 60


@pytest.mark.asyncio
class TestUpdate:
    async def test_status_transition_persists(self, redis):
        reg = RunRegistry(redis)
        record = _make_record()
        await reg.create(record)

        updated = await reg.update(record.id, status=RunState.RUNNING)
        assert updated.status == RunState.RUNNING
        assert updated.updated_at >= record.updated_at

        loaded = await reg.get(record.id)
        assert loaded.status == RunState.RUNNING

    async def test_clearing_optional_field_to_none(self, redis):
        reg = RunRegistry(redis)
        record = _make_record(interrupt={"x": 1})
        await reg.create(record)

        updated = await reg.update(record.id, interrupt=None)
        assert updated.interrupt is None

        loaded = await reg.get(record.id)
        # Hash never stored None, so absence after clear is correct.
        assert loaded.interrupt is None

    async def test_update_unknown_run_raises(self, redis):
        reg = RunRegistry(redis)
        with pytest.raises(KeyError):
            await reg.update(uuid4(), status=RunState.RUNNING)


@pytest.mark.asyncio
class TestActiveRunMutex:
    async def test_first_set_wins(self, redis):
        reg = RunRegistry(redis)
        rid_a, rid_b = uuid4(), uuid4()
        assert await reg.try_set_active("thread-1", rid_a) is True
        assert await reg.try_set_active("thread-1", rid_b) is False
        assert await reg.get_active("thread-1") == rid_a

    async def test_clear_only_if_match(self, redis):
        reg = RunRegistry(redis)
        rid_a, rid_b = uuid4(), uuid4()
        await reg.try_set_active("thread-1", rid_a)

        # Other run cannot clear.
        assert await reg.clear_active_if_match("thread-1", rid_b) is False
        assert await reg.get_active("thread-1") == rid_a

        # Owning run can.
        assert await reg.clear_active_if_match("thread-1", rid_a) is True
        assert await reg.get_active("thread-1") is None

    async def test_active_ttl(self, redis):
        reg = RunRegistry(redis)
        rid = uuid4()
        await reg.try_set_active("thread-1", rid, ttl_seconds=120)
        ttl = await redis.ttl("thread:thread-1:active_run")
        assert 0 < ttl <= 120


@pytest.mark.asyncio
class TestHeartbeatAndScan:
    async def test_heartbeat_updates_field_only(self, redis):
        reg = RunRegistry(redis)
        record = _make_record()
        await reg.create(record)
        await reg.heartbeat(record.id)
        loaded = await reg.get(record.id)
        assert loaded.heartbeat_at is not None
        assert loaded.heartbeat_at > record.created_at

    async def test_scan_active_filters_terminal(self, redis):
        reg = RunRegistry(redis)
        active = _make_record(status=RunState.RUNNING)
        terminal = _make_record(status=RunState.SUCCESS)
        interrupted = _make_record(status=RunState.INTERRUPTED)
        await reg.create(active)
        await reg.create(terminal)
        await reg.create(interrupted)

        found_ids = {r.id for r in await reg.scan_active()}
        assert active.id in found_ids
        assert interrupted.id in found_ids
        assert terminal.id not in found_ids


@pytest.mark.asyncio
class TestSerialization:
    async def test_enums_round_trip_correctly(self, redis):
        reg = RunRegistry(redis)
        record = _make_record(
            status=RunState.RUNNING,
            cancellation_reason=CancellationReason.TIMEOUT,
            multitask_strategy=MultitaskStrategy.INTERRUPT,
        )
        await reg.create(record)
        loaded = await reg.get(record.id)
        assert loaded.status is RunState.RUNNING
        assert loaded.cancellation_reason is CancellationReason.TIMEOUT
        assert loaded.multitask_strategy is MultitaskStrategy.INTERRUPT

    async def test_datetimes_preserve_timezone(self, redis):
        reg = RunRegistry(redis)
        ts = datetime(2026, 1, 1, 12, 30, 45, tzinfo=timezone.utc)
        record = _make_record(created_at=ts, updated_at=ts)
        await reg.create(record)
        loaded = await reg.get(record.id)
        assert loaded.created_at == ts
        assert loaded.created_at.tzinfo is not None
