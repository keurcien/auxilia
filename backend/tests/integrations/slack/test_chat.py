"""Unit tests for the paginated Slack agent picker (``build_agent_picker_blocks``)."""

from types import SimpleNamespace
from uuid import uuid4

from app.integrations.slack.commands.chat import PAGE_SIZE, build_agent_picker_blocks


def _agents(n: int) -> list[SimpleNamespace]:
    """Lightweight stand-ins; the builder only reads ``id`` / ``name`` / ``emoji``."""
    return [
        SimpleNamespace(id=uuid4(), name=f"Agent {i:03d}", emoji=None) for i in range(n)
    ]


def _action_blocks(blocks: list[dict]) -> list[dict]:
    return [b for b in blocks if b["type"] == "actions"]


def _elements(blocks: list[dict]) -> list[dict]:
    return [el for b in _action_blocks(blocks) for el in b["elements"]]


def _select_buttons(blocks: list[dict]) -> list[dict]:
    return [
        el for el in _elements(blocks) if el["action_id"].startswith("select_agent:")
    ]


def _show_more(blocks: list[dict]) -> dict | None:
    more = [
        el for el in _elements(blocks) if el["action_id"].startswith("load_more_agents:")
    ]
    return more[0] if more else None


def test_first_page_shows_one_batch_with_show_more_when_more_exist():
    blocks = build_agent_picker_blocks(_agents(25))

    assert len(_select_buttons(blocks)) == PAGE_SIZE
    more = _show_more(blocks)
    assert more is not None
    # Encodes the new cumulative count to reveal next.
    assert more["action_id"] == f"load_more_agents:{PAGE_SIZE + 1}"
    assert more["value"] == str(PAGE_SIZE + 1)


def test_no_show_more_when_everything_fits_on_first_page():
    blocks = build_agent_picker_blocks(_agents(PAGE_SIZE))

    assert len(_select_buttons(blocks)) == PAGE_SIZE
    assert _show_more(blocks) is None


def test_no_actions_block_exceeds_slack_limit():
    # Regression guard: the original picker crammed every agent into a single
    # actions block, which Slack rejects past 25 elements (the >25 agents bug).
    blocks = build_agent_picker_blocks(_agents(120), shown=120)

    for block in _action_blocks(blocks):
        assert len(block["elements"]) <= 25


def test_accumulates_previously_shown_agents():
    blocks = build_agent_picker_blocks(_agents(100), shown=2 * PAGE_SIZE)

    # All agents revealed so far stay visible, not just the latest batch.
    assert len(_select_buttons(blocks)) == 2 * PAGE_SIZE
    more = _show_more(blocks)
    assert more is not None
    assert more["action_id"] == f"load_more_agents:{3 * PAGE_SIZE}"


def test_next_count_is_capped_at_total():
    blocks = build_agent_picker_blocks(_agents(30), shown=PAGE_SIZE)

    more = _show_more(blocks)
    assert more is not None
    assert more["action_id"] == "load_more_agents:30"
    assert "6 more" in more["text"]["text"]


def test_header_text_is_rendered():
    blocks = build_agent_picker_blocks(_agents(3), header_text="Pick one:")

    assert blocks[0]["type"] == "section"
    assert blocks[0]["text"]["text"] == "Pick one:"
