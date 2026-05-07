"""Redis Streams transport for SSE chunks.

The producer writes every chunk to ``run:{run_id}:events`` via ``XADD``.
Consumers (HTTP handlers) read with ``XREAD``, optionally starting from a
client-supplied ``last_event_id`` so reattach replays missed events.

This module knows about Redis IDs and binary payloads only. It does **not**
know what an ``"end"`` event means or what shape ``payload`` has — that lives
in ``worker.py`` and ``stream.py``.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID

from redis.asyncio import Redis


DEFAULT_MAX_LEN: int = 5000  # ~ approx, see XADD MAXLEN ~ option
DEFAULT_TTL_SECONDS: int = 24 * 60 * 60
DEFAULT_BLOCK_MS: int = 25_000


def _events_key(run_id: UUID) -> str:
    return f"run:{run_id}:events"


class RunEvents:
    """Append-only event log per run, backed by a Redis Stream.

    Each event is stored as ``{"data": <json-string>}``. The Redis Stream ID
    (``<ms>-<seq>``) is what reattach uses as ``last_event_id``.
    """

    def __init__(self, redis: Redis):
        self.redis = redis

    async def append(
        self,
        run_id: UUID,
        event: dict[str, Any],
        *,
        maxlen: int = DEFAULT_MAX_LEN,
    ) -> str:
        """Append an event and return its Stream ID.

        Uses approximate ``MAXLEN ~`` trimming so the stream doesn't grow
        unbounded. If trimming drops events that a slow consumer hasn't read
        yet, the consumer will see a gap; the worker is responsible for
        emitting a ``truncated`` event in that case (see PRD §17.7).
        """
        return await self.redis.xadd(
            _events_key(run_id),
            {"data": json.dumps(event, default=str)},
            maxlen=maxlen,
            approximate=True,
        )

    async def read(
        self,
        run_id: UUID,
        *,
        last_id: str = "0",
        block_ms: int = DEFAULT_BLOCK_MS,
        count: int | None = 100,
    ) -> AsyncIterator[tuple[str, dict[str, Any]]]:
        """Yield ``(stream_id, event)`` tuples until the consumer cancels.

        ``last_id="0"`` replays from the beginning of the stream. Pass the most
        recent yielded ID to resume from where you left off.

        This generator never finishes on its own — the worker emits a sentinel
        event (``{"type": "end"}``) and the consumer breaks out of the loop on
        seeing it. Callers that want a hard timeout should wrap with
        ``asyncio.wait_for``.
        """
        cursor = last_id
        key = _events_key(run_id)
        while True:
            response = await self.redis.xread(
                {key: cursor}, count=count, block=block_ms
            )
            if not response:
                # block timeout with no new entries — continue polling.
                continue
            # response shape: [(key, [(id, {field: value}), ...])]
            _, entries = response[0]
            for entry_id, fields in entries:
                cursor = entry_id
                raw = fields.get("data") or fields.get(b"data")
                if isinstance(raw, bytes):
                    raw = raw.decode()
                if raw is None:
                    continue
                yield entry_id, json.loads(raw)

    async def expire(
        self, run_id: UUID, ttl_seconds: int = DEFAULT_TTL_SECONDS
    ) -> None:
        """Set TTL on the event stream. Call once after writing the ``end`` event."""
        await self.redis.expire(_events_key(run_id), ttl_seconds)

    async def delete(self, run_id: UUID) -> None:
        await self.redis.delete(_events_key(run_id))
