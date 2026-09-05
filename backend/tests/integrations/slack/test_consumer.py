"""Tests for the worker-side Slack delivery consumer.

The consumer reads the run's event log — Agent Streaming Protocol events as
the worker stores them (`app/agents/protocol/wire.py`) — so fixtures are
built with the real encoder and the terminal entry `finalize` appends.
"""

from contextlib import asynccontextmanager
from types import SimpleNamespace
from uuid import uuid4

import app.integrations.slack.consumer as consumer_mod
from app.agents.protocol import events as ev
from app.agents.protocol.wire import encode_event, encode_terminal
from app.agents.runs.models import RunDB
from app.agents.runs.state import RunStatus
from app.integrations.slack.consumer import (
    SlackProtocolAdapter,
    SlackRunConsumer,
    build_slack_delivery,
    build_slack_run_consumer,
)


def _record(delivery=None) -> RunDB:
    return RunDB(id="r1", thread_id="t1", user_id=uuid4(), delivery=delivery)


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


def _log(*events, status: RunStatus | None = RunStatus.success, error=None):
    """A stored log: encoded protocol events + the terminal entry."""
    chunks = [encode_event(e) for e in events]
    if status is not None:
        chunks.append(encode_terminal(status.value, error=error))

    async def _gen(*_args, **_kwargs):
        for chunk in chunks:
            yield chunk

    return _gen


def _text_message(ns, node, text, *, message_id="a", role="ai"):
    return [
        ev.message_start(ns, node, role=role, message_id=message_id),
        ev.content_block_start(ns, node, index=0, content={"type": "text", "text": ""}),
        ev.content_block_delta(
            ns, node, index=0, delta={"type": "text-delta", "text": text}
        ),
        ev.message_finish(ns, node),
    ]


def _patch_status(monkeypatch, status: RunStatus | None, error: str | None = None):
    """The consumer reads the terminal status off the durable record."""

    async def _get(self, run_id):
        return SimpleNamespace(status=status or RunStatus.running, error=error)

    monkeypatch.setattr(consumer_mod.RunService, "get", _get)


def _patch_thread_lookup(monkeypatch):
    @asynccontextmanager
    async def _session():
        yield SimpleNamespace(
            get=lambda model, pk: _async(SimpleNamespace(id="t1", agent_id="agent-1"))
        )

    monkeypatch.setattr(consumer_mod, "AsyncSessionLocal", _session)


# ── Factory ──────────────────────────────────────────────────────────


def test_factory_skips_non_slack_runs():
    assert build_slack_run_consumer(_record(None)) is None
    assert build_slack_run_consumer(_record({"channel": "web"})) is None


def test_factory_builds_for_slack_runs():
    consumer = build_slack_run_consumer(_record(_slack_delivery()))
    assert isinstance(consumer, SlackRunConsumer)


# ── Adapter: what reaches the streaming message ──────────────────────────


def test_adapter_relays_root_ai_text_only():
    adapter = SlackProtocolAdapter()
    out: list[str] = []
    for event in [
        *_text_message([], "model", "Hi"),
        # Subagent tokens stream under their namespace and are skipped.
        *_text_message(["tools:t1"], "model", "sub", message_id="s"),
        # A tool-role message carries the raw tool result — never chat text.
        ev.message_start([], None, role="tool", message_id="tm", tool_call_id="c1"),
        ev.content_block_start(
            [], None, index=0, content={"type": "text", "text": '{"raw": 1}'}
        ),
        ev.message_finish([], None),
        # Reasoning deltas are excluded.
        ev.message_start([], "model", role="ai", message_id="b"),
        ev.content_block_delta(
            [], "model", index=0, delta={"type": "reasoning-delta", "reasoning": "hmm"}
        ),
        ev.content_block_delta(
            [], "model", index=1, delta={"type": "text-delta", "text": "!"}
        ),
        ev.message_finish([], "model"),
    ]:
        out.extend(adapter.texts(event))
    assert out == ["Hi", "!"]


