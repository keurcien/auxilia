import pytest
from fakeredis import FakeServer, aioredis


@pytest.fixture
async def redis():
    """A fresh in-memory async Redis per test (streams + Lua supported).

    An explicit shared `FakeServer` makes every pooled connection see the same
    data — without it, a blocking pop holds one connection and concurrent
    reads land on a different, empty fake server.
    """
    client = aioredis.FakeRedis(server=FakeServer(), decode_responses=True)
    await client.flushall()
    yield client
    await client.aclose()
