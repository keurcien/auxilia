import asyncio
from uuid import uuid4

import pytest

from app.agents.runs.events import RunEvents


@pytest.mark.asyncio
class TestAppendAndRead:
    async def test_round_trip_one_event(self, redis):
        events = RunEvents(redis)
        rid = uuid4()
        stream_id = await events.append(rid, {"type": "messages", "delta": "hi"})
        assert stream_id

        gen = events.read(rid, last_id="0", block_ms=100, count=10)
        seen_id, seen = await asyncio.wait_for(gen.__anext__(), timeout=1)
        assert seen_id == stream_id
        assert seen == {"type": "messages", "delta": "hi"}
        await gen.aclose()

    async def test_replay_preserves_order(self, redis):
        events = RunEvents(redis)
        rid = uuid4()
        ids = [
            await events.append(rid, {"type": "messages", "delta": str(i)})
            for i in range(5)
        ]

        gen = events.read(rid, last_id="0", block_ms=100, count=10)
        seen: list[tuple[str, dict]] = []
        for _ in range(5):
            seen.append(await asyncio.wait_for(gen.__anext__(), timeout=1))
        await gen.aclose()

        assert [s[0] for s in seen] == ids
        assert [s[1]["delta"] for s in seen] == ["0", "1", "2", "3", "4"]

    async def test_resume_from_last_id_skips_history(self, redis):
        events = RunEvents(redis)
        rid = uuid4()
        first_id = await events.append(rid, {"type": "messages", "delta": "before"})
        await events.append(rid, {"type": "messages", "delta": "after"})

        gen = events.read(rid, last_id=first_id, block_ms=100, count=10)
        sid, evt = await asyncio.wait_for(gen.__anext__(), timeout=1)
        await gen.aclose()
        assert evt["delta"] == "after"
        assert sid != first_id


@pytest.mark.asyncio
class TestExpire:
    async def test_expire_sets_ttl(self, redis):
        events = RunEvents(redis)
        rid = uuid4()
        await events.append(rid, {"type": "end"})
        await events.expire(rid, ttl_seconds=60)
        ttl = await redis.ttl(f"run:{rid}:events")
        assert 0 < ttl <= 60
