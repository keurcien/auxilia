"""Behavioural tests for app/mcp/client/connectivity.py that don't need a live
MCP server: the authorized-vs-reachable split and the stateless probe's OAuth
guard. The provider-construction tests live in tests/mcp/servers/test_service.py;
pagination guards in tests/mcp/servers/test_connect_to_server.py.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from fakeredis import FakeServer, aioredis

from app.mcp.client import connectivity
from app.mcp.servers.models import MCPAuthType


def _server(auth_type, server_id="s1"):
    return SimpleNamespace(
        id=server_id, url="https://mcp.example.com/mcp", auth_type=auth_type
    )


async def test_is_authorized_true_for_non_oauth_without_touching_network():
    # none/api_key hold no per-user credential, so authorization is a no-op:
    # no provider is built and no token lookup happens.
    with patch.object(connectivity, "build_oauth_provider") as build:
        assert await connectivity.is_authorized(_server(MCPAuthType.none), "u1") is True
        assert (
            await connectivity.is_authorized(_server(MCPAuthType.api_key), "u1") is True
        )
    build.assert_not_called()


async def test_is_authorized_oauth_refresh_uses_ensure_valid_token():
    provider = SimpleNamespace(ensure_valid_token=AsyncMock(return_value=True))
    with patch.object(
        connectivity, "build_oauth_provider", AsyncMock(return_value=provider)
    ):
        assert (
            await connectivity.is_authorized(_server(MCPAuthType.oauth2), "u1") is True
        )
    provider.ensure_valid_token.assert_awaited_once()


async def test_is_authorized_oauth_no_refresh_checks_stored_token_only():
    """`refresh=False` is a storage read — no provider, no network."""
    storage = SimpleNamespace(get_tokens=AsyncMock(return_value=None))
    factory = SimpleNamespace(get_storage=lambda *_args: storage)
    with (
        patch.object(connectivity, "TokenStorageFactory", lambda: factory),
        patch.object(connectivity, "build_oauth_provider", AsyncMock()) as build,
    ):
        result = await connectivity.is_authorized(
            _server(MCPAuthType.oauth2), "u1", refresh=False
        )
    assert result is False
    storage.get_tokens.assert_awaited_once()
    build.assert_not_awaited()


async def test_probe_candidate_rejects_oauth_before_saving():
    result = await connectivity.probe_candidate(
        "https://mcp.example.com/mcp", MCPAuthType.oauth2
    )
    assert result.reachable is False
    assert result.oauth_required is False
    assert "saved" in (result.error or "")


# ---------------------------------------------------------------------------
# probe_authorization (P1-6) — the single concurrent, fail-open, memoized probe
# ---------------------------------------------------------------------------


@pytest.fixture
async def probe_redis(monkeypatch):
    client = aioredis.FakeRedis(server=FakeServer(), decode_responses=True)
    monkeypatch.setattr(connectivity, "get_redis", lambda: client)
    yield client
    await client.aclose()


async def test_probe_returns_empty_without_touching_redis():
    with patch.object(connectivity, "get_redis") as get_redis:
        assert await connectivity.probe_authorization([], "u1") == {}
    get_redis.assert_not_called()


async def test_probe_runs_concurrently(probe_redis):
    """Sequential probes are what made the polled readiness endpoint slow: each
    one can do a token-refresh POST. All three must be in flight at once."""
    import asyncio

    servers = [_server(MCPAuthType.oauth2, uuid4()) for _ in range(3)]
    in_flight = 0
    peak = 0

    async def _slow(server, user_id, **_):
        nonlocal in_flight, peak
        in_flight += 1
        peak = max(peak, in_flight)
        await asyncio.sleep(0)
        in_flight -= 1
        return True

    with patch.object(connectivity, "is_authorized", _slow):
        result = await connectivity.probe_authorization(servers, "u1")

    assert peak == 3
    assert result == {s.id: True for s in servers}


async def test_probe_fails_open_when_one_probe_raises(probe_redis):
    """Readiness is a convenience, not a security boundary — the server itself
    rejects unauthorized calls. An IdP outage must not make agents unlaunchable."""
    good, bad = (
        _server(MCPAuthType.oauth2, uuid4()),
        _server(MCPAuthType.oauth2, uuid4()),
    )

    async def _flaky(server, user_id, **_):
        if server.id == bad.id:
            raise RuntimeError("IdP is down")
        return False

    with patch.object(connectivity, "is_authorized", _flaky):
        result = await connectivity.probe_authorization([good, bad], "u1")

    assert result == {good.id: False, bad.id: True}


async def test_probe_memoizes_a_positive_so_the_polling_loop_stops_refreshing(
    probe_redis,
):
    server = _server(MCPAuthType.oauth2, uuid4())
    probe = AsyncMock(return_value=True)

    with patch.object(connectivity, "is_authorized", probe):
        first = await connectivity.probe_authorization([server], "u1")
        second = await connectivity.probe_authorization([server], "u1")

    assert first == second == {server.id: True}
    probe.assert_awaited_once()
    assert await probe_redis.ttl(f"mcp:u1:{server.id}:authprobe") > 0


async def test_probe_does_not_memoize_a_negative(probe_redis):
    """A user who has just finished the OAuth popup must not keep reading as
    disconnected for the length of the TTL."""
    server = _server(MCPAuthType.oauth2, uuid4())
    probe = AsyncMock(return_value=False)

    with patch.object(connectivity, "is_authorized", probe):
        await connectivity.probe_authorization([server], "u1")
        await connectivity.probe_authorization([server], "u1")

    assert probe.await_count == 2


async def test_probe_cache_is_scoped_per_user(probe_redis):
    server = _server(MCPAuthType.oauth2, uuid4())
    probe = AsyncMock(return_value=True)

    with patch.object(connectivity, "is_authorized", probe):
        await connectivity.probe_authorization([server], "alice")
        await connectivity.probe_authorization([server], "bob")

    assert probe.await_count == 2


async def test_probe_survives_a_redis_outage(monkeypatch):
    """A cache failure degrades to probing, never to failing — this sits on the
    endpoint the frontend polls."""
    broken = SimpleNamespace(
        mget=AsyncMock(side_effect=RuntimeError("redis down")),
        pipeline=lambda **_: (_ for _ in ()).throw(RuntimeError("redis down")),
    )
    monkeypatch.setattr(connectivity, "get_redis", lambda: broken)
    server = _server(MCPAuthType.oauth2, uuid4())

    with patch.object(connectivity, "is_authorized", AsyncMock(return_value=True)):
        result = await connectivity.probe_authorization([server], "u1")

    assert result == {server.id: True}


async def test_probe_dedupes_a_server_bound_by_both_parent_and_subagent(probe_redis):
    server = _server(MCPAuthType.oauth2, uuid4())
    probe = AsyncMock(return_value=True)

    with patch.object(connectivity, "is_authorized", probe):
        result = await connectivity.probe_authorization([server, server], "u1")

    assert result == {server.id: True}
    probe.assert_awaited_once()


async def test_the_probe_cache_lives_where_the_purges_can_reach_it(probe_redis):
    """The cache key must sit inside `mcp:{user}:{server}:...`, the layout
    `TokenStorageFactory.clear_server_data` / `clear_user_server_data` scan
    (`mcp:*:{server_id}:*`). Outside it, the key survives every purge — so a
    user who revoked their connection, or a server whose URL just changed, would
    keep reading as authorized from a cache nothing knows how to invalidate."""
    from app.mcp.client.storage import TokenStorageFactory

    server = _server(MCPAuthType.oauth2, uuid4())
    with patch.object(connectivity, "is_authorized", AsyncMock(return_value=True)):
        await connectivity.probe_authorization([server], "u1")
    assert await probe_redis.exists(f"mcp:u1:{server.id}:authprobe")

    deleted = await TokenStorageFactory(redis=probe_redis).clear_server_data(
        str(server.id)
    )

    assert deleted >= 1
    assert not await probe_redis.exists(f"mcp:u1:{server.id}:authprobe")


async def test_a_stalled_redis_does_not_hang_the_polled_endpoint(monkeypatch):
    """Fail-open only catches raised errors. A Redis that accepts the connection
    then stalls would hang readiness and the run-start preflight indefinitely."""
    import asyncio as _asyncio

    async def _never_returns(*_args, **_kwargs):
        await _asyncio.Event().wait()

    class _StallingPipeline:
        """Stalls on entry, the way a wedged connection would — so the write
        path is timed out rather than failing on a type error."""

        async def __aenter__(self):
            await _asyncio.Event().wait()

        async def __aexit__(self, *_exc):
            return False

    monkeypatch.setattr(connectivity, "_CACHE_TIMEOUT_SECONDS", 0.01)
    monkeypatch.setattr(
        connectivity,
        "get_redis",
        lambda: SimpleNamespace(
            mget=_never_returns, pipeline=lambda **_kw: _StallingPipeline()
        ),
    )
    server = _server(MCPAuthType.oauth2, uuid4())

    with patch.object(connectivity, "is_authorized", AsyncMock(return_value=True)):
        async with _asyncio.timeout(2):
            result = await connectivity.probe_authorization([server], "u1")

    assert result == {server.id: True}
