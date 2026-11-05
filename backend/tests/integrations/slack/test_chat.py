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


async def test_options_deadline_cancels_slow_identity_lookup(monkeypatch):
    import asyncio

    lookup = AsyncMock(side_effect=lambda: None)

    async def slow_lookup(_user):
        await asyncio.Event().wait()

    lookup.side_effect = slow_lookup
    monkeypatch.setattr(chat, "resolve_user", lookup)
    monkeypatch.setattr(chat, "OPTIONS_TIMEOUT_SECONDS", 0.01)
    payload = SlackInteractionPayload(
        type="block_suggestion", user={"id": "U1"}, action_id="select_agent"
    )
    assert await asyncio.wait_for(chat.handle_agent_options(payload), timeout=0.5) == {
        "options": []
    }


async def test_selection_replaces_picker_without_container(monkeypatch):
    agent = _agents(1)[0]
    user = SimpleNamespace(id=uuid4(), role="member", team_id=None)
    info = SimpleNamespace(profile=SimpleNamespace(email="member@example.com"))
    monkeypatch.setattr(chat, "get_user_info", AsyncMock(return_value=info))
    repo = SimpleNamespace(get_by_email=AsyncMock(return_value=user))
    monkeypatch.setattr(chat, "UserRepository", lambda _db: repo)
    db = AsyncMock()
    db.get.return_value = agent
    session = AsyncMock()
    session.__aenter__.return_value = db
    monkeypatch.setattr(chat, "AsyncSessionLocal", lambda: session)
    monkeypatch.setattr(chat, "list_pickable_agents", AsyncMock(return_value=[agent]))
    service = SimpleNamespace(get_or_create=AsyncMock())
    monkeypatch.setattr(chat, "ThreadService", lambda _db: service)
    client = AsyncMock()
    monkeypatch.setattr(chat, "AsyncWebClient", lambda **_kwargs: client)
    payload = SlackInteractionPayload(
        type="block_actions",
        user={"id": "U1"},
        channel={"id": "C1"},
        message={"ts": "2.0", "thread_ts": "1.0"},
        actions=[
            {"action_id": "select_agent", "selected_option": {"value": str(agent.id)}}
        ],
    )
    await chat.handle_agent_selection(payload)
    service.get_or_create.assert_awaited_once()
    assert service.get_or_create.await_args.kwargs["ts"] == "1.0"
    client.chat_update.assert_awaited_once()
    assert client.chat_update.await_args.kwargs["ts"] == "2.0"