def test_adapter_emits_each_tool_label_once():
    adapter = SlackProtocolAdapter()
    started = ev.tool_started([], None, tool_call_id="c1", tool_name="get_weather")
    assert adapter.texts(started) == [
        consumer_mod.format_tool_streamer_label("get_weather")
    ]
    assert adapter.texts(started) == []
    assert (
        adapter.texts(ev.tool_finished([], None, tool_call_id="c1", output="x")) == []
    )


# ── Delivery behavior ──────────────────────────────────────────────────


async def test_consumer_streams_text_and_posts_link_on_success(monkeypatch):
    monkeypatch.setattr(
        consumer_mod.RunService, "stream", _log(*_text_message([], "model", "Hi"))
    )
    _patch_status(monkeypatch, RunStatus.success)
    _patch_thread_lookup(monkeypatch)

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


def _scope(interrupt, subagent_type=None):
    """A `load_interrupt_scope` stand-in: the located pending interrupt."""

    async def _load(_checkpointer, _thread_id):
        return SimpleNamespace(
            root=None,
            checkpoint=None,
            interrupt=interrupt,
            namespace="tools:x" if subagent_type else "",
            subagent_type=subagent_type,
        )

    return _load


async def test_consumer_posts_approval_blocks_on_interrupt(monkeypatch):
    monkeypatch.setattr(
        consumer_mod.RunService, "stream", _log(status=RunStatus.interrupted)
    )
    _patch_status(monkeypatch, RunStatus.interrupted)

    @asynccontextmanager
    async def _checkpointer():
        yield SimpleNamespace(aget_tuple=lambda config: _async(None))

    monkeypatch.setattr(consumer_mod, "get_checkpointer", _checkpointer)
    monkeypatch.setattr(
        consumer_mod, "load_interrupt_scope", _scope(SimpleNamespace(id=None, value={}))
    )
    monkeypatch.setattr(
        consumer_mod,
        "pending_approval_requests",
        lambda _root, _scope: [
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


async def test_approval_cards_carry_the_interrupt_id_block_id(monkeypatch):
    """Each card is tied to the checkpoint's interrupt id via its block_id —
    the key the batch-resume logic reads back (P3-6)."""
    monkeypatch.setattr(
        consumer_mod.RunService, "stream", _log(status=RunStatus.interrupted)
    )
    _patch_status(monkeypatch, RunStatus.interrupted)

    @asynccontextmanager
    async def _checkpointer():
        yield SimpleNamespace(aget_tuple=lambda config: _async(None))

    monkeypatch.setattr(consumer_mod, "get_checkpointer", _checkpointer)
    iid = "ab" * 16
    monkeypatch.setattr(
        consumer_mod,
        "load_interrupt_scope",
        _scope(SimpleNamespace(id=iid, value={}), subagent_type="mailer"),
    )
    monkeypatch.setattr(
        consumer_mod,
        "pending_approval_requests",
        lambda _root, _scope: [
            {"tool_call_id": "call_1", "tool_name": "t", "input": {}}
        ],
    )

    consumer = SlackRunConsumer(_record(_slack_delivery()))
    fake = _FakeClient()
    consumer.client = fake
    await consumer.run()

    actions = next(b for b in fake.posts[0]["blocks"] if b.get("type") == "actions")
    assert actions["block_id"] == f"hitl:{iid}:call_1"
    # A subagent's request says which subagent asked.
    context = next(b for b in fake.posts[0]["blocks"] if b.get("type") == "context")
    assert "mailer" in context["elements"][0]["text"]
    assert fake.posts[0]["text"] == "Approve t for mailer?"


async def test_consumer_posts_failure_notice_on_error(monkeypatch):
    monkeypatch.setattr(
        consumer_mod.RunService, "stream", _log(status=RunStatus.error, error="boom")
    )
    _patch_status(monkeypatch, RunStatus.error, "boom")

    consumer = SlackRunConsumer(_record(_slack_delivery()))
    fake = _FakeClient()
    consumer.client = fake
    await consumer.run()

    assert fake.streamer.stopped
    # The failure is surfaced inline on the streaming message…
    assert any("Error: boom" in text for text in fake.streamer.appended)
    # …and as the generic notice.
    assert len(fake.posts) == 1
    assert "something went wrong" in fake.posts[0]["text"].lower()


async def test_cancelled_runs_stay_silent(monkeypatch):
    """The protocol terminal folds a Stop into `completed`; the durable record
    tells them apart, and a user Stop must not post the auxilia link."""
    monkeypatch.setattr(
        consumer_mod.RunService, "stream", _log(status=RunStatus.cancelled)
    )
    _patch_status(monkeypatch, RunStatus.cancelled)

    consumer = SlackRunConsumer(_record(_slack_delivery()))
    fake = _FakeClient()
    consumer.client = fake
    await consumer.run()

    assert fake.streamer.stopped
    assert fake.posts == []


async def test_consumer_posts_connect_prompt_on_reauth_gated_error(monkeypatch):
    """A run refused by the worker's OAuth pre-flight must surface the
    Connect button in the Slack thread, not the generic failure notice."""
    from app.agents.runs.state import MCP_REAUTH_ERROR

    monkeypatch.setattr(
        consumer_mod.RunService,
        "stream",
        _log(status=RunStatus.error, error=MCP_REAUTH_ERROR),
    )
    _patch_status(monkeypatch, RunStatus.error, MCP_REAUTH_ERROR)
    _patch_thread_lookup(monkeypatch)

    consumer = SlackRunConsumer(_record(_slack_delivery()))
    fake = _FakeClient()
    consumer.client = fake
    await consumer.run()

    assert len(fake.posts) == 1
    assert "Connect on auxilia" in str(fake.posts[0]["blocks"])
    assert "agent-1" in str(fake.posts[0]["blocks"])


async def test_consumer_posts_failure_notice_when_stream_crashes(monkeypatch):
    def _boom(*_args, **_kwargs):
        raise RuntimeError("redis gone")

    monkeypatch.setattr(consumer_mod.RunService, "stream", _boom)

    consumer = SlackRunConsumer(_record(_slack_delivery()))
    fake = _FakeClient()
    consumer.client = fake
    # A crash mid-delivery is handled: the thread gets a notice, not silence.
    await consumer.run()

    assert any("something went wrong" in p["text"].lower() for p in fake.posts)


async def test_non_terminal_record_after_the_log_ends_posts_the_failure_notice(
    monkeypatch,
):
    """The log ended but the record isn't terminal (a producer this build can't
    reconcile with): the thread must not be left with only a stopped
    streaming message."""
    monkeypatch.setattr(consumer_mod.RunService, "stream", _log())
    _patch_status(monkeypatch, None)

    consumer = SlackRunConsumer(_record(_slack_delivery()))
    fake = _FakeClient()
    consumer.client = fake
    await consumer.run()

    assert fake.streamer.stopped
    assert len(fake.posts) == 1
    assert "something went wrong" in fake.posts[0]["text"]


async def test_legacy_log_entries_are_ignored(monkeypatch):
    """A run in flight during the deploy has pre-protocol SSE entries in its
    log; they must be skipped, and the run still ends cleanly."""

    async def _gen(*_args, **_kwargs):
        yield 'event: messages\ndata: [{"type": "AIMessageChunk", "content": "Hi", "id": "a"}, {}]\n\n'
        yield encode_terminal("success")

    monkeypatch.setattr(consumer_mod.RunService, "stream", _gen)
    _patch_status(monkeypatch, RunStatus.success)
    _patch_thread_lookup(monkeypatch)

    consumer = SlackRunConsumer(_record(_slack_delivery()))
    fake = _FakeClient()
    consumer.client = fake
    await consumer.run()

    assert fake.streamer.appended == []
    assert any("View in auxilia" in str(p["blocks"]) for p in fake.posts)


async def _async(value):
    return value
