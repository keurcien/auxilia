"""Tests for the Slack webhook edge.

These cover the three failure modes documented in the backend design review §5.6,
each of which had bitten (or was one malformed callback away from biting) the only
Slack execution path we have:

  1. handler tasks garbage-collected mid-flight (no strong reference),
  2. dedup held per-process, so a Slack retry landing on a second Cloud Run
     instance ran the agent twice,
  3. `payload.event` dereferenced unconditionally though it is Optional, turning
     one malformed callback into a retry loop of 500s.
"""

import asyncio
import json

import pytest
from fastapi import Request
from fastapi.testclient import TestClient

from app.integrations.slack import router as router_module
from app.integrations.slack.utils import verify_slack_signature
from app.main import app


@pytest.fixture
def slack_client():
    """A client whose Slack signature check is bypassed."""

    async def override(request: Request) -> bytes:
        # The real dependency verifies the HMAC and returns the raw body; here we
        # skip verification but must still hand the router the body it parses.
        return await request.body()

    app.dependency_overrides[verify_slack_signature] = override
    client = TestClient(app)
    yield client
    app.dependency_overrides.clear()


@pytest.fixture
def spawned(monkeypatch):
    """Record what the router spawns instead of actually running it."""
    calls: list[str] = []

    def fake_spawn(coro):
        calls.append(getattr(coro, "__qualname__", repr(coro)))
        coro.close()  # never awaited; don't warn

    monkeypatch.setattr(router_module, "_spawn", fake_spawn)
    return calls


@pytest.fixture
def claimed(monkeypatch):
    """Stub the Redis dedup claim; the list records the keys claimed."""
    keys: list[str] = []
    verdicts: list[bool] = []

    async def fake_claim(key: str) -> bool:
        keys.append(key)
        return verdicts.pop(0) if verdicts else True

    monkeypatch.setattr(router_module, "_claim_delivery", fake_claim)
    return keys, verdicts


def _post(client, payload):
    return client.post("/integrations/slack/events", content=json.dumps(payload))


def test_url_verification_echoes_the_challenge(slack_client):
    response = _post(slack_client, {"type": "url_verification", "challenge": "abc"})

    assert response.status_code == 200
    assert response.json() == {"challenge": "abc"}


def test_callback_without_an_event_is_acked_not_500(slack_client, spawned):
    """`event` is Optional. A 500 here makes Slack retry the same broken
    callback for its whole retry window."""
    response = _post(slack_client, {"type": "event_callback"})

    assert response.status_code == 200
    assert response.json() == {"ok": True}
    assert spawned == []


def test_message_event_spawns_a_handler(slack_client, spawned, claimed):
    keys, _ = claimed

    response = _post(
        slack_client,
        {
            "type": "event_callback",
            "team_id": "T1",
            "event": {
                "type": "message",
                "user": "U1",
                "channel": "C1",
                "ts": "1.0",
                "text": "hi",
            },
        },
    )

    assert response.status_code == 200
    assert len(spawned) == 1
    assert keys == ["slack:event:T1:C1:1.0"]


def test_unclaimed_duplicate_delivery_is_dropped(slack_client, spawned, claimed):
    """A Slack retry whose claim is already held must not run the agent again."""
    _, verdicts = claimed
    verdicts.append(False)

    response = _post(
        slack_client,
        {
            "type": "event_callback",
            "team_id": "T1",
            "event": {"type": "message", "user": "U1", "channel": "C1", "ts": "1.0"},
        },
    )

    assert response.status_code == 200
    assert spawned == []


def test_bot_messages_are_ignored_before_the_dedup_claim(
    slack_client, spawned, claimed
):
    """Don't burn a dedup key (or echo ourselves) on our own bot's messages."""
    keys, _ = claimed

    response = _post(
        slack_client,
        {
            "type": "event_callback",
            "event": {
                "type": "message",
                "user": "U1",
                "bot_id": "B1",
                "channel": "C1",
                "ts": "1.0",
            },
        },
    )

    assert response.status_code == 200
    assert spawned == []
    assert keys == []


def test_assistant_thread_started_spawns_without_dedup(slack_client, spawned, claimed):
    keys, _ = claimed

    response = _post(
        slack_client,
        {
            "type": "event_callback",
            "event": {"type": "assistant_thread_started"},
        },
    )

    assert response.status_code == 200
    assert len(spawned) == 1
    assert keys == []


async def test_spawn_keeps_a_strong_reference_until_the_task_finishes():
    """The event loop holds only a weak reference to a running task, so the
    router must own one or CPython may collect the handler mid-flight."""
    started = asyncio.Event()
    release = asyncio.Event()

    async def handler() -> None:
        started.set()
        await release.wait()

    router_module._spawn(handler())
    await started.wait()

    assert len(router_module._background_tasks) == 1

    release.set()
    await asyncio.sleep(0)  # let the task finish and the callback run
    await asyncio.sleep(0)

    assert router_module._background_tasks == set()


async def test_claim_delivery_fails_open_when_redis_is_down(monkeypatch):
    """Dropping the user's message is worse than a duplicate reply."""
    from redis.exceptions import RedisError

    class DeadRedis:
        async def set(self, *args, **kwargs):
            raise RedisError("connection refused")

    monkeypatch.setattr(router_module, "get_redis", lambda: DeadRedis())

    assert await router_module._claim_delivery("slack:event:x") is True


async def test_claim_delivery_uses_set_nx_ex(monkeypatch):
    recorded: dict = {}

    class FakeRedis:
        async def set(self, key, value, nx=False, ex=None):
            recorded.update(key=key, value=value, nx=nx, ex=ex)
            return True

    monkeypatch.setattr(router_module, "get_redis", lambda: FakeRedis())

    assert await router_module._claim_delivery("slack:event:x") is True
    assert recorded["nx"] is True
    assert recorded["ex"] == router_module._DEDUP_TTL_SECONDS
