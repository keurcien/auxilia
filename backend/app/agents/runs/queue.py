"""Run dispatch queue.

The HTTP layer enqueues a run id when ``POST /threads/{tid}/runs[/stream]`` is
called. Worker tasks ``BRPOP`` from the queue and execute the run.

A simple Redis list is sufficient: we don't need pub/sub fan-out, and the
ordering guarantees Redis already gives us are exactly what we want. If we
ever need priority queues or fair scheduling per user, swap to a sorted set —
this module is the only thing that would change.
"""

from __future__ import annotations

from uuid import UUID

from redis.asyncio import Redis


QUEUE_KEY: str = "runs:queue"


class RunQueue:
    def __init__(self, redis: Redis, key: str = QUEUE_KEY):
        self.redis = redis
        self.key = key

    async def enqueue(self, run_id: UUID) -> None:
        """LPUSH so workers BRPOP get FIFO order."""
        await self.redis.lpush(self.key, str(run_id))

    async def dequeue(self, *, timeout_seconds: int = 5) -> UUID | None:
        """BRPOP with a timeout so workers can spin shutdown checks between waits."""
        result = await self.redis.brpop([self.key], timeout=timeout_seconds)
        if result is None:
            return None
        _key, raw = result
        if isinstance(raw, bytes):
            raw = raw.decode()
        return UUID(raw)

    async def length(self) -> int:
        return await self.redis.llen(self.key)
