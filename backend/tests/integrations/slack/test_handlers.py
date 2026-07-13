"""Tests for the thin Slack web tier — turns enqueue durable runs."""

from types import SimpleNamespace

import app.integrations.slack.handlers as handlers_mod
from app.exceptions import DomainValidationError
from app.integrations.slack.blocks import build_tool_approval_blocks
from app.integrations.slack.handlers import _extract_decision


class _RecordingClient:
    def __init__(self):
        self.updated: dict = {}

    async def chat_update(self, **kwargs):
        self.updated = kwargs


def _context_text(blocks: list[dict]) -> str:
    return " ".join(
        el.get("text", "")
        for b in blocks
        if b.get("type") == "context"
        for el in b.get("elements", [])
    )


async def test_approval_card_has_no_tool_header():
    # The streamed tool label already shows the tool name above the card, so the
    # card must not repeat it — and a pending card carries no decision marker.
    blocks = build_tool_approval_blocks("call_1", {"a": 1})
    assert all(b.get("type") != "context" for b in blocks)
    assert any(b.get("type") == "actions" for b in blocks)


async def test_approval_decision_round_trips_through_context_block():
    blocks = build_tool_approval_blocks("call_1", {"a": 1})
    msg = {"blocks": blocks}
    # Pending: no decision yet, buttons present.
    assert _extract_decision(msg) is None

    client = _RecordingClient()
    await handlers_mod._update_approval_message(client, "C1", "111.1", blocks, True)
    updated = client.updated["blocks"]

    # Decision lands in a context block; the buttons are gone.
    assert ":white_check_mark:" in _context_text(updated)
    assert not any(b.get("type") == "actions" for b in updated)
    assert _extract_decision({"blocks": updated}) == "approve"


def _patch_run_service(monkeypatch, *, raises: Exception | None = None):
    """Replace RunService with a recorder; returns the captured create kwargs."""
    captured: dict = {}

    class _FakeRunService:
        def __init__(self, *args, **kwargs):
            pass

        async def create(self, **kwargs):
            if raises is not None:
                raise raises
            captured.update(kwargs)
            return SimpleNamespace(id="run-1")

    monkeypatch.setattr(handlers_mod, "RunService", _FakeRunService)
    return captured


async def test_enqueue_builds_slack_delivery_and_passes_input(monkeypatch):
    captured = _patch_run_service(monkeypatch)

    await handlers_mod._enqueue_slack_run(
        thread_id="t1",
        user_id="u1",
        channel_id="C1",
        slack_user_id="U1",
        team_id="T1",
        input={"messages": [{"type": "human", "content": "hi"}]},
    )

    assert captured["thread_id"] == "t1"
    assert captured["user_id"] == "u1"
    assert captured["input"] == {"messages": [{"type": "human", "content": "hi"}]}
    assert captured["command"] is None
    assert captured["delivery"] == {
        "channel": "slack",
        "channel_id": "C1",
        "thread_ts": "t1",
        "slack_user_id": "U1",
        "team_id": "T1",
    }


async def test_enqueue_passes_resume_command(monkeypatch):
    captured = _patch_run_service(monkeypatch)

    await handlers_mod._enqueue_slack_run(
        thread_id="t1",
        user_id="u1",
        channel_id="C1",
        slack_user_id="U1",
        team_id=None,
        command={"resume": {"decisions": [{"type": "approve"}]}},
    )

    assert captured["command"] == {"resume": {"decisions": [{"type": "approve"}]}}
    assert captured["input"] is None


async def test_is_agent_ready_delegates_to_describe_readiness(monkeypatch):
    """The gate's contract: project readiness['ready'] for the given user.
    Its hand-rolled predecessor was always-ready because of an untested bug."""
    from uuid import uuid4

    agent_id = uuid4()
    seen: list = []

    async def _readiness(self, aid, user_id):
        seen.append((aid, user_id))
        return {"ready": False, "disconnected_servers": ["s"], "status": "disconnected"}

    monkeypatch.setattr(handlers_mod.AgentService, "__init__", lambda self, db: None)
    monkeypatch.setattr(handlers_mod.AgentService, "describe_readiness", _readiness)
    assert await handlers_mod._is_agent_ready(str(agent_id), "u1", None) is False
    # str agent_id converted to UUID; probed for the given user.
    assert seen == [(agent_id, "u1")]


async def test_is_agent_ready_fails_open_on_infra_errors(monkeypatch):
    async def _boom(self, aid, user_id):
        raise ConnectionError("redis down")

    monkeypatch.setattr(handlers_mod.AgentService, "describe_readiness", _boom)
    monkeypatch.setattr(handlers_mod.AgentService, "__init__", lambda self, db: None)
    from uuid import uuid4

    assert await handlers_mod._is_agent_ready(str(uuid4()), "u1", None) is True


def _resume_fixture(monkeypatch, *, ready: bool):
    thread = SimpleNamespace(agent_id="a1")

    class _Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def get(self, model, pk):
            return thread

    prompts: list = []
    enqueued: list = []

    async def _user(_):
        return SimpleNamespace(id="u1")

    async def _ready(*_):
        return ready

    async def _prompt(client, channel, thread_ts, agent_id):
        prompts.append(agent_id)

    async def _enqueue(**kwargs):
        enqueued.append(kwargs)

    async def _noop_status(**kwargs):
        return None

    monkeypatch.setattr(handlers_mod, "resolve_user", _user)
    monkeypatch.setattr(handlers_mod, "AsyncSessionLocal", lambda: _Session())
    monkeypatch.setattr(handlers_mod, "_is_agent_ready", _ready)
    monkeypatch.setattr(handlers_mod, "_post_connect_prompt", _prompt)
    monkeypatch.setattr(handlers_mod, "_enqueue_slack_run", _enqueue)
    client = SimpleNamespace(assistant_threads_setStatus=_noop_status)
    return client, prompts, enqueued


async def test_resume_agent_prompts_reconnect_when_mcp_unauthorized(monkeypatch):
    """An approval clicked after the user's OAuth expired must post the
    connect prompt, not enqueue a doomed run."""
    client, prompts, enqueued = _resume_fixture(monkeypatch, ready=False)
    payload = SimpleNamespace(user=SimpleNamespace(id="U1"), team=None)

    await handlers_mod._resume_agent(client, payload, "C1", "111.1", ["approve"])

    assert prompts == ["a1"]
    assert enqueued == []


async def test_resume_agent_enqueues_resume_when_ready(monkeypatch):
    client, prompts, enqueued = _resume_fixture(monkeypatch, ready=True)
    payload = SimpleNamespace(user=SimpleNamespace(id="U1"), team={"id": "T1"})

    await handlers_mod._resume_agent(client, payload, "C1", "111.1", ["approve"])

    assert prompts == []
    assert len(enqueued) == 1
    assert enqueued[0]["command"] == {"resume": {"decisions": [{"type": "approve"}]}}
    assert enqueued[0]["team_id"] == "T1"


async def test_enqueue_swallows_active_run_conflict(monkeypatch):
    _patch_run_service(monkeypatch, raises=DomainValidationError("active run"))

    # A duplicate that loses the per-thread mutex race must not raise — the
    # webhook still needs to ack cleanly.
    await handlers_mod._enqueue_slack_run(
        thread_id="t1",
        user_id="u1",
        channel_id="C1",
        slack_user_id="U1",
        team_id=None,
        input={"messages": []},
    )
