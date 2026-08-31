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
    defaults = {
        "id": uuid4(),
        "name": "Test Agent",
        "instructions": "Do stuff",
        "owner_id": uuid4(),
        "created_at": datetime.now(),
        "updated_at": datetime.now(),
    }
    return AgentDB(**{**defaults, **kwargs})


def make_permission(agent_id=None, **kwargs):
    defaults = {
        "id": uuid4(),
        "agent_id": agent_id or uuid4(),
        "user_id": uuid4(),
        "permission": PermissionLevel.member,
        "created_at": datetime.now(),
        "updated_at": datetime.now(),
    }
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

    rows = await repo.list_with_permissions(
        user_id=uuid4(), user_role=WorkspaceRole.member
    )

    mock_db.execute.assert_awaited_once()
    mock_result.all.assert_called_once()
    assert rows == [(agent, None, None)]


async def test_list_with_permissions_non_admin_joins_permissions(repo, mock_db):
    mock_result = MagicMock()
    mock_result.all.return_value = []
    mock_db.execute.return_value = mock_result

    await repo.list_with_permissions(user_id=uuid4(), user_role=WorkspaceRole.member)

    query_str = str(mock_db.execute.call_args[0][0])
    assert "agent_user_permissions" in query_str


async def test_list_with_permissions_admin_skips_permission_join(repo, mock_db):
    mock_result = MagicMock()
    mock_result.all.return_value = []
    mock_db.execute.return_value = mock_result

    await repo.list_with_permissions(user_id=uuid4(), user_role=WorkspaceRole.admin)

    query_str = str(mock_db.execute.call_args[0][0])
    assert "agent_user_permissions" not in query_str


async def test_list_with_permissions_no_user_skips_permission_join(repo, mock_db):
    mock_result = MagicMock()
    mock_result.all.return_value = []
    mock_db.execute.return_value = mock_result

    await repo.list_with_permissions(user_id=None, user_role=None)

    query_str = str(mock_db.execute.call_args[0][0])
    assert "agent_user_permissions" not in query_str


async def test_list_with_permissions_returns_empty_list(repo, mock_db):
    mock_result = MagicMock()
    mock_result.all.return_value = []
    mock_db.execute.return_value = mock_result

    result = await repo.list_with_permissions(user_id=None, user_role=None)

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


async def test_set_archived_flips_the_flag_in_place(agent_session):
    repo = AgentRepository(agent_session)
    agent = AgentDB(name="A", instructions="x", owner_id=uuid4())
    agent_session.add(agent)
    await agent_session.flush()

    await repo.set_archived(agent.id, archived=True)
    assert (await repo.get(agent.id)).is_archived is True

    await repo.set_archived(agent.id, archived=False)
    assert (await repo.get(agent.id)).is_archived is False


async def test_update_by_id_writes_only_the_set_fields_and_bumps_updated_at(
    agent_session,
):
    repo = AgentRepository(agent_session)
    agent = AgentDB(
        name="A", instructions="keep me", owner_id=uuid4(), description="keep me too"
    )
    agent_session.add(agent)
    await agent_session.flush()
    before = agent.updated_at

    await repo.update_by_id(agent.id, AgentPatch(name="B"))

    reread = await repo.get(agent.id)
    assert reread.name == "B"
    assert reread.instructions == "keep me"
    assert reread.description == "keep me too"
    assert reread.updated_at >= before


async def test_update_by_id_with_an_empty_patch_touches_nothing(
    agent_session, statements
):
    """Matches what the ORM path did: `sqlmodel_update({})` leaves the instance
    clean, so a PATCH naming no fields must not bump `updated_at` either."""
    repo = AgentRepository(agent_session)
    agent = AgentDB(name="A", instructions="x", owner_id=uuid4())
    agent_session.add(agent)
    await agent_session.flush()
    statements.reset()

    await repo.update_by_id(agent.id, AgentPatch())

    assert len(statements) == 0


async def test_delete_by_id_removes_the_row(agent_session):
    repo = AgentRepository(agent_session)
    agent = AgentDB(name="A", instructions="x", owner_id=uuid4())
    agent_session.add(agent)
    await agent_session.flush()

    await repo.delete_by_id(agent.id)

    assert await repo.get(agent.id) is None


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
# set_permissions / set_teams — whole-set replace, against a real engine
#
# These used to be mock mirrors: they asserted `db.delete` was awaited once per
# existing row and counted `flush`es. That is a transcript of the old
# implementation, not of its contract — rewriting the loop as one
# `DELETE ... WHERE` broke every one of them while changing nothing a caller
# can observe (design review §6.2, P3-16).
# ---------------------------------------------------------------------------


