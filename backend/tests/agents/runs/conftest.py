import fakeredis.aioredis
import pytest_asyncio


@pytest_asyncio.fixture
async def redis():
    """Per-test fakeredis instance. Auto-closed after each test."""
    client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    try:
        yield client
    finally:
        await client.aclose()
