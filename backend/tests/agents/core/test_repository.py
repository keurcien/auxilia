from datetime import datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.agents.core.repository import AgentRepository
from app.agents.models import (
    AgentDB,
    AgentUserPermissionDB,
    PermissionLevel,
)
from app.agents.schemas import AgentCreateDB, AgentPatch, AgentPermissionCreate
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
    data = AgentCreateDB(name="Agent X", instructions="Be helpful", owner_id=owner_id)

    result = await repo.create(data)

    mock_db.add.assert_called_once()
    mock_db.flush.assert_awaited_once()
    mock_db.refresh.assert_awaited_once()

    added = mock_db.add.call_args[0][0]
    assert isinstance(added, AgentDB)
    assert added.name == "Agent X"
    assert added.instructions == "Be helpful"
    assert added.owner_id == owner_id
    assert result is added


async def test_create_returns_validated_agent_db(repo, mock_db):
    owner_id = uuid4()
    data = AgentCreateDB(name="X", instructions="Y", owner_id=owner_id, emoji="🤖")

    result = await repo.create(data)

    assert result.emoji == "🤖"
    assert result.owner_id == owner_id


# ---------------------------------------------------------------------------
# update
# ---------------------------------------------------------------------------

async def test_update_applies_all_fields(repo, mock_db):
    agent = make_agent(name="Old Name", emoji=None)

    result = await repo.update(agent, AgentPatch(name="New Name", emoji="🤖"))

    assert agent.name == "New Name"
    assert agent.emoji == "🤖"
    assert result is agent


async def test_update_flushes_and_refreshes(repo, mock_db):
    agent = make_agent()

    await repo.update(agent, AgentPatch(name="Updated"))

    mock_db.add.assert_called_once_with(agent)
    mock_db.flush.assert_awaited_once()
    mock_db.refresh.assert_awaited_once_with(agent)


async def test_update_with_empty_schema_leaves_agent_unchanged(repo, mock_db):
    agent = make_agent(name="Original")

    await repo.update(agent, AgentPatch())

    assert agent.name == "Original"
    mock_db.flush.assert_awaited_once()


# ---------------------------------------------------------------------------
# archive
# ---------------------------------------------------------------------------

async def test_archive_sets_is_archived_and_flushes(repo, mock_db):
    agent = make_agent()

    await repo.archive(agent)

    assert agent.is_archived is True
    mock_db.add.assert_called_once_with(agent)
    mock_db.flush.assert_awaited_once()


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

    new_write = AgentPermissionCreate(user_id=uuid4(), permission=PermissionLevel.editor)
    await repo.set_permissions(agent_id, [new_write])

    mock_db.delete.assert_awaited_once_with(existing)
    assert mock_db.flush.await_count == 2


async def test_set_permissions_inserts_new_permissions(repo, mock_db):
    agent_id = uuid4()
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = []
    mock_db.execute.return_value = mock_result

    new_user_id = uuid4()
    new_write = AgentPermissionCreate(user_id=new_user_id, permission=PermissionLevel.editor)
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
        AgentPermissionCreate(user_id=uuid4(), permission=PermissionLevel.user),
        AgentPermissionCreate(user_id=uuid4(), permission=PermissionLevel.editor),
    ]
    result = await repo.set_permissions(agent_id, writes)

    assert mock_db.refresh.await_count == 2
    assert len(result) == 2
