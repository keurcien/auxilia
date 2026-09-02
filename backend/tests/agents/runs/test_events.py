import asyncio
import json
from unittest.mock import AsyncMock

import pytest

from app.agents.runs.events import BufferedEventPublisher, RunEventStream
from app.agents.runs.settings import run_settings
from app.agents.runs.state import RunStatus


async def test_publish_and_full_replay(redis):
    events = RunEventStream("r1", redis)
    await events.publish('{"method": "values", "params": {"n": 1}}')
    await events.publish('{"method": "values", "params": {"n": 2}}')
    await events.publish_end(RunStatus.success)

    chunks = [c async for c in events.subscribe("0", block_ms=200)]
    assert len(chunks) == 3
    assert '"n": 1' in chunks[0]
    # The terminal entry is the root lifecycle event for the run's status.
    terminal = json.loads(chunks[-1])
    assert terminal["method"] == "lifecycle"
    assert terminal["params"]["data"] == {"event": "completed"}


async def test_terminal_entry_carries_the_error(redis):
    events = RunEventStream("r1", redis)
    await events.publish_end(RunStatus.error, "boom")
    [chunk] = [c async for c in events.subscribe("0", block_ms=200)]
    assert json.loads(chunk)["params"]["data"] == {"event": "failed", "error": "boom"}


async def test_stream_is_capped_at_max_events(redis, monkeypatch):
    """A runaway run can't grow its event stream without bound — MAXLEN trims it.

    Cap and volume span several Redis stream macro nodes (~100 entries each) so
    approximate `MAXLEN ~` trimming actually fires on a real server — it evicts
    whole nodes, not single entries — and not only on fakeredis's exact trim.
    """
    monkeypatch.setattr(run_settings, "max_events", 100)
    events = RunEventStream("r1", redis)
    for i in range(500):
        await events.publish(f"data: {i}\n\n")

    length = await redis.xlen(events._key)
    assert length < 500  # trimming happened
    # Bounded, but tolerant of node-granular approximate trimming on real Redis.
    assert length <= run_settings.max_events * 2


async def test_subscribe_resumes_after_cursor(redis):
    events = RunEventStream("r1", redis)
    first_id = await events.publish("a")
    await events.publish("b")
    await events.publish_end(RunStatus.success)

    # Resuming after the first entry must skip it (the reattach replay window).
    chunks = [c async for c in events.subscribe(first_id, block_ms=200)]
    assert "a" not in chunks
    assert chunks[0] == "b"


async def test_first_publish_stamps_a_safety_ttl(redis):
    """§5.4: a stream must never be able to outlive its run permanently.

    `RunService.finalize` normally sets the TTL, but it is skipped when the run
    row has vanished — a thread deleted mid-run CASCADEs the run away — and the
    log would then sit in Redis for ever with no expiry at all.
    """
    events = RunEventStream("r-ttl", redis)

    await events.publish("event: messages\ndata: 1\n\n")

    assert 0 < await redis.ttl(events._key) <= run_settings.ttl_seconds


async def test_touch_ttl_keeps_a_long_run_from_expiring_its_own_stream(redis):
    """The worker's heartbeat calls this. Without it, a run longer than the
    safety TTL (or an uncapped one) would lose its live stream mid-flight."""
    events = RunEventStream("r-touch", redis)
    await events.publish("a")
    await redis.expire(events._key, 5)

    await events.touch_ttl()

    assert await redis.ttl(events._key) > 5


async def test_touch_ttl_on_an_empty_log_is_a_noop(redis):
    """The heartbeat starts before the first chunk is published."""
    await RunEventStream("r-empty", redis).touch_ttl()  # must not raise


# ---------------------------------------------------------------------------
# BufferedEventPublisher (P1-11 / §3.4)
# ---------------------------------------------------------------------------


async def test_a_full_buffer_costs_no_per_chunk_round_trip(redis, count_appends):
    """32 chunks used to be 32 awaited XADDs, each one a Redis RTT the next
    token waited on. They now ride in a single pipeline."""
    appends = count_appends(redis)
    events = RunEventStream("r-buf", redis)

    async with BufferedEventPublisher(
        events, max_chunks=32, max_delay_seconds=3600
    ) as publisher:
        for i in range(32):
            await publisher.publish(f"data: {i}\n\n")

    assert appends["xadd"] == 0  # nothing blocked per chunk
    assert await redis.xlen(events._key) == 32


