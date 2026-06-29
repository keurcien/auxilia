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


def _header_text(blocks: list[dict]) -> str:
    return next(b["text"]["text"] for b in blocks if b.get("type") == "section")


async def test_approval_header_is_a_section_block():
    # The tool header must be a body-size section, not a small context block,
    # so it matches the streamed tool label.
    blocks = build_tool_approval_blocks("call_1", "BigQuery_execute_sql", {"a": 1})
    assert blocks[0]["type"] == "section"
    assert all(b.get("type") != "context" for b in blocks)


async def test_approval_decision_round_trips_through_section_header():
    blocks = build_tool_approval_blocks("call_1", "BigQuery_execute_sql", {"a": 1})
    msg = {"blocks": blocks}
    # Pending: no decision yet, buttons present.
    assert _extract_decision(msg) is None

    client = _RecordingClient()
    await handlers_mod._update_approval_message(client, "C1", "111.1", blocks, True)
    updated = client.updated["blocks"]

    # Decision lands on the header section; the input section is untouched.
    assert ":white_check_mark:" in _header_text(updated)
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
