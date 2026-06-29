"""Tests for the worker-side Slack delivery consumer."""

from contextlib import asynccontextmanager
from types import SimpleNamespace

import app.integrations.slack.consumer as consumer_mod
from app.agents.runs.state import RunRecord
from app.integrations.slack.consumer import (
    SlackRunConsumer,
    build_slack_delivery,
    build_slack_run_consumer,
)


def _record(delivery=None) -> RunRecord:
    return RunRecord(id="r1", thread_id="t1", user_id="u1", delivery=delivery)


def _slack_delivery() -> dict:
    return build_slack_delivery(
        channel_id="C1", thread_ts="t1", slack_user_id="U1", team_id="T1"
    )


class _FakeStreamer:
    def __init__(self):
        self.appended: list[str] = []
        self.stopped = False
        self.kwargs: dict = {}

    async def append(self, markdown_text: str):
        self.appended.append(markdown_text)

    async def stop(self):
        self.stopped = True


class _FakeClient:
    def __init__(self):
        self.streamer = _FakeStreamer()
        self.posts: list[dict] = []

    async def chat_stream(self, **kwargs):
        self.streamer.kwargs = kwargs
        return self.streamer

    async def chat_postMessage(self, **kwargs):
        self.posts.append(kwargs)


def _sse_stream(*chunks):
    async def _gen(*_args, **_kwargs):
        for chunk in chunks:
            yield chunk

    return _gen


# ── Factory ──────────────────────────────────────────────────────────


def test_factory_skips_non_slack_runs():
    assert build_slack_run_consumer(_record(None)) is None
    assert build_slack_run_consumer(_record({"channel": "web"})) is None


def test_factory_builds_for_slack_runs():
    consumer = build_slack_run_consumer(_record(_slack_delivery()))
    assert isinstance(consumer, SlackRunConsumer)


# ── Delivery behavior ──────────────────────────────────────────────────


async def test_consumer_streams_text_and_posts_link_on_success(monkeypatch):
    monkeypatch.setattr(
        consumer_mod.RunService,
        "stream",
        _sse_stream(
            'event: messages\ndata: [{"type": "AIMessageChunk", "content": "Hi", "id": "a"}, {}]\n\n',
            'event: end\ndata: {"status": "success"}\n\n',
        ),
    )

    @asynccontextmanager
    async def _session():
        yield SimpleNamespace(
            get=lambda model, pk: _async(SimpleNamespace(id="t1", agent_id="agent-1"))
        )

    monkeypatch.setattr(consumer_mod, "AsyncSessionLocal", _session)

    consumer = SlackRunConsumer(_record(_slack_delivery()))
    fake = _FakeClient()
    consumer.client = fake
    await consumer.run()

    assert "Hi" in "".join(fake.streamer.appended)
    assert fake.streamer.stopped
    assert any("View in auxilia" in str(p["blocks"]) for p in fake.posts)
    # Streaming targets the right Slack thread/recipient.
    assert fake.streamer.kwargs["channel"] == "C1"
    assert fake.streamer.kwargs["recipient_user_id"] == "U1"


async def test_consumer_posts_approval_blocks_on_interrupt(monkeypatch):
    monkeypatch.setattr(
        consumer_mod.RunService,
        "stream",
        _sse_stream('event: end\ndata: {"status": "interrupted"}\n\n'),
    )

    @asynccontextmanager
    async def _checkpointer():
        yield SimpleNamespace(aget_tuple=lambda config: _async(None))

    monkeypatch.setattr(consumer_mod, "get_checkpointer", _checkpointer)
    monkeypatch.setattr(
        consumer_mod,
        "pending_approval_requests",
        lambda _cp: [
            {
                "tool_call_id": "call_1",
                "tool_name": "get_weather",
                "input": {"city": "Paris"},
            }
        ],
    )

    consumer = SlackRunConsumer(_record(_slack_delivery()))
    fake = _FakeClient()
    consumer.client = fake
    await consumer.run()

    assert fake.streamer.stopped
    assert len(fake.posts) == 1
    action_ids = [
        el.get("action_id")
        for block in fake.posts[0]["blocks"]
        if block.get("type") == "actions"
        for el in block.get("elements", [])
    ]
    assert "tool_approve" in action_ids
    assert "tool_reject" in action_ids


async def _async(value):
    return value
