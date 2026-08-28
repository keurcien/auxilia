from datetime import UTC, datetime
from fnmatch import fnmatch

import pytest
from mcp.shared.auth import OAuthToken

from app.mcp.client import storage as storage_module
from app.mcp.client.storage import RedisTokenStorage, TokenStorageFactory


class _FakeRedis:
    """Minimal async Redis stand-in backed by a dict."""

    def __init__(self) -> None:
        self.store: dict[str, str] = {}

    async def get(self, key: str) -> str | None:
        return self.store.get(key)

    async def set(self, key: str, value: str, ex: int | None = None) -> None:
        self.store[key] = value

    async def delete(self, key: str) -> None:
        self.store.pop(key, None)

    async def scan_iter(self, match: str):
        for key in list(self.store):
            if fnmatch(key, match):
                yield key


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


def _factory() -> TokenStorageFactory:
    return TokenStorageFactory(redis=_FakeRedis())


def test_factory_borrows_the_app_wide_client_instead_of_opening_a_pool(monkeypatch):
    """P1-3: the factory used to build its own never-closed `ConnectionPool` in
    `__init__`, once per call at eight call sites. It must now hand back the
    lifespan-managed client so nothing leaks."""
    shared = _FakeRedis()
    monkeypatch.setattr(storage_module, "get_redis", lambda: shared)

    factory = TokenStorageFactory()

    assert factory.redis is shared
    assert factory.get_storage("u1", "s1").redis is shared


@pytest.mark.asyncio
async def test_list_connected_user_ids_matches_token_keys_only():
    factory = _factory()
    factory.redis.store = {
        "mcp:u1:s1:tokens": "t",
        "mcp:u1:s1:client_info": "c",
        "mcp:u2:s1:tokens": "t",
        "mcp:u3:s2:tokens": "t",  # other server
        "mcp:oauth_states:abc": "s",  # state key, not a connection
    }

    user_ids = await factory.list_connected_user_ids("s1")

    assert sorted(user_ids) == ["u1", "u2"]


@pytest.mark.asyncio
async def test_clear_user_server_data_scopes_to_one_user():
    factory = _factory()
    factory.redis.store = {
        "mcp:u1:s1:tokens": "t",
        "mcp:u1:s1:client_info": "c",
        "mcp:u2:s1:tokens": "t",
        "mcp:u1:s2:tokens": "t",
    }

    deleted = await factory.clear_user_server_data("u1", "s1")

    assert deleted == 2
    assert set(factory.redis.store) == {"mcp:u2:s1:tokens", "mcp:u1:s2:tokens"}


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