async def test_the_delay_bound_ships_a_partial_buffer(redis, until):
    """The bound that matters for behaviour: these chunks are the tokens a user
    is watching appear, so a run that goes quiet mid-stream (a long tool call)
    must not sit on them until the buffer happens to fill."""
    events = RunEventStream("r-delay", redis)

    async with BufferedEventPublisher(
        events, max_chunks=1000, max_delay_seconds=0.001
    ) as publisher:
        await publisher.publish("data: only\n\n")

        async def _shipped() -> bool:
            return await redis.xlen(events._key) > 0

        await until(_shipped, what="the delay bound to ship a partial buffer")

    assert await redis.xlen(events._key) == 1


async def test_closing_drains_the_buffer(redis):
    """What orders the last chunks ahead of finalize's end sentinel."""
    events = RunEventStream("r-drain", redis)

    async with BufferedEventPublisher(
        events, max_chunks=1000, max_delay_seconds=3600
    ) as publisher:
        await publisher.publish("a")
        await publisher.publish("b")
        assert await redis.xlen(events._key) == 0  # still buffered

    assert await redis.xlen(events._key) == 2


async def test_chunk_order_is_preserved(redis):
    events = RunEventStream("r-order", redis)

    async with BufferedEventPublisher(
        events, max_chunks=4, max_delay_seconds=3600
    ) as publisher:
        for i in range(10):
            await publisher.publish(f"data: {i}\n\n")
    await events.publish_end(RunStatus.success)

    chunks = [c async for c in events.subscribe("0", block_ms=200)]
    assert chunks[:-1] == [f"data: {i}\n\n" for i in range(10)]
    assert '"lifecycle"' in chunks[-1]  # the terminal entry closes the log


async def test_a_flush_failure_surfaces_rather_than_dropping_output(redis):
    """A Redis that has gone away must still fail the run. Buffering moves the
    write off the publish call, so the error has to be carried back."""
    events = RunEventStream("r-fail", redis)
    events.publish_many = AsyncMock(side_effect=ConnectionError("redis down"))

    with pytest.raises(ConnectionError, match="redis down"):
        async with BufferedEventPublisher(
            events, max_chunks=1, max_delay_seconds=3600
        ) as publisher:
            await publisher.publish("a")


async def test_a_background_flush_failure_surfaces_on_close(redis, until):
    events = RunEventStream("r-fail2", redis)
    events.publish_many = AsyncMock(side_effect=ConnectionError("redis down"))

    publisher = BufferedEventPublisher(events, max_chunks=1000, max_delay_seconds=0.001)
    await publisher.__aenter__()
    await publisher.publish("a")

    async def _attempted() -> bool:
        return events.publish_many.await_count > 0

    await until(_attempted, what="the background flusher to attempt a write")

    with pytest.raises(ConnectionError, match="redis down"):
        await publisher.aclose()


async def test_closing_never_drops_a_write_that_is_already_in_flight(redis, until):
    """`_flush_locked` takes the buffer *before* awaiting the write, so a close
    that cancels the flusher mid-write destroys chunks the drain can no longer
    see — the tail of a run, silently lost or landing after the end sentinel."""
    events = RunEventStream("r-race", redis)
    real_publish_many = events.publish_many
    in_flight = asyncio.Event()
    release = asyncio.Event()

    async def _slow_publish_many(chunks):
        in_flight.set()
        await release.wait()
        await real_publish_many(chunks)

    events.publish_many = _slow_publish_many

    publisher = BufferedEventPublisher(events, max_chunks=1000, max_delay_seconds=0.001)
    await publisher.__aenter__()
    await publisher.publish("first")

    async def _writing() -> bool:
        return in_flight.is_set()

    await until(_writing, what="the periodic flusher to start writing")

    closing = asyncio.create_task(publisher.aclose())
    await asyncio.sleep(0)  # let aclose reach its await
    release.set()
    await closing

    await events.publish_end(RunStatus.success)
    chunks = [c async for c in events.subscribe("0", block_ms=200)]
    assert "first" in chunks
    assert chunks.index("first") < len(chunks) - 1  # ahead of the end sentinel


async def test_a_zero_delay_does_not_spin_the_flusher(redis):
    """A configured 0 means "ship immediately", not "burn a core for the length
    of the run" — the flusher's wait would return instantly forever."""
    events = RunEventStream("r-zero", redis)

    publisher = BufferedEventPublisher(events, max_chunks=1000, max_delay_seconds=0)

    assert publisher._max_delay > 0
