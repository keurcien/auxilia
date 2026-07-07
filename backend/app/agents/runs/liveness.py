"""Worker liveness for a run — a self-expiring Redis key.

Heartbeats are ephemeral coordination: only the latest value matters and
staleness *is* the signal, so they live in Redis (an in-place SET with a TTL)
rather than churning MVCC row versions in Postgres. The reaper treats a
missing key on a `running` run as a dead worker.
"""

from redis.asyncio import Redis

from app.agents.runs import keys
from app.redis_client import get_redis


class RunLiveness:
    """The liveness key for a single run."""

    def __init__(self, run_id: str, redis: Redis | None = None):
        self.run_id = run_id
        self.redis: Redis = redis or get_redis()
        self._key = keys.run_alive_key(run_id)

    async def stamp(self, *, ttl: int) -> None:
        """Refresh the heartbeat; the key expires `ttl` seconds after the last
        stamp, so a dead worker goes silent on its own."""
        await self.redis.set(self._key, "1", ex=ttl)

    async def is_alive(self) -> bool:
        return bool(await self.redis.exists(self._key))

    async def clear(self) -> None:
        """Drop the key on clean finish so the reaper never has to wait out
        the TTL for a run that already finalized."""
        await self.redis.delete(self._key)
