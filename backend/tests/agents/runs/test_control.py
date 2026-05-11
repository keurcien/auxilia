import asyncio
from uuid import uuid4

import pytest

from app.agents.runs.control import RunControl
from app.agents.runs.state import CancellationReason


@pytest.mark.asyncio
class TestCancelSignal:
    async def test_signal_then_watch(self, redis):
        ctl = RunControl(redis)
        rid = uuid4()
        await ctl.signal_cancel(rid, CancellationReason.USER)
        reason = await asyncio.wait_for(ctl.watch_cancel(rid, timeout=1), timeout=2)
        assert reason is CancellationReason.USER

    async def test_watch_blocks_until_signal(self, redis):
        ctl = RunControl(redis)
        rid = uuid4()

        async def signal_after_delay():
            await asyncio.sleep(0.1)
            await ctl.signal_cancel(rid, CancellationReason.REPLACED)

        task = asyncio.create_task(signal_after_delay())
        reason = await asyncio.wait_for(ctl.watch_cancel(rid, timeout=2), timeout=3)
        await task
        assert reason is CancellationReason.REPLACED

    async def test_clear_drops_pending_signal(self, redis):
        ctl = RunControl(redis)
        rid = uuid4()
        await ctl.signal_cancel(rid)
        await ctl.clear(rid)
        with pytest.raises(asyncio.TimeoutError):
            await ctl.watch_cancel(rid, timeout=0.2)

    async def test_unknown_reason_value_falls_back_to_system(self, redis):
        ctl = RunControl(redis)
        rid = uuid4()
        await redis.rpush(f"run:{rid}:control", "garbage-reason")
        reason = await asyncio.wait_for(ctl.watch_cancel(rid, timeout=1), timeout=2)
        assert reason is CancellationReason.SYSTEM
