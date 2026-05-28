"""Unit tests for the Slack agent picker (``build_agent_picker_blocks``)."""

from types import SimpleNamespace
from uuid import uuid4

from app.integrations.slack.commands.chat import (
    MAX_OPTIONS,
    SELECT_AGENT_ACTION_ID,
    build_agent_picker_blocks,
)


def _agents(n: int) -> list[SimpleNamespace]:
    """Lightweight stand-ins; the builder only reads ``id`` / ``name`` / ``emoji``."""
    return [
        SimpleNamespace(id=uuid4(), name=f"Agent {i:03d}", emoji=None) for i in range(n)
    ]


def _select_element(blocks: list[dict]) -> dict:
    for block in blocks:
        if block.get("type") != "actions":
            continue
        for el in block.get("elements", []):
            if el.get("type") == "static_select":
                return el
    raise AssertionError("no static_select found in blocks")


def _context_blocks(blocks: list[dict]) -> list[dict]:
    return [b for b in blocks if b.get("type") == "context"]


def test_builds_one_static_select_with_one_option_per_agent():
    blocks = build_agent_picker_blocks(_agents(7))

    select = _select_element(blocks)
    assert select["action_id"] == SELECT_AGENT_ACTION_ID
    assert len(select["options"]) == 7


def test_option_value_is_agent_id():
    agents = _agents(3)
    options = _select_element(build_agent_picker_blocks(agents))["options"]

    assert [o["value"] for o in options] == [str(a.id) for a in agents]


def test_option_text_includes_emoji_and_name():
    agents = [SimpleNamespace(id=uuid4(), name="Bug-Data", emoji="🐛")]
    options = _select_element(build_agent_picker_blocks(agents))["options"]

    assert options[0]["text"]["text"] == "🐛 Bug-Data"


def test_options_capped_at_slack_limit():
    # Regression guard: Slack rejects a static_select with more than 100 options.
    blocks = build_agent_picker_blocks(_agents(MAX_OPTIONS + 25))

    assert len(_select_element(blocks)["options"]) == MAX_OPTIONS


def test_truncation_note_added_when_over_cap():
    blocks = build_agent_picker_blocks(_agents(MAX_OPTIONS + 5))

    notes = _context_blocks(blocks)
    assert len(notes) == 1
    assert f"{MAX_OPTIONS}" in notes[0]["elements"][0]["text"]
    assert f"{MAX_OPTIONS + 5}" in notes[0]["elements"][0]["text"]


def test_no_truncation_note_when_within_cap():
    blocks = build_agent_picker_blocks(_agents(MAX_OPTIONS))

    assert _context_blocks(blocks) == []


def test_header_text_is_rendered():
    blocks = build_agent_picker_blocks(_agents(3), header_text="Pick one:")

    assert blocks[0]["type"] == "section"
    assert blocks[0]["text"]["text"] == "Pick one:"
