from unittest.mock import AsyncMock, MagicMock

from app.integrations.slack import utils


async def test_user_info_cache_avoids_slack_roundtrip_and_expires(
    monkeypatch, fake_shared_redis
):
    response = MagicMock()
    response.json.return_value = {
        "ok": True,
        "user": {
            "id": "U1",
            "name": "member",
            "profile": {"email": "member@example.com"},
        },
    }
    client = AsyncMock()
    client.get.return_value = response
    context = AsyncMock()
    context.__aenter__.return_value = client
    monkeypatch.setattr(utils.httpx, "AsyncClient", lambda: context)
    first = await utils.get_user_info("U1")
    second = await utils.get_user_info("U1")
    assert first == second
    client.get.assert_awaited_once()
    keys = await fake_shared_redis.keys("slack:user-info:*")
    assert len(keys) == 1
    assert 0 < await fake_shared_redis.ttl(keys[0]) <= 300
    await fake_shared_redis.delete(keys[0])
    await utils.get_user_info("U1")
    assert client.get.await_count == 2
