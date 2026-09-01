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
    await handlers_mod._update_approval_message(
        client, "C1", "111.1", blocks, "approve"
    )
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

    await handlers_mod._resume_agent(
        client, payload, "C1", "111.1", {"resume": {"decisions": [{"type": "approve"}]}}
    )

    assert prompts == ["a1"]
    assert enqueued == []


async def test_resume_agent_enqueues_resume_when_ready(monkeypatch):
    client, prompts, enqueued = _resume_fixture(monkeypatch, ready=True)
    payload = SimpleNamespace(user=SimpleNamespace(id="U1"), team={"id": "T1"})

    command = {
        "resume": {
            "interrupt_id": "ab" * 16,
            "decisions": [{"tool_call_id": "call_1", "type": "approve"}],
        }
    }
    await handlers_mod._resume_agent(client, payload, "C1", "111.1", command)

    assert prompts == []
    assert len(enqueued) == 1
    assert enqueued[0]["command"] == command
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


# ---------------------------------------------------------------------------
# Block-id protocol (P3-6): the card is tied to the checkpoint's interrupt id
# ---------------------------------------------------------------------------

IID = "ab" * 16
OTHER_IID = "cd" * 16


def _card(tool_call_id, iid=IID):
    return {"blocks": build_tool_approval_blocks(tool_call_id, {}, interrupt_id=iid)}


async def _decided_card(tool_call_id, decision, iid=IID):
    client = _RecordingClient()
    blocks = build_tool_approval_blocks(tool_call_id, {}, interrupt_id=iid)
    await handlers_mod._update_approval_message(client, "C1", "1.1", blocks, decision)
    return {"blocks": client.updated["blocks"]}


def test_block_id_round_trips_the_decision():
    blocks = build_tool_approval_blocks("call_1", {}, interrupt_id=IID)
    actions = next(b for b in blocks if b["type"] == "actions")
    assert handlers_mod._parse_hitl_block_id(actions["block_id"], decided=False) == (
        IID,
        "call_1",
        None,
    )
    assert handlers_mod._card_interrupt_id(blocks) == IID


async def test_decided_marker_carries_the_decision_in_its_block_id():
    msg = await _decided_card("call_1", "approve")
    marker = next(b for b in msg["blocks"] if b["type"] == "context")
    assert handlers_mod._parse_hitl_block_id(marker["block_id"], decided=True) == (
        IID,
        "call_1",
        "approve",
    )
    # The emoji is still there, but purely as presentation.
    assert ":white_check_mark:" in _context_text(msg["blocks"])


def test_parse_tolerates_colons_in_tool_call_ids():
    # Decided marker: the decision is always the appended last segment, so a
    # tool_call_id containing ':' survives.
    assert handlers_mod._parse_hitl_block_id(
        f"hitl:{IID}:mcp:tool:1:reject", decided=True
    ) == (IID, "mcp:tool:1", "reject")
    # Pending actions block: never split a suffix — a tool_call_id that itself
    # ends in ':approve' must not read as decided.
    assert handlers_mod._parse_hitl_block_id(
        f"hitl:{IID}:mcp:tool:approve", decided=False
    ) == (IID, "mcp:tool:approve", None)
    assert handlers_mod._parse_hitl_block_id("not-hitl", decided=False) is None
    assert handlers_mod._parse_hitl_block_id(None, decided=True) is None


async def test_pending_card_with_decisionlike_tool_call_id_stays_pending():
    """cubic P2: a pending actions block whose tool_call_id ends in ':approve'
    must count as pending, not decided — the block type decides, not the tail."""
    messages = [_card("call:approve")]
    decided, any_pending = handlers_mod._addressed_cards(messages, IID)
    assert decided == {}
    assert any_pending is True


async def test_addressed_batch_is_identified_not_guessed():
    """An interleaved non-approval message and a card from an older interrupt
    must not affect the batch — the contiguity heuristic did both wrong."""
    interrupt = handlers_mod.PendingInterrupt(id=IID, value={})
    requests = [
        {"tool_call_id": "call_1", "tool_name": "a", "input": {}},
        {"tool_call_id": "call_2", "tool_name": "b", "input": {}},
    ]
    messages = [
        await _decided_card("call_9", "approve", iid=OTHER_IID),  # older batch
        await _decided_card("call_1", "approve"),
        {"text": "something went wrong, retry"},  # interleaved notice
        await _decided_card("call_2", "reject"),
    ]

    command = handlers_mod._collect_batch_command(
        messages, interrupt, requests, allow_legacy=False
    )

    assert command == {
        "resume": {
            "interrupt_id": IID,
            "decisions": [
                {"tool_call_id": "call_1", "type": "approve"},
                {"tool_call_id": "call_2", "type": "reject"},
            ],
        }
    }


