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
    defaults = dict(
        id=uuid4(),
        agent_id=uuid4(),
        mcp_server_id=uuid4(),
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )
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
