import pytest
from mcp.shared.auth import OAuthToken

from app.mcp.client.oauth_events import OAuthCompletion
from app.mcp.client.storage import RedisTokenStorage


async def test_changed_stored_token_recovers_a_missing_callback_marker(
    fake_shared_redis,
):
    storage = RedisTokenStorage("user", "server", redis=fake_shared_redis)
    await storage.set_tokens(OAuthToken(access_token="old-access", expires_in=3600))
    await storage.set_verifier("challenge", "verifier")
    completion = await OAuthCompletion.for_challenge(
        "https://auth.example?state=challenge",
        user_id="user",
        server_ids={"server"},
        redis=fake_shared_redis,
    )
    assert not await completion.completed()
    await storage.set_tokens(OAuthToken(access_token="new-access", expires_in=3600))
    await storage.delete_verifier("challenge")
    assert await completion.completed()


@pytest.mark.parametrize(
    "user_id,server_ids", [("other-user", {"server"}), ("user", {"other-server"})]
)
async def test_token_recovery_cannot_cross_user_or_server_scope(
    fake_shared_redis, user_id, server_ids
):
    storage = RedisTokenStorage("user", "server", redis=fake_shared_redis)
    await storage.set_verifier("challenge", "verifier")
    completion = await OAuthCompletion.for_challenge(
        "https://auth.example?state=challenge",
        user_id=user_id,
        server_ids=server_ids,
        redis=fake_shared_redis,
    )
    await storage.set_tokens(OAuthToken(access_token="new-access", expires_in=3600))
    assert not await completion.completed()


async def test_expired_stored_token_does_not_resume(fake_shared_redis):
    storage = RedisTokenStorage("user", "server", redis=fake_shared_redis)
    await storage.set_verifier("challenge", "verifier")
    completion = await OAuthCompletion.for_challenge(
        "https://auth.example?state=challenge",
        user_id="user",
        server_ids={"server"},
        redis=fake_shared_redis,
    )
    await storage.set_tokens(OAuthToken(access_token="expired-access", expires_in=-1))
    assert not await completion.completed()