async def _permissions(session, agent_id) -> dict:
    rows = await AgentRepository(session).get_permissions(agent_id)
    return {row.user_id: row.permission for row in rows}


async def test_set_permissions_replaces_the_whole_set(agent_session):
    agent_id = uuid4()
    kept, dropped, added = uuid4(), uuid4(), uuid4()
    repo = AgentRepository(agent_session)
    await repo.set_permissions(
        agent_id,
        [
            AgentPermissionCreate(user_id=kept, permission=PermissionLevel.member),
            AgentPermissionCreate(user_id=dropped, permission=PermissionLevel.admin),
        ],
    )

    result = await repo.set_permissions(
        agent_id,
        [
            AgentPermissionCreate(user_id=kept, permission=PermissionLevel.editor),
            AgentPermissionCreate(user_id=added, permission=PermissionLevel.member),
        ],
    )

    assert {p.user_id for p in result} == {kept, added}
    assert await _permissions(agent_session, agent_id) == {
        kept: PermissionLevel.editor,
        added: PermissionLevel.member,
    }


async def test_set_permissions_with_an_empty_list_clears_the_agent(agent_session):
    agent_id = uuid4()
    repo = AgentRepository(agent_session)
    await repo.set_permissions(
        agent_id,
        [AgentPermissionCreate(user_id=uuid4(), permission=PermissionLevel.admin)],
    )

    assert await repo.set_permissions(agent_id, []) == []
    assert await _permissions(agent_session, agent_id) == {}


async def test_set_permissions_leaves_other_agents_alone(agent_session):
    """The bulk `DELETE` is only correct if its `WHERE` is."""
    mine, theirs = uuid4(), uuid4()
    other_user = uuid4()
    repo = AgentRepository(agent_session)
    await repo.set_permissions(
        theirs,
        [AgentPermissionCreate(user_id=other_user, permission=PermissionLevel.admin)],
    )

    await repo.set_permissions(
        mine,
        [AgentPermissionCreate(user_id=uuid4(), permission=PermissionLevel.member)],
    )

    assert await _permissions(agent_session, theirs) == {
        other_user: PermissionLevel.admin
    }


async def test_set_permissions_costs_two_statements_whatever_the_size(
    agent_session, statements
):
    """One `DELETE`, one `INSERT` — no per-row delete, and no `refresh` loop
    reading timestamps `AgentPermissionResponse` does not carry."""
    agent_id = uuid4()
    repo = AgentRepository(agent_session)
    await repo.set_permissions(
        agent_id,
        [AgentPermissionCreate(user_id=uuid4(), permission=PermissionLevel.member)],
    )
    statements.reset()

    await repo.set_permissions(
        agent_id,
        [
            AgentPermissionCreate(user_id=uuid4(), permission=PermissionLevel.editor)
            for _ in range(5)
        ],
    )

    assert len(statements) == 2


async def test_set_teams_replaces_the_whole_set_and_dedupes(agent_session):
    agent_id = uuid4()
    kept, dropped, added = uuid4(), uuid4(), uuid4()
    repo = AgentRepository(agent_session)
    await repo.set_teams(agent_id, [kept, dropped])

    result = await repo.set_teams(agent_id, [kept, added, added])

    assert result == [kept, added]
    assert set(await repo.get_team_ids(agent_id)) == {kept, added}


async def test_delete_all_teams_clears_only_this_agent(agent_session):
    mine, theirs = uuid4(), uuid4()
    team = uuid4()
    repo = AgentRepository(agent_session)
    await repo.set_teams(mine, [team])
    await repo.set_teams(theirs, [team])

    await repo.delete_all_teams(mine)

    assert await repo.get_team_ids(mine) == []
    assert await repo.get_team_ids(theirs) == [team]


async def test_delete_all_permissions_clears_only_this_agent(agent_session):
    mine, theirs = uuid4(), uuid4()
    other_user = uuid4()
    repo = AgentRepository(agent_session)
    await repo.set_permissions(
        mine, [AgentPermissionCreate(user_id=uuid4(), permission=PermissionLevel.admin)]
    )
    await repo.set_permissions(
        theirs,
        [AgentPermissionCreate(user_id=other_user, permission=PermissionLevel.member)],
    )

    await repo.delete_all_permissions(mine)

    assert await _permissions(agent_session, mine) == {}
    assert await _permissions(agent_session, theirs) == {
        other_user: PermissionLevel.member
    }
