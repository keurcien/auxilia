from datetime import datetime
from uuid import uuid4
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.agents.models import (
    AgentCreate,
    AgentDB,
    AgentMCPServerBindingDB,
    AgentPermissionWrite,
    AgentUserPermissionDB,
    PermissionLevel,
)
from app.agents.repository import AgentRepository
from app.users.models import WorkspaceRole


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
    return AgentRepository(mock_db)


def make_agent(**kwargs):
    defaults = dict(
        id=uuid4(),
        name="Test Agent",
        instructions="Do stuff",
        owner_id=uuid4(),
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )
    return AgentDB(**{**defaults, **kwargs})


def make_binding(**kwargs):
    defaults = dict(
        id=uuid4(),
        agent_id=uuid4(),
        mcp_server_id=uuid4(),
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )
    return AgentMCPServerBindingDB(**{**defaults, **kwargs})


def make_permission(agent_id=None, **kwargs):
    defaults = dict(
        id=uuid4(),
        agent_id=agent_id or uuid4(),
        user_id=uuid4(),
        permission=PermissionLevel.user,
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )
    return AgentUserPermissionDB(**{**defaults, **kwargs})


# ---------------------------------------------------------------------------
# get
# ---------------------------------------------------------------------------

async def test_get_returns_agent(repo, mock_db):
    agent = make_agent()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = agent
    mock_db.execute.return_value = mock_result

    result = await repo.get(agent.id)

    assert result is agent
    mock_db.execute.assert_awaited_once()
    mock_result.scalar_one_or_none.assert_called_once()


async def test_get_returns_none_when_not_found(repo, mock_db):
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    mock_db.execute.return_value = mock_result

    result = await repo.get(uuid4())

    assert result is None


# ---------------------------------------------------------------------------
# list_with_permissions
# ---------------------------------------------------------------------------

async def test_list_with_permissions_returns_rows(repo, mock_db):
    agent = make_agent()
    mock_result = MagicMock()
    mock_result.all.return_value = [(agent, None, None)]
    mock_db.execute.return_value = mock_result

    rows = await repo.list_with_permissions(uuid4(), WorkspaceRole.member)

    mock_db.execute.assert_awaited_once()
    mock_result.all.assert_called_once()
    assert rows == [(agent, None, None)]


async def test_list_with_permissions_non_admin_joins_permissions(repo, mock_db):
    mock_result = MagicMock()
    mock_result.all.return_value = []
    mock_db.execute.return_value = mock_result

    await repo.list_with_permissions(uuid4(), WorkspaceRole.member)

    query_str = str(mock_db.execute.call_args[0][0])
    assert "agent_user_permissions" in query_str


async def test_list_with_permissions_admin_skips_permission_join(repo, mock_db):
    mock_result = MagicMock()
    mock_result.all.return_value = []
    mock_db.execute.return_value = mock_result

    await repo.list_with_permissions(uuid4(), WorkspaceRole.admin)

    query_str = str(mock_db.execute.call_args[0][0])
    assert "agent_user_permissions" not in query_str


async def test_list_with_permissions_no_user_skips_permission_join(repo, mock_db):
    mock_result = MagicMock()
    mock_result.all.return_value = []
    mock_db.execute.return_value = mock_result

    await repo.list_with_permissions(None, None)

    query_str = str(mock_db.execute.call_args[0][0])
    assert "agent_user_permissions" not in query_str


async def test_list_with_permissions_returns_empty_list(repo, mock_db):
    mock_result = MagicMock()
    mock_result.all.return_value = []
    mock_db.execute.return_value = mock_result

    result = await repo.list_with_permissions(None, None)

    assert result == []


# ---------------------------------------------------------------------------
# create
# ---------------------------------------------------------------------------

async def test_create_adds_commits_and_refreshes(repo, mock_db):
    owner_id = uuid4()
    data = AgentCreate(name="Agent X", instructions="Be helpful", owner_id=owner_id)

    result = await repo.create(data)

    mock_db.add.assert_called_once()
    mock_db.commit.assert_awaited_once()
    mock_db.refresh.assert_awaited_once()

    added = mock_db.add.call_args[0][0]
    assert isinstance(added, AgentDB)
    assert added.name == "Agent X"
    assert added.instructions == "Be helpful"
    assert added.owner_id == owner_id
    assert result is added


