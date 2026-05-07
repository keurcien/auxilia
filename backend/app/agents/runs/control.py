"""Cancellation control channel.

The HTTP layer signals cancellation by appending to a per-run Redis list. The
worker has a watcher coroutine that ``BLPOP``s the list; when it pops a
message, it calls ``task.cancel()`` on the producer task.

A list is overkill for a single-shot signal, but it gives us:
- Trivial idempotency (multiple ``RPUSH`` are absorbed by one ``BLPOP``).
- Cross-instance delivery without pub/sub subscription state.
- Built-in TTL via ``EXPIRE`` on the key.
"""

from __future__ import annotations

from uuid import UUID

from redis.asyncio import Redis

from app.agents.runs.state import CancellationReason


def _control_key(run_id: UUID) -> str:
    return f"run:{run_id}:control"


class RunControl:
    DEFAULT_TTL_SECONDS: int = 30 * 60  # match the active-run TTL

    def __init__(self, redis: Redis):
        self.redis = redis

    async def signal_cancel(
        self, run_id: UUID, reason: CancellationReason = CancellationReason.USER
    ) -> None:
        """Idempotently signal cancellation. Worker picks it up via ``watch_cancel``."""
        key = _control_key(run_id)
        await self.redis.rpush(key, reason.value)
        await self.redis.expire(key, self.DEFAULT_TTL_SECONDS)

    async def watch_cancel(
        self, run_id: UUID, *, timeout: float = 0.0
    ) -> CancellationReason:
        """Block until a cancel signal arrives, then return the reason.

        ``timeout=0`` blocks forever (Redis BLPOP semantics). The worker spawns
        this as a sidecar task and ``await``s it concurrently with the astream
        loop.
        """
        result = await self.redis.blpop([_control_key(run_id)], timeout=timeout)
        if result is None:  # only happens with non-zero timeout
            raise TimeoutError
        _key, reason = result
        if isinstance(reason, bytes):
            reason = reason.decode()
        try:
            return CancellationReason(reason)
        except ValueError:
            return CancellationReason.SYSTEM

    async def clear(self, run_id: UUID) -> None:
        """Drop any leftover signal. Called once the run has reached a terminal state."""
        await self.redis.delete(_control_key(run_id))
