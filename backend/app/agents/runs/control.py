"""The cancel channel for a run.

A Stop request `request_cancel`s by pushing a token; the worker runs
`wait_for_cancel` concurrently with the stream and aborts when the token arrives.
A list (rather than pub/sub) means the signal survives until consumed, so a
cancel that races the worker's startup isn't lost.

`wait_for_cancel` *polls* with a non-blocking LPOP rather than holding a
connection on a blocking BLPOP: it stays promptly cancellable when the worker
tears it down after a clean finish, with no held connection — uniform behaviour
across real Redis and the test fake. ~`poll_seconds` of cancel latency is fine
for a Stop.
"""

import asyncio

from redis.asyncio import Redis

from app.agents.runs import keys
from app.redis_client import get_redis


class RunControl:
    """The control channel for a single run."""

    def __init__(self, run_id: str, redis: Redis | None = None):
        self.run_id = run_id
        self.redis: Redis = redis or get_redis()
        self._key = keys.run_control_key(run_id)

    async def request_cancel(self, *, ttl: int) -> None:
        """Signal the worker to stop this run."""
        async with self.redis.pipeline(transaction=True) as pipe:
            pipe.rpush(self._key, "cancel")
            pipe.expire(self._key, ttl)
            await pipe.execute()

    async def wait_for_cancel(self, *, poll_seconds: float = 1.0) -> bool:
        """Return True once a cancel signal is present, polling until then."""
        # Guard against a misconfigured 0/negative interval turning this into a
        # tight Redis loop on every running worker.
        interval = poll_seconds if poll_seconds > 0 else 1.0
        while True:
            if await self.redis.lpop(self._key) is not None:
                return True
            await asyncio.sleep(interval)