async def test_addressed_batch_waits_while_a_card_is_pending():
    interrupt = handlers_mod.PendingInterrupt(id=IID, value={})
    requests = [
        {"tool_call_id": "call_1", "tool_name": "a", "input": {}},
        {"tool_call_id": "call_2", "tool_name": "b", "input": {}},
    ]
    messages = [await _decided_card("call_1", "approve"), _card("call_2")]
    assert (
        handlers_mod._collect_batch_command(
            messages, interrupt, requests, allow_legacy=False
        )
        is None
    )


async def test_addressed_batch_with_a_vanished_card_never_resumes():
    interrupt = handlers_mod.PendingInterrupt(id=IID, value={})
    requests = [
        {"tool_call_id": "call_1", "tool_name": "a", "input": {}},
        {"tool_call_id": "call_2", "tool_name": "b", "input": {}},
    ]
    messages = [await _decided_card("call_1", "approve")]  # call_2's card deleted
    assert (
        handlers_mod._collect_batch_command(
            messages, interrupt, requests, allow_legacy=False
        )
        is None
    )


def test_legacy_cards_fall_back_to_the_emoji_scan():
    """Cards posted before the block-id protocol resume positionally — but
    only while the checkpoint's interrupt is id-less too, so the scan can't
    be replaying decisions onto an identifiable interrupt they may not answer."""
    interrupt = handlers_mod.PendingInterrupt(id=None, value={})
    requests = [{"tool_call_id": "call_1", "tool_name": "a", "input": {}}]
    legacy_decided = {
        "blocks": [
            {
                "type": "context",
                "elements": [{"type": "mrkdwn", "text": ":white_check_mark: Approved"}],
            }
        ]
    }
    command = handlers_mod._collect_batch_command(
        [legacy_decided], interrupt, requests, allow_legacy=True
    )
    assert command == {"resume": {"decisions": [{"type": "approve"}]}}


def test_legacy_scan_never_touches_an_identifiable_interrupt():
    """cubic P1 (round 2): even a legacy *click* (allow_legacy=True) must not
    resume an id-bearing interrupt from emoji-scanned cards — same-size older
    batches would be replayed onto it positionally."""
    interrupt = handlers_mod.PendingInterrupt(id=IID, value={})
    requests = [{"tool_call_id": "call_1", "tool_name": "a", "input": {}}]
    legacy_decided = {
        "blocks": [
            {
                "type": "context",
                "elements": [{"type": "mrkdwn", "text": ":white_check_mark: Approved"}],
            }
        ]
    }
    assert (
        handlers_mod._collect_batch_command(
            [legacy_decided], interrupt, requests, allow_legacy=True
        )
        is None
    )


async def test_legacy_click_on_identifiable_interrupt_points_to_the_web_ui(
    monkeypatch,
):
    """A pre-block-id card against an interrupt the checkpoint identifies:
    unprovable — the card keeps its buttons and the user is sent to the web."""

    async def _state(thread_id):
        return (
            handlers_mod.PendingInterrupt(id=IID, value={}),
            [{"tool_call_id": "call_1", "tool_name": "t", "input": {}}],
        )

    resumed: list = []
    updates: list = []
    posts: list = []

    async def _resume(*args, **kwargs):
        resumed.append(args)

    async def _update(*args, **kwargs):
        updates.append(args)

    async def _post(**kwargs):
        posts.append(kwargs)

    monkeypatch.setattr(handlers_mod, "_pending_hitl_state", _state)
    monkeypatch.setattr(handlers_mod, "_resume_agent", _resume)
    monkeypatch.setattr(handlers_mod, "_update_approval_message", _update)
    monkeypatch.setattr(
        handlers_mod.AsyncWebClient,
        "chat_postMessage",
        lambda self, **kwargs: _post(**kwargs),
    )

    legacy_blocks = build_tool_approval_blocks("call_1", {})  # no interrupt_id
    await handlers_mod.handle_interaction(_interaction_payload(legacy_blocks))

    assert resumed == []
    assert updates == []  # buttons stay — the card is never marked
    assert len(posts) == 1
    assert "auxilia" in posts[0]["text"]


