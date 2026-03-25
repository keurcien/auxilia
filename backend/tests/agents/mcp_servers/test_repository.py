from datetime import datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.agents.mcp_servers.repository import MCPBindingRepository
from app.agents.models import AgentMCPServerBindingDB


@pytest.fixture
def mock_db():
    db = AsyncMock()
    db.add = MagicMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    db.delete = AsyncMock()
    db.execute = AsyncMock()
    return db


@pytest.fixture
def repo(mock_db):
    return MCPBindingRepository(mock_db)


def make_binding(**kwargs):
    defaults = dict(
        id=uuid4(),
        agent_id=uuid4(),
        mcp_server_id=uuid4(),
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )
    return AgentMCPServerBindingDB(**{**defaults, **kwargs})


# ---------------------------------------------------------------------------
# get_binding
# ---------------------------------------------------------------------------

async def test_get_binding_returns_binding(repo, mock_db):
    binding = make_binding()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = binding
    mock_db.execute.return_value = mock_result

    result = await repo.get_binding(binding.agent_id, binding.mcp_server_id)

    assert result is binding
    mock_db.execute.assert_awaited_once()


async def test_get_binding_returns_none_when_not_found(repo, mock_db):
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    mock_db.execute.return_value = mock_result

    result = await repo.get_binding(uuid4(), uuid4())

    assert result is None


# ---------------------------------------------------------------------------
# create_binding
# ---------------------------------------------------------------------------

async def test_create_binding_creates_with_null_tools(repo, mock_db):
    agent_id = uuid4()
    server_id = uuid4()

    result = await repo.create_binding(agent_id, server_id)

    mock_db.add.assert_called_once()
    mock_db.commit.assert_awaited_once()
    mock_db.refresh.assert_awaited_once()

    added = mock_db.add.call_args[0][0]
    assert isinstance(added, AgentMCPServerBindingDB)
    assert added.agent_id == agent_id
    assert added.mcp_server_id == server_id
    assert added.tools is None
    assert result is added


# ---------------------------------------------------------------------------
# update_binding
# ---------------------------------------------------------------------------

async def test_update_binding_applies_fields(repo, mock_db):
    binding = make_binding(tools=None)
    new_tools = {"search": "always_allow"}

    result = await repo.update_binding(binding, {"tools": new_tools})

    assert binding.tools == new_tools
    mock_db.add.assert_called_once_with(binding)
    mock_db.commit.assert_awaited_once()
    mock_db.refresh.assert_awaited_once_with(binding)
    assert result is binding


async def test_update_binding_with_empty_dict_is_noop(repo, mock_db):
    binding = make_binding(tools={"x": "always_allow"})

    await repo.update_binding(binding, {})

    assert binding.tools == {"x": "always_allow"}
    mock_db.commit.assert_awaited_once()


# ---------------------------------------------------------------------------
# delete_binding
# ---------------------------------------------------------------------------

async def test_delete_binding_calls_delete_and_commits(repo, mock_db):
    binding = make_binding()

    await repo.delete_binding(binding)

    mock_db.delete.assert_awaited_once_with(binding)
    mock_db.commit.assert_awaited_once()
