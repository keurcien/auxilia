from app.agents.runs.events import RunEventStream
from app.agents.runs.settings import run_settings
from app.agents.runs.state import RunStatus


async def test_publish_and_full_replay(redis):
    events = RunEventStream("r1", redis)
    await events.publish("event: messages\ndata: 1\n\n")
    await events.publish("event: messages\ndata: 2\n\n")
    await events.publish_end(RunStatus.success)

    chunks = [c async for c in events.subscribe("0", block_ms=200)]
    assert len(chunks) == 3
    assert "data: 1" in chunks[0]
    assert "event: end" in chunks[-1]
    assert "success" in chunks[-1]


async def test_stream_is_capped_at_max_events(redis, monkeypatch):
    """A runaway run can't grow its event stream without bound — MAXLEN trims it."""
    monkeypatch.setattr(run_settings, "max_events", 5)
    events = RunEventStream("r1", redis)
    for i in range(20):
        await events.publish(f"data: {i}\n\n")

    # Approximate trimming keeps roughly the cap, never the full 20.
    length = await redis.xlen(events._key)
    assert length < 20
    assert length <= run_settings.max_events + 5


async def test_subscribe_resumes_after_cursor(redis):
    events = RunEventStream("r1", redis)
    first_id = await events.publish("a")
    await events.publish("b")
    await events.publish_end(RunStatus.success)

    # Resuming after the first entry must skip it (the reattach replay window).
    chunks = [c async for c in events.subscribe(first_id, block_ms=200)]
    assert "a" not in chunks
    assert chunks[0] == "b"
