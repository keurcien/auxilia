"""The shared dispatch queue.

A single Redis list of run_ids that any instance's dispatcher can drain. LPUSH +
BRPOP gives FIFO ordering; the shared key is what distributes runs across
instances. No per-run state here — just the hand-off.
"""

from redis.asyncio import Redis

from app.agents.runs import keys
from app.redis_client import get_redis


class RunQueue:
    def __init__(self, redis: Redis | None = None):
        self.redis: Redis = redis or get_redis()

    async def enqueue(self, run_id: str) -> None:
        """Add a run to the tail of the queue (FIFO with `dequeue`)."""
        await self.redis.lpush(keys.QUEUE_KEY, run_id)

    async def dequeue(self, *, timeout: float = 5.0) -> str | None:
        """Block up to `timeout` seconds for the next run_id; None on timeout."""
        result = await self.redis.brpop([keys.QUEUE_KEY], timeout=timeout)
        if result is None:
            return None
        _, run_id = result
        return run_id
