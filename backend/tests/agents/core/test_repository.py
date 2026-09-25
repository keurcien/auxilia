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
from app.agents.schemas import (
    AgentCreateDB,
    AgentPatch,
    AgentPermissionCreate,
    AgentSandboxConfig,
)
from app.sandbox.models import SandboxDB, SandboxProviderType
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


# ---------------------------------------------------------------------------
# Subagent links — the join table lives on the aggregate, like teams
# ---------------------------------------------------------------------------


async def _seed_agents(session, count) -> list[AgentDB]:
    agents = [make_agent(name=f"Agent {i}") for i in range(count)]
    session.add_all(agents)
    await session.flush()
    return agents


async def test_subagent_links_round_trip(agent_session):
    supervisor, first, second = await _seed_agents(agent_session, 3)
    repo = AgentRepository(agent_session)

    link = await repo.create_subagent_link(supervisor.id, first.id)
    await repo.create_subagent_link(supervisor.id, second.id)

    assert await repo.get_subagent_link(supervisor.id, first.id) == link
    assert await repo.get_subagent_link(first.id, supervisor.id) is None
    assert {
        link.subagent_id for link in await repo.list_subagent_links(supervisor.id)
    } == {
        first.id,
        second.id,
    }
    assert await repo.has_subagents(supervisor.id) is True
    assert await repo.has_subagents(first.id) is False
    assert await repo.is_subagent(first.id) is True
    assert await repo.is_subagent(supervisor.id) is False


async def test_list_subagent_links_for_agents_sees_both_sides(agent_session):
    supervisor, sub, bystander = await _seed_agents(agent_session, 3)
    repo = AgentRepository(agent_session)
    await repo.create_subagent_link(supervisor.id, sub.id)

    assert len(await repo.list_subagent_links_for_agents([supervisor.id])) == 1
    assert len(await repo.list_subagent_links_for_agents([sub.id])) == 1
    assert await repo.list_subagent_links_for_agents([bystander.id]) == []
    assert await repo.list_subagent_links_for_agents([]) == []


async def test_delete_subagent_link_removes_one_row(agent_session):
    supervisor, first, second = await _seed_agents(agent_session, 3)
    repo = AgentRepository(agent_session)
    link = await repo.create_subagent_link(supervisor.id, first.id)
    await repo.create_subagent_link(supervisor.id, second.id)

    await repo.delete_subagent_link(link)

    assert [
        link.subagent_id for link in await repo.list_subagent_links(supervisor.id)
    ] == [second.id]


async def test_delete_all_subagent_links_clears_both_directions(agent_session):
    """An agent being deleted stops supervising anyone and stops being anyone's
    subagent — and links between other agents are untouched."""
    a, b, c, d = await _seed_agents(agent_session, 4)
    repo = AgentRepository(agent_session)
    await repo.create_subagent_link(a.id, b.id)  # b is a's subagent
    await repo.create_subagent_link(c.id, b.id)  # b is also c's subagent
    await repo.create_subagent_link(a.id, d.id)  # unrelated to b

    await repo.delete_all_subagent_links(b.id)

    assert await repo.is_subagent(b.id) is False
    assert [link.subagent_id for link in await repo.list_subagent_links(a.id)] == [d.id]
    assert await repo.list_subagent_links(c.id) == []


async def test_list_by_ids_short_circuits_on_an_empty_list(repo, mock_db):
    assert await repo.list_by_ids([]) == []
    mock_db.execute.assert_not_called()


# ---------------------------------------------------------------------------
# Sandbox binding — at most one per agent (uq_agent_sandbox)
# ---------------------------------------------------------------------------


async def _seed_sandboxes(session, count) -> list[SandboxDB]:
    rows = [
        SandboxDB(
            name=f"Sandbox {i}",
            provider=SandboxProviderType.opensandbox,
            url=f"https://sandbox-{i}.example",
        )
        for i in range(count)
    ]
    session.add_all(rows)
    await session.flush()
    return rows


async def test_set_sandbox_binds_rebinds_and_unbinds(agent_session):
    (agent,) = await _seed_agents(agent_session, 1)
    first, second = await _seed_sandboxes(agent_session, 2)
    repo = AgentRepository(agent_session)

    await repo.set_sandbox(agent.id, AgentSandboxConfig(sandbox_id=first.id))
    binding = await repo.get_sandbox_binding(agent.id)
    assert binding is not None and binding.sandbox_id == first.id
    assert binding.tools is None

    # Same sandbox, new per-tool map: the row is kept and only `tools` moves.
    tools = {"execute": "needs_approval"}
    await repo.set_sandbox(
        agent.id, AgentSandboxConfig(sandbox_id=first.id, tools=tools)
    )
    rebound = await repo.get_sandbox_binding(agent.id)
    assert rebound is not None and rebound.id == binding.id
    assert rebound.tools == tools

    # Another sandbox: replaced, never two rows for one agent.
    await repo.set_sandbox(agent.id, AgentSandboxConfig(sandbox_id=second.id))
    replaced = await repo.get_sandbox_binding(agent.id)
    assert replaced is not None and replaced.sandbox_id == second.id
    assert replaced.id != binding.id
    assert [
        (link.agent_id, sandbox.id)
        for link, sandbox in await repo.list_sandbox_bindings([agent.id])
    ] == [(agent.id, second.id)]

    await repo.set_sandbox(agent.id, None)
    assert await repo.get_sandbox_binding(agent.id) is None
    assert await repo.list_sandbox_bindings([agent.id]) == []


async def test_set_sandbox_to_none_on_an_unbound_agent_is_a_noop(
    agent_session, statements
):
    (agent,) = await _seed_agents(agent_session, 1)
    repo = AgentRepository(agent_session)
    statements.reset()

    await repo.set_sandbox(agent.id, None)

    assert len(statements) == 1  # the lookup, and nothing written


async def test_list_for_sandbox_and_detach(agent_session):
    bound_a, bound_b, other = await _seed_agents(agent_session, 3)
    sandbox, other_sandbox = await _seed_sandboxes(agent_session, 2)
    repo = AgentRepository(agent_session)
    await repo.set_sandbox(bound_b.id, AgentSandboxConfig(sandbox_id=sandbox.id))
    await repo.set_sandbox(bound_a.id, AgentSandboxConfig(sandbox_id=sandbox.id))
    await repo.set_sandbox(other.id, AgentSandboxConfig(sandbox_id=other_sandbox.id))

    listed = await repo.list_for_sandbox(sandbox.id)
    assert [a.name for a in listed] == sorted([bound_a.name, bound_b.name])

    await repo.delete_all_sandbox_bindings_for_sandbox(sandbox.id)

    assert await repo.list_for_sandbox(sandbox.id) == []
    assert [a.id for a in await repo.list_for_sandbox(other_sandbox.id)] == [other.id]
