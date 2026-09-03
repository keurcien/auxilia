"""The reattachable event log — a Redis Stream of protocol events per run.

The worker `publish`es each Agent Streaming Protocol event the agent emits
(JSON-encoded by `app/agents/protocol/wire.py`, one event per entry);
subscribers read from a cursor and relay the stored events. Stream entry ids
*are* the resume cursor (and the client-visible `event_id`/`seq`), so reattach
replays only what a client missed.
"""

import asyncio
from collections.abc import AsyncGenerator
from contextlib import suppress

from redis.asyncio import Redis

from app.agents.protocol.wire import encode_terminal
from app.agents.runs import keys
from app.agents.runs.settings import run_settings
from app.agents.runs.state import RunStatus
from app.redis_client import get_redis


# Stream entry fields.
_DATA = "data"  # one JSON-encoded protocol event
_MIN_FLUSH_DELAY_SECONDS = 0.001
_END = "end"  # present ("1") only on the terminal entry


def terminal_entry(status: RunStatus, error: str | None = None) -> str:
    """The stored event that terminates a run's log: the root lifecycle
    `completed` / `failed` / `interrupted` event. Also produced synthetically
    when a subscriber attaches to a terminal run whose log has expired."""
    return encode_terminal(status.value, error=error)


class RunEventStream:
    """The event log for a single run."""

    def __init__(self, run_id: str, redis: Redis | None = None):
        self.run_id = run_id
        self.redis: Redis = redis or get_redis()
        self._key = keys.run_events_key(run_id)
        self._ttl_stamped = False

    async def publish(self, sse: str) -> str:
        """Append one encoded event; returns its stream entry id.

        The first append also stamps a safety TTL, so a stream can never
        outlive its run permanently. `RunService.finalize` normally sets that
        TTL, but it is skipped when the run row has vanished — a thread deleted
        mid-run CASCADEs the run away — and the log would then sit in Redis for
        ever. The worker's heartbeat pushes this TTL out every few seconds, so
        a long (or uncapped) run never expires its own live stream.
        """
        # ponytail: approximate MAXLEN keeps only the recent tail — a slow reattacher
        # on a trimmed cursor misses intermediate live chunks, but final state is
        # reconstructable from the checkpoint, so it's safe.
        if self._ttl_stamped:
            return await self.redis.xadd(
                self._key,
                {_DATA: sse},
                maxlen=run_settings.max_events,
                approximate=True,
            )
        async with self.redis.pipeline(transaction=False) as pipe:
            pipe.xadd(
                self._key,
                {_DATA: sse},
                maxlen=run_settings.max_events,
                approximate=True,
            )
            pipe.expire(self._key, run_settings.ttl_seconds)
            entry_id, _ = await pipe.execute()
        self._ttl_stamped = True
        return entry_id

    async def publish_many(self, chunks: list[str]) -> None:
        """Append several encoded events in one round trip.

        The whole point of `BufferedEventPublisher`: an awaited `XADD` per chunk
        means one Redis RTT per token, serialized with the agent stream, so a
        3,000-chunk run on managed Redis spends seconds of wall clock just
        waiting on the network (design review §3.4).
        """
        if not chunks:
            return
        async with self.redis.pipeline(transaction=False) as pipe:
            for sse in chunks:
                pipe.xadd(
                    self._key,
                    {_DATA: sse},
                    maxlen=run_settings.max_events,
                    approximate=True,
                )
            if not self._ttl_stamped:
                pipe.expire(self._key, run_settings.ttl_seconds)
            await pipe.execute()
        self._ttl_stamped = True

    async def touch_ttl(self) -> None:
        """Push the safety TTL out. Called from the worker's heartbeat so an
        in-flight run keeps its live stream however long it takes. A no-op
        while the log is still empty — EXPIRE on a missing key does nothing."""
        await self.redis.expire(self._key, run_settings.ttl_seconds)

    async def publish_end(self, status: RunStatus, error: str | None = None) -> str:
        """Append the terminal entry — the root terminal lifecycle event,
        flagged with `_END`. Subscribers stop after reading it."""
        # The terminal is always the newest entry → MAXLEN never trims it away.
        return await self.redis.xadd(
            self._key,
            {_DATA: terminal_entry(status, error), _END: "1"},
            maxlen=run_settings.max_events,
            approximate=True,
        )

    async def exists(self) -> bool:
        """Whether the log has any entries (False once the key TTLs away)."""
        return bool(await self.redis.exists(self._key))

    async def read_batch(
        self, cursor: str, *, block_ms: int = 15000
    ) -> tuple[str, list[str], bool] | None:
        """One blocking read from `cursor`: `(new_cursor, chunks, ended)`, or
        `None` if the block window elapsed with no new entries. Callers own
        the idle policy (keep waiting, or check the run record)."""
        result = await self.redis.xread({self._key: cursor}, block=block_ms, count=100)
        if not result:
            return None
        _, entries = result[0]
        chunks: list[str] = []
        ended = False
        for entry_id, fields in entries:
            cursor = entry_id
            data = fields.get(_DATA)
            if data is not None:
                chunks.append(data)
            if fields.get(_END):
                ended = True
        return cursor, chunks, ended

    async def read_batch_with_ids(
        self, cursor: str, *, block_ms: int = 15000
    ) -> tuple[str, list[tuple[str, str, bool]], bool] | None:
        """Like `read_batch`, but each chunk keeps its stream entry id:
        `(new_cursor, [(entry_id, chunk, is_end)], ended)`. The protocol
        stream endpoint derives the client's replay cursors (`event_id`/`seq`)
        from the entry ids, so it needs them alongside the payloads."""
        result = await self.redis.xread({self._key: cursor}, block=block_ms, count=100)
        if not result:
            return None
        _, entries = result[0]
        chunks: list[tuple[str, str, bool]] = []
        ended = False
        for entry_id, fields in entries:
            cursor = entry_id
            is_end = bool(fields.get(_END))
            data = fields.get(_DATA)
            if data is not None:
                chunks.append((entry_id, data, is_end))
            if is_end:
                ended = True
        return cursor, chunks, ended

    async def subscribe(
        self, last_event_id: str = "0", *, block_ms: int = 15000
    ) -> AsyncGenerator[str, None]:
        """Yield stored events from `last_event_id` onward until the terminal.

        `"0"` replays the whole log (fresh subscriber); pass a client's last seen
        entry id to resume after a reattach. Blocks for live entries in between.
        The worker (or reaper) always publishes the terminal on a finished run,
        so this generator is guaranteed to end.
        """
        cursor = last_event_id or "0"
        while True:
            batch = await self.read_batch(cursor, block_ms=block_ms)
            if batch is None:
                continue  # block window elapsed with no new entries — keep waiting
            cursor, chunks, ended = batch
            for chunk in chunks:
                yield chunk
            if ended:
                return