async def test_id_tagged_click_never_falls_back_to_the_emoji_scan():
    """cubic P1: with the current interrupt's tagged cards gone, older legacy
    decided cards must not be replayed onto it — unresolved, web UI takes over."""
    interrupt = handlers_mod.PendingInterrupt(id=IID, value={})
    requests = [{"tool_call_id": "call_1", "tool_name": "a", "input": {}}]
    stale_legacy = {
        "blocks": [
            {
                "type": "context",
                "elements": [{"type": "mrkdwn", "text": ":white_check_mark: Approved"}],
            }
        ]
    }
    assert (
        handlers_mod._collect_batch_command(
            [stale_legacy], interrupt, requests, allow_legacy=False
        )
        is None
    )


def test_legacy_scan_requires_the_decision_count_to_match():
    """A legacy batch whose size disagrees with the pending requests answers
    some other batch — never resume with it."""
    interrupt = handlers_mod.PendingInterrupt(id=None, value={})
    requests = [
        {"tool_call_id": "call_1", "tool_name": "a", "input": {}},
        {"tool_call_id": "call_2", "tool_name": "b", "input": {}},
    ]
    one_legacy_decision = {
        "blocks": [
            {
                "type": "context",
                "elements": [{"type": "mrkdwn", "text": ":white_check_mark: Approved"}],
            }
        ]
    }
    assert (
        handlers_mod._collect_batch_command(
            [one_legacy_decision], interrupt, requests, allow_legacy=True
        )
        is None
    )


def _interaction_payload(blocks):
    return SimpleNamespace(
        actions=[SimpleNamespace(action_id="tool_approve", value="call_1")],
        container=SimpleNamespace(
            channel_id="C1", thread_ts="111.1", message_ts="222.2"
        ),
        channel=None,
        message=SimpleNamespace(blocks=blocks),
        user=SimpleNamespace(id="U1"),
        team=None,
    )


async def test_stale_click_marks_the_card_and_never_resumes(monkeypatch):
    """A click on a card whose interrupt was already resolved elsewhere (web,
    another batch) must not resume whatever the thread pends on now."""
    resumed: list = []

    async def _no_state(thread_id):
        return None  # nothing pending on the checkpoint

    async def _resume(*args, **kwargs):
        resumed.append(args)

    monkeypatch.setattr(handlers_mod, "_pending_hitl_state", _no_state)
    monkeypatch.setattr(handlers_mod, "_resume_agent", _resume)
    updates: list = []

    async def _update(client, channel_id, message_ts, blocks, decision):
        updates.append(decision)

    monkeypatch.setattr(handlers_mod, "_update_approval_message", _update)

    await handlers_mod.handle_interaction(
        _interaction_payload(_card("call_1")["blocks"])
    )

    assert updates == ["stale"]
    assert resumed == []


async def test_click_on_an_older_batch_card_is_stale(monkeypatch):
    """A *different* interrupt pends: the old card is marked, the new batch
    is untouched."""

    async def _state(thread_id):
        return (
            handlers_mod.PendingInterrupt(id=OTHER_IID, value={}),
            [{"tool_call_id": "call_7", "tool_name": "t", "input": {}}],
        )

    resumed: list = []

    async def _resume(*args, **kwargs):
        resumed.append(args)

    updates: list = []

    async def _update(client, channel_id, message_ts, blocks, decision):
        updates.append(decision)

    monkeypatch.setattr(handlers_mod, "_pending_hitl_state", _state)
    monkeypatch.setattr(handlers_mod, "_resume_agent", _resume)
    monkeypatch.setattr(handlers_mod, "_update_approval_message", _update)

    await handlers_mod.handle_interaction(
        _interaction_payload(_card("call_1")["blocks"])
    )

    assert updates == ["stale"]
    assert resumed == []


async def test_resume_agent_reports_a_lost_race_as_already_handled(monkeypatch):
    """`RunService.create` is the stale backstop; the Slack thread hears about
    it instead of failing silently."""
    from app.exceptions import StaleApprovalError

    client, _prompts, _enqueued = _resume_fixture(monkeypatch, ready=True)

    async def _stale_enqueue(**kwargs):
        raise StaleApprovalError("already handled")

    posts: list = []

    async def _post(**kwargs):
        posts.append(kwargs)

    monkeypatch.setattr(handlers_mod, "_enqueue_slack_run", _stale_enqueue)
    client.chat_postMessage = _post
    payload = SimpleNamespace(user=SimpleNamespace(id="U1"), team=None)

    await handlers_mod._resume_agent(
        client,
        payload,
        "C1",
        "111.1",
        {"resume": {"interrupt_id": IID, "decisions": []}},
    )

    assert len(posts) == 1
    assert "already handled" in posts[0]["text"].lower()
