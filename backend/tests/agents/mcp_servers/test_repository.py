from datetime import datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.agents.mcp_servers.repository import AgentMCPServerRepository
from app.agents.models import AgentMCPServerBase, AgentMCPServerDB
from app.agents.schemas import AgentMCPServerPatch


@pytest.fixture
def mock_db():
    db = AsyncMock()
    db.add = MagicMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    db.delete = AsyncMock()
    db.flush = AsyncMock()
    db.execute = AsyncMock()
    return db


@pytest.fixture
def repo(mock_db):
    return AgentMCPServerRepository(mock_db)


def make_link(**kwargs):
    defaults = {
        "id": uuid4(),
        "agent_id": uuid4(),
        "mcp_server_id": uuid4(),
        "created_at": datetime.now(),
        "updated_at": datetime.now(),
    }
    return AgentMCPServerDB(**{**defaults, **kwargs})


# ---------------------------------------------------------------------------
# get
# ---------------------------------------------------------------------------


async def test_get_returns_link(repo, mock_db):
    link = make_link()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = link
    mock_db.execute.return_value = mock_result

    result = await repo.get(link.agent_id, link.mcp_server_id)

    assert result is link
    mock_db.execute.assert_awaited_once()


async def test_get_returns_none_when_not_found(repo, mock_db):
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    mock_db.execute.return_value = mock_result

    result = await repo.get(uuid4(), uuid4())

    assert result is None


# ---------------------------------------------------------------------------
# create
# ---------------------------------------------------------------------------


async def test_create_creates_with_null_tools(repo, mock_db):
    agent_id = uuid4()
    server_id = uuid4()
    data = AgentMCPServerBase(agent_id=agent_id, mcp_server_id=server_id, tools=None)

    result = await repo.create(data)

    mock_db.add.assert_called_once()
    mock_db.flush.assert_awaited_once()
    mock_db.refresh.assert_awaited_once()

    added = mock_db.add.call_args[0][0]
    assert isinstance(added, AgentMCPServerDB)
    assert added.agent_id == agent_id
    assert added.mcp_server_id == server_id
    assert added.tools is None
    assert result is added


# ---------------------------------------------------------------------------
# update
# ---------------------------------------------------------------------------


async def test_update_applies_fields(repo, mock_db):
    link = make_link(tools=None)
    new_tools = {"search": "always_allow"}

    result = await repo.update(link, AgentMCPServerPatch(tools=new_tools))

    assert link.tools == new_tools
    mock_db.add.assert_called_once_with(link)
    mock_db.flush.assert_awaited_once()
    mock_db.refresh.assert_awaited_once_with(link)
    assert result is link


async def test_update_with_empty_schema_is_noop(repo, mock_db):
    link = make_link(tools={"x": "always_allow"})

    await repo.update(link, AgentMCPServerPatch())

    assert link.tools == {"x": "always_allow"}
    mock_db.flush.assert_awaited_once()


# ---------------------------------------------------------------------------
# delete
# ---------------------------------------------------------------------------


async def test_delete_calls_delete_and_flushes(repo, mock_db):
    link = make_link()

    await repo.delete(link)

    mock_db.delete.assert_awaited_once_with(link)
    mock_db.flush.assert_awaited_once()


# ---------------------------------------------------------------------------
# delete_all_for_agent / delete_all_for_server — one bulk DELETE each
#
# Against a real engine, not a mocked session: the mock versions asserted
# `db.delete` was awaited once per link, which is a transcript of the loop that
# used to be here rather than of what a caller can observe (P3-5, P3-16).
# ---------------------------------------------------------------------------


def _add_link(session, agent_id, server_id) -> None:
    session.add(AgentMCPServerDB(agent_id=agent_id, mcp_server_id=server_id))


async def test_delete_all_for_agent_clears_only_that_agent(agent_session):
    mine, theirs = uuid4(), uuid4()
    server = uuid4()
    _add_link(agent_session, mine, server)
    _add_link(agent_session, mine, uuid4())
    _add_link(agent_session, theirs, server)
    await agent_session.flush()
    repo = AgentMCPServerRepository(agent_session)

    await repo.delete_all_for_agent(mine)

    assert await repo.list_for_agent(mine) == []
    assert len(await repo.list_for_agent(theirs)) == 1


async def test_delete_all_for_agent_is_one_statement_for_any_number_of_links(
    agent_session, statements
):
    agent_id = uuid4()
    for _ in range(4):
        _add_link(agent_session, agent_id, uuid4())
    await agent_session.flush()
    statements.reset()

    await AgentMCPServerRepository(agent_session).delete_all_for_agent(agent_id)

    assert len(statements) == 1


async def test_delete_all_for_agent_on_an_agent_with_no_links_is_harmless(
    agent_session,
):
    await AgentMCPServerRepository(agent_session).delete_all_for_agent(uuid4())


async def test_delete_all_for_server_clears_that_server_across_agents(agent_session):
    server, other_server = uuid4(), uuid4()
    agent_a, agent_b = uuid4(), uuid4()
    _add_link(agent_session, agent_a, server)
    _add_link(agent_session, agent_b, server)
    _add_link(agent_session, agent_a, other_server)
    await agent_session.flush()
    repo = AgentMCPServerRepository(agent_session)

    await repo.delete_all_for_server(server)

    assert [link.mcp_server_id for link in await repo.list_for_agent(agent_a)] == [
        other_server
    ]
    assert await repo.list_for_agent(agent_b) == []