class BufferedEventPublisher:
    """Coalesces encoded events into pipelined appends.

    Bounded on both axes, because each bound fixes a different failure:

    * **chunks** caps memory and keeps one pipeline small.
    * **delay** caps *latency*. This is the one that matters for behaviour —
      these chunks are the tokens a user is watching appear. A count-only buffer
      would hold the tail of a slow response until enough tokens arrived, which
      is exactly backwards.

    A background flusher enforces the delay bound, so a run that goes quiet
    mid-stream (a long tool call) still ships what it has. Flush errors are not
    swallowed: the flusher records them and the next `publish`/`aclose` re-raises,
    so a Redis that has gone away still fails the run rather than silently
    dropping its output.

    Use as an async context manager — exiting drains the buffer, which is what
    orders the last events before `finalize`'s terminal entry.
    """

    def __init__(
        self,
        events: RunEventStream,
        *,
        max_chunks: int | None = None,
        max_delay_seconds: float | None = None,
    ):
        self._events = events
        self._max_chunks = max_chunks or run_settings.event_buffer_max_chunks
        delay = (
            max_delay_seconds
            if max_delay_seconds is not None
            else run_settings.event_buffer_max_delay_ms / 1000
        )
        # A non-positive delay would make the flusher's wait return instantly
        # and spin a CPU for the length of the run. Zero plainly means "ship
        # immediately", so honour that intent at the smallest delay that still
        # yields, rather than rejecting the configuration.
        self._max_delay = max(delay, _MIN_FLUSH_DELAY_SECONDS)
        self._buffer: list[str] = []
        self._lock = asyncio.Lock()
        self._flusher: asyncio.Task | None = None
        self._stopping = asyncio.Event()
        self._error: BaseException | None = None

    async def __aenter__(self) -> "BufferedEventPublisher":
        self._flusher = asyncio.create_task(self._flush_periodically())
        return self

    async def __aexit__(self, *_exc) -> None:
        await self.aclose()

    async def publish(self, sse: str) -> None:
        self._raise_pending()
        async with self._lock:
            self._buffer.append(sse)
            if len(self._buffer) >= self._max_chunks:
                await self._flush_locked()

    async def aclose(self) -> None:
        """Stop the flusher and drain whatever is left.

        The flusher is *asked* to stop and awaited, never cancelled.
        `_flush_locked` takes the buffer before awaiting the write, so
        cancelling mid-write would destroy chunks that are no longer in the
        buffer for the drain below to pick up — losing the tail of a run, or
        landing it after the terminal entry.
        """
        self._stopping.set()
        if self._flusher is not None:
            await self._flusher
            self._flusher = None
        async with self._lock:
            await self._flush_locked()
        self._raise_pending()

    def _raise_pending(self) -> None:
        if self._error is not None:
            error, self._error = self._error, None
            raise error

    async def _flush_locked(self) -> None:
        if not self._buffer:
            return
        chunks, self._buffer = self._buffer, []
        await self._events.publish_many(chunks)

    async def _flush_periodically(self) -> None:
        while not self._stopping.is_set():
            with suppress(TimeoutError):
                await asyncio.wait_for(self._stopping.wait(), timeout=self._max_delay)
            if self._stopping.is_set():
                return  # `aclose` owns the final drain
            try:
                async with self._lock:
                    await self._flush_locked()
            except Exception as exc:  # noqa: BLE001 — re-raised on the next publish/aclose
                self._error = exc
                return
