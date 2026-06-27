"""RunRecord storage + the per-thread active-run mutex.

This is the data-access layer for run *records* (the Redis equivalent of a
repository): plain CRUD on a hash, plus the compare-and-set mutex that keeps a
thread to one active run. It never decides policy — `RunService` does.
"""

import json
from datetime import UTC, datetime

from redis.asyncio import Redis

from app.agents.runs import keys
from app.agents.runs.state import RunRecord, RunStatus, is_terminal, transition
from app.redis_client import get_redis


# Compare-and-delete: only release the mutex if we still own it. Avoids a slow
# worker deleting the mutex a newer run already re-claimed after a TTL expiry.
_RELEASE_IF_OWNER = """
if redis.call('get', KEYS[1]) == ARGV[1] then
    return redis.call('del', KEYS[1])
end
return 0
"""


class RunRegistry:
    def __init__(self, redis: Redis | None = None):
        self.redis: Redis = redis or get_redis()
        self._release = self.redis.register_script(_RELEASE_IF_OWNER)

    async def create(self, record: RunRecord, *, ttl: int) -> None:
        """Persist a new record, index it on its thread, and mark it active."""
        run_key = keys.run_key(record.id)
        score = record.created_at.timestamp()
        async with self.redis.pipeline(transaction=True) as pipe:
            pipe.hset(run_key, mapping=record.to_redis())
            pipe.expire(run_key, ttl)
            pipe.zadd(keys.thread_runs_key(record.thread_id), {record.id: score})
            pipe.expire(keys.thread_runs_key(record.thread_id), ttl)
            pipe.sadd(keys.ACTIVE_SET_KEY, record.id)
            await pipe.execute()

    async def get(self, run_id: str) -> RunRecord | None:
        raw = await self.redis.hgetall(keys.run_key(run_id))
        return RunRecord.from_redis(raw) if raw else None

    async def list_for_thread(self, thread_id: str) -> list[RunRecord]:
        """Runs for a thread, newest first."""
        run_ids = await self.redis.zrevrange(keys.thread_runs_key(thread_id), 0, -1)
        records = [await self.get(run_id) for run_id in run_ids]
        return [r for r in records if r is not None]

    async def set_status(
        self, run_id: str, target: RunStatus, *, error: str | None = None
    ) -> RunRecord | None:
        """Transition a run's status (validated), stamping `updated_at`.

        On reaching a terminal state, drop it from the active set. Returns the
        updated record, or `None` if the run vanished (TTL expiry).
        """
        record = await self.get(run_id)
        if record is None:
            return None
        record.status = transition(record.status, target)
        record.updated_at = datetime.now(UTC)
        mapping = {
            "status": json.dumps(record.status.value),
            "updated_at": json.dumps(record.updated_at.isoformat()),
        }
        if error is not None:
            record.error = error
            mapping["error"] = json.dumps(error)
        async with self.redis.pipeline(transaction=True) as pipe:
            pipe.hset(keys.run_key(run_id), mapping=mapping)
            if is_terminal(record.status):
                pipe.srem(keys.ACTIVE_SET_KEY, run_id)
            await pipe.execute()
        return record

    async def heartbeat(self, run_id: str) -> None:
        """Stamp `last_heartbeat` so the reaper can tell this worker is alive."""
        stamp = json.dumps(datetime.now(UTC).isoformat())
        await self.redis.hset(
            keys.run_key(run_id),
            mapping={"last_heartbeat": stamp, "updated_at": stamp},
        )

    async def set_ttl(self, run_id: str, ttl: int) -> None:
        """Expire all keys for a finished run."""
        async with self.redis.pipeline(transaction=True) as pipe:
            pipe.expire(keys.run_key(run_id), ttl)
            pipe.expire(keys.run_events_key(run_id), ttl)
            pipe.expire(keys.run_control_key(run_id), ttl)
            await pipe.execute()

    async def list_active_ids(self) -> list[str]:
        """Run ids currently pending/running (the reaper's worklist)."""
        return list(await self.redis.smembers(keys.ACTIVE_SET_KEY))

    async def discard_active_id(self, run_id: str) -> None:
        """Drop an id from the active set (e.g. a reaped record that TTL'd away)."""
        await self.redis.srem(keys.ACTIVE_SET_KEY, run_id)

    # --- per-thread active-run mutex ---------------------------------------

    async def claim_active(self, thread_id: str, run_id: str, *, ttl: int) -> bool:
        """Try to make `run_id` the thread's active run. True if claimed."""
        claimed = await self.redis.set(
            keys.thread_active_run_key(thread_id), run_id, nx=True, ex=ttl
        )
        return bool(claimed)

    async def refresh_active(self, thread_id: str, run_id: str, *, ttl: int) -> None:
        """Extend the mutex TTL while the run is alive (called on heartbeat)."""
        if await self.redis.get(keys.thread_active_run_key(thread_id)) == run_id:
            await self.redis.expire(keys.thread_active_run_key(thread_id), ttl)

    async def release_active(self, thread_id: str, run_id: str) -> None:
        """Release the mutex iff we still hold it."""
        await self._release(keys=[keys.thread_active_run_key(thread_id)], args=[run_id])

    async def get_active_id(self, thread_id: str) -> str | None:
        return await self.redis.get(keys.thread_active_run_key(thread_id))
