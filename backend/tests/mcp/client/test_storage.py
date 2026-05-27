from datetime import UTC, datetime

import pytest
from mcp.shared.auth import OAuthToken

from app.mcp.client.storage import RedisTokenStorage


class _FakeRedis:
    """Minimal async Redis stand-in backed by a dict."""

    def __init__(self) -> None:
        self.store: dict[str, str] = {}

    async def get(self, key: str) -> str | None:
        return self.store.get(key)

    async def set(self, key: str, value: str, ex: int | None = None) -> None:
        self.store[key] = value


def _storage() -> RedisTokenStorage:
    return RedisTokenStorage("u1", "s1", redis=_FakeRedis())


@pytest.mark.asyncio
async def test_refresh_without_refresh_token_preserves_stored_one():
    """Google omits refresh_token on refresh; the stored one must survive."""
    storage = _storage()

    await storage.set_tokens(
        OAuthToken(access_token="AT1", expires_in=3600, refresh_token="RT1")
    )
    # Simulate a Google refresh response: new access token, no refresh token.
    await storage.set_tokens(OAuthToken(access_token="AT2", expires_in=3600))

    tokens = await storage.get_tokens()
    assert tokens is not None
    assert tokens.access_token == "AT2"
    assert tokens.refresh_token == "RT1"


@pytest.mark.asyncio
async def test_set_tokens_keeps_a_newly_issued_refresh_token():
    """A genuinely new refresh_token must not be shadowed by the old one."""
    storage = _storage()

    await storage.set_tokens(
        OAuthToken(access_token="AT1", expires_in=3600, refresh_token="RT1")
    )
    await storage.set_tokens(
        OAuthToken(access_token="AT2", expires_in=3600, refresh_token="RT2")
    )

    tokens = await storage.get_tokens()
    assert tokens is not None
    assert tokens.refresh_token == "RT2"


@pytest.mark.asyncio
async def test_set_tokens_without_existing_token_stores_as_is():
    """No prior token + no incoming refresh_token: store as-is, no crash."""
    storage = _storage()

    await storage.set_tokens(OAuthToken(access_token="AT1", expires_in=3600))

    tokens = await storage.get_tokens()
    assert tokens is not None
    assert tokens.refresh_token is None


@pytest.mark.asyncio
async def test_set_tokens_updates_expiry_on_refresh():
    """expires_at must track the refresh response's expires_in, not the old value."""
    storage = _storage()

    await storage.set_tokens(
        OAuthToken(access_token="AT1", expires_in=10, refresh_token="RT1")
    )
    await storage.set_tokens(OAuthToken(access_token="AT2", expires_in=3600))

    stored = await storage.get_stored_token()
    assert stored is not None
    assert stored.expires_at is not None
    remaining = (stored.expires_at - datetime.now(UTC)).total_seconds()
    assert remaining > 60
