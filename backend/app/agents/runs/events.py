"""The reattachable event log — a Redis Stream of SSE chunks per run.

The worker `publish`es each SSE string the agent emits; subscribers `subscribe`
from a cursor and relay the raw strings to their HTTP response. Stream entry ids
*are* the resume cursor, so reattach replays only what a client missed.
"""

import json
from collections.abc import AsyncGenerator

from redis.asyncio import Redis

from app.agents.runs import keys
from app.agents.runs.state import RunStatus
from app.redis_client import get_redis


# Stream entry fields.
_DATA = "data"  # the raw SSE chunk
_END = "end"  # present ("1") only on the terminal sentinel


def end_sentinel(status: RunStatus) -> str:
    """The SSE chunk that terminates a run's stream. Also emitted synthetically
    when a subscriber attaches to a terminal run whose event log has expired."""
    return f"event: end\ndata: {json.dumps({'status': status.value})}\n\n"


class RunEventStream:
    """The event log for a single run."""

    def __init__(self, run_id: str, redis: Redis | None = None):
        self.run_id = run_id
        self.redis: Redis = redis or get_redis()
        self._key = keys.run_events_key(run_id)

    async def publish(self, sse: str) -> str:
        """Append an SSE chunk; returns its stream entry id."""
        return await self.redis.xadd(self._key, {_DATA: sse})

    async def publish_end(self, status: RunStatus) -> str:
        """Append the terminal sentinel. Subscribers stop after reading it."""
        return await self.redis.xadd(
            self._key, {_DATA: end_sentinel(status), _END: "1"}
        )

    async def exists(self) -> bool:
        """Whether the log has any entries (False once the key TTLs away)."""
        return bool(await self.redis.exists(self._key))

    async def subscribe(
        self, last_event_id: str = "0", *, block_ms: int = 15000
    ) -> AsyncGenerator[str, None]:
        """Yield SSE chunks from `last_event_id` onward until the sentinel.

        `"0"` replays the whole log (fresh subscriber); pass a client's last seen
        entry id to resume after a reattach. Blocks for live chunks in between.
        The worker (or reaper) always publishes the sentinel on a terminal run,
        so this generator is guaranteed to end.
        """
        cursor = last_event_id or "0"
        while True:
            result = await self.redis.xread(
                {self._key: cursor}, block=block_ms, count=100
            )
            if not result:
                continue  # block window elapsed with no new entries — keep waiting
            _, entries = result[0]
            for entry_id, fields in entries:
                cursor = entry_id
                data = fields.get(_DATA)
                if data is not None:
                    yield data
                if fields.get(_END):
                    return
