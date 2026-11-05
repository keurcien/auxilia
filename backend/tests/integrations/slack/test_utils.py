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


async def test_invalid_cached_identity_does_not_log_personal_data(monkeypatch, caplog):
    cache = AsyncMock()
    # Missing required fields: Pydantic would echo this entire input in its traceback.
    cache.get.return_value = '{"profile": {"email": "private@example.com"}}'
    monkeypatch.setattr(utils, "get_redis", lambda: cache)
    response = MagicMock()
    response.json.return_value = {
        "ok": True,
        "user": {
            "id": "U1",
            "name": "member",
            "profile": {"email": "private@example.com"},
        },
    }
    client = AsyncMock()
    client.get.return_value = response
    context = AsyncMock()
    context.__aenter__.return_value = client
    monkeypatch.setattr(utils.httpx, "AsyncClient", lambda: context)

    user = await utils.get_user_info("U1")
    assert user.profile.email == "private@example.com"
    client.get.assert_awaited_once()
    assert "failed validation" in caplog.text
    assert "private@example.com" not in caplog.text
    assert all(record.exc_info is None for record in caplog.records)

    # Fresh API payloads must not leak through the generic exception handler either.
    caplog.clear()
    cache.get.return_value = None
    response.json.return_value = {
        "ok": True,
        "user": {"profile": {"email": "private@example.com"}},
    }
    assert await utils.get_user_info("U1") is None
    assert "users.info payload failed validation" in caplog.text
    assert "private@example.com" not in caplog.text
    assert all(record.exc_info is None for record in caplog.records)


async def test_cache_infrastructure_failures_keep_tracebacks(monkeypatch, caplog):
    from redis.exceptions import RedisError

    cache = AsyncMock()
    cache.get.side_effect = RedisError("cache unavailable")
    cache.set.side_effect = TimeoutError("cache write timed out")
    monkeypatch.setattr(utils, "get_redis", lambda: cache)
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

    assert await utils.get_user_info("U1") is not None
    records = [r for r in caplog.records if "Slack identity cache" in r.message]
    assert len(records) == 2
    assert isinstance(records[0].exc_info[1], RedisError)
    assert isinstance(records[1].exc_info[1], TimeoutError)
