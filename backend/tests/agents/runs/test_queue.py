import asyncio
from uuid import uuid4

import pytest

from app.agents.runs.queue import RunQueue


@pytest.mark.asyncio
class TestQueue:
    async def test_fifo_order(self, redis):
        q = RunQueue(redis)
        ids = [uuid4() for _ in range(3)]
        for rid in ids:
            await q.enqueue(rid)

        assert await q.length() == 3
        seen = [await q.dequeue(timeout_seconds=1) for _ in range(3)]
        assert seen == ids

    async def test_dequeue_timeout_returns_none(self, redis):
        q = RunQueue(redis)
        result = await q.dequeue(timeout_seconds=1)
        assert result is None

    async def test_dequeue_blocks_until_enqueue(self, redis):
        q = RunQueue(redis)
        rid = uuid4()

        async def push_after_delay():
            await asyncio.sleep(0.1)
            await q.enqueue(rid)

        task = asyncio.create_task(push_after_delay())
        result = await q.dequeue(timeout_seconds=2)
        await task
        assert result == rid
