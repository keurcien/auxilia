"""Slack agent search must filter before applying Slack's response limit."""

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

from app.integrations.slack.commands import chat
from app.integrations.slack.models import SlackInteractionPayload


def _agents(n):
    return [
        SimpleNamespace(id=uuid4(), name=f"Agent {i:03d}", emoji=None) for i in range(n)
    ]


def test_external_picker():
    blocks = chat.build_agent_picker_blocks(_agents(150), header_text="Pick one:")
    assert blocks[0]["text"]["text"] == "Pick one:"
    element = blocks[1]["elements"][0]
    assert element["type"] == "external_select"
    assert element["action_id"] == "select_agent"
    assert element["min_query_length"] == 0
    assert "options" not in element


def test_search_reaches_agents_past_first_hundred():
    agents = _agents(150)
    assert len(chat.search_agent_options(agents, "")) == 100
    assert chat.search_agent_options(agents, "Agent 149")[0]["value"] == str(
        agents[-1].id
    )
    assert chat.search_agent_options(agents, str(agents[-1].id))[0]["value"] == str(
        agents[-1].id
    )
    assert chat.search_agent_options(agents, "absent") == []


def test_search_ranking_and_label_limit():
    agents = _agents(3)
    for agent, name in zip(agents, ["My Sales", "Sales ops", "Sales"], strict=True):
        agent.name = name
    assert [o["value"] for o in chat.search_agent_options(agents, " SALES ")] == [
        str(a.id) for a in reversed(agents)
    ]
    agents[0].name = "x" * 100
    agents[0].emoji = "🐛"
    label = chat.search_agent_options(agents, "xxx")[0]["text"]["text"]
    assert label.startswith("🐛 ")
    assert len(label) == 75


async def test_options_resolve_current_user_permissions(monkeypatch):
    user = SimpleNamespace(id=uuid4(), role="member", team_id=uuid4())
    monkeypatch.setattr(chat, "resolve_user", AsyncMock(return_value=user))
    session = AsyncMock()
    monkeypatch.setattr(chat, "AsyncSessionLocal", lambda: session)
    listing = AsyncMock(return_value=_agents(150))
    monkeypatch.setattr(chat, "list_pickable_agents", listing)
    payload = SlackInteractionPayload(
        type="block_suggestion",
        user={"id": "U1"},
        action_id="select_agent",
        value="149",
    )
    result = await chat.handle_agent_options(payload)
    assert len(result["options"]) == 1
    listing.assert_awaited_once_with(
        session.__aenter__.return_value, user.id, user.role, user.team_id
    )
    chat.resolve_user.return_value = None
    assert await chat.handle_agent_options(payload) == {"options": []}