async def test_create_returns_validated_agent_db(repo, mock_db):
    owner_id = uuid4()
    data = AgentCreate(name="X", instructions="Y", owner_id=owner_id, emoji="🤖")

    result = await repo.create(data)

    assert result.emoji == "🤖"
    assert result.owner_id == owner_id


# ---------------------------------------------------------------------------
# update
# ---------------------------------------------------------------------------

async def test_update_applies_all_fields(repo, mock_db):
    agent = make_agent(name="Old Name", emoji=None)

    result = await repo.update(agent, {"name": "New Name", "emoji": "🤖"})

    assert agent.name == "New Name"
    assert agent.emoji == "🤖"
    assert result is agent


async def test_update_commits_and_refreshes(repo, mock_db):
    agent = make_agent()

    await repo.update(agent, {"name": "Updated"})

    mock_db.add.assert_called_once_with(agent)
    mock_db.commit.assert_awaited_once()
    mock_db.refresh.assert_awaited_once_with(agent)


async def test_update_with_empty_dict_leaves_agent_unchanged(repo, mock_db):
    agent = make_agent(name="Original")

    await repo.update(agent, {})

    assert agent.name == "Original"
    mock_db.commit.assert_awaited_once()


# ---------------------------------------------------------------------------
# delete
# ---------------------------------------------------------------------------

async def test_delete_calls_delete_and_commits(repo, mock_db):
    agent = make_agent()

    await repo.delete(agent)

    mock_db.delete.assert_awaited_once_with(agent)
    mock_db.commit.assert_awaited_once()


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


# ---------------------------------------------------------------------------
# get_permissions
# ---------------------------------------------------------------------------

async def test_get_permissions_returns_list(repo, mock_db):
    agent_id = uuid4()
    perm = make_permission(agent_id=agent_id)
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = [perm]
    mock_db.execute.return_value = mock_result

    result = await repo.get_permissions(agent_id)

    assert result == [perm]
    mock_db.execute.assert_awaited_once()


async def test_get_permissions_returns_empty_list_when_none(repo, mock_db):
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = []
    mock_db.execute.return_value = mock_result

    result = await repo.get_permissions(uuid4())

    assert result == []


# ---------------------------------------------------------------------------
# set_permissions
# ---------------------------------------------------------------------------

async def test_set_permissions_deletes_existing_before_inserting(repo, mock_db):
    agent_id = uuid4()
    existing = make_permission(agent_id=agent_id)
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = [existing]
    mock_db.execute.return_value = mock_result

    new_write = AgentPermissionWrite(user_id=uuid4(), permission=PermissionLevel.editor)
    await repo.set_permissions(agent_id, [new_write])

    mock_db.delete.assert_awaited_once_with(existing)
    mock_db.flush.assert_awaited_once()
    mock_db.commit.assert_awaited_once()


async def test_set_permissions_inserts_new_permissions(repo, mock_db):
    agent_id = uuid4()
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = []
    mock_db.execute.return_value = mock_result

    new_user_id = uuid4()
    new_write = AgentPermissionWrite(user_id=new_user_id, permission=PermissionLevel.editor)
    result = await repo.set_permissions(agent_id, [new_write])

    mock_db.add.assert_called_once()
    added = mock_db.add.call_args[0][0]
    assert isinstance(added, AgentUserPermissionDB)
    assert added.agent_id == agent_id
    assert added.user_id == new_user_id
    assert added.permission == PermissionLevel.editor
    assert len(result) == 1


async def test_set_permissions_with_empty_list_clears_all(repo, mock_db):
    agent_id = uuid4()
    existing = make_permission(agent_id=agent_id)
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = [existing]
    mock_db.execute.return_value = mock_result

    result = await repo.set_permissions(agent_id, [])

    mock_db.delete.assert_awaited_once_with(existing)
    mock_db.add.assert_not_called()
    assert result == []


async def test_set_permissions_refreshes_each_new_permission(repo, mock_db):
    agent_id = uuid4()
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = []
    mock_db.execute.return_value = mock_result

    writes = [
        AgentPermissionWrite(user_id=uuid4(), permission=PermissionLevel.user),
        AgentPermissionWrite(user_id=uuid4(), permission=PermissionLevel.editor),
    ]
    result = await repo.set_permissions(agent_id, writes)

    assert mock_db.refresh.await_count == 2
    assert len(result) == 2
