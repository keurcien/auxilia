"""The agent permission gate — `AgentRepository.get_access` and
`AgentService.require_permission` (design review §4.4).

These run against a real engine (see `conftest.py`). The gate is the one place
that decides who may touch an agent, and the thing worth pinning is what the
*database* returns for each way access can be held — owner, workspace admin,
explicit grant, team link — plus the cost, which is one query.
"""

from uuid import uuid4

import pytest

from app.agents.core.repository import AgentRepository
from app.agents.core.service import AgentService
from app.agents.models import (
    AgentDB,
    AgentTeamDB,
    AgentUserPermissionDB,
    EffectivePermission,
    PermissionLevel,
)
from app.exceptions import NotFoundError, PermissionDeniedError
from app.users.models import WorkspaceRole


async def _add_agent(session, **kwargs) -> AgentDB:
    agent = AgentDB(
        name="Agent",
        instructions="do things",
        owner_id=kwargs.pop("owner_id", uuid4()),
        **kwargs,
    )
    session.add(agent)
    await session.flush()
    return agent


async def _grant(session, agent_id, user_id, permission: PermissionLevel) -> None:
    session.add(
        AgentUserPermissionDB(agent_id=agent_id, user_id=user_id, permission=permission)
    )
    await session.flush()


async def _bind_team(session, agent_id, team_id) -> None:
    session.add(AgentTeamDB(agent_id=agent_id, team_id=team_id))
    await session.flush()


# ---------------------------------------------------------------------------
# get_access — the row
# ---------------------------------------------------------------------------


async def test_returns_the_owner_and_no_grant(agent_session):
    agent = await _add_agent(agent_session)

    access = await AgentRepository(agent_session).get_access(agent.id, user_id=uuid4())

    assert access is not None
    assert access.owner_id == agent.owner_id
    assert access.granted is None
    assert access.team_member is False


async def test_returns_this_users_grant_only(agent_session):
    agent = await _add_agent(agent_session)
    user_id = uuid4()
    await _grant(agent_session, agent.id, user_id, PermissionLevel.editor)
    await _grant(agent_session, agent.id, uuid4(), PermissionLevel.admin)

    access = await AgentRepository(agent_session).get_access(agent.id, user_id=user_id)

    assert access is not None
    assert access.granted is PermissionLevel.editor


async def test_team_membership_needs_the_users_team(agent_session):
    agent = await _add_agent(agent_session)
    team_id = uuid4()
    await _bind_team(agent_session, agent.id, team_id)
    repository = AgentRepository(agent_session)

    matched = await repository.get_access(
        agent.id, user_id=uuid4(), user_team_id=team_id
    )
    other_team = await repository.get_access(
        agent.id, user_id=uuid4(), user_team_id=uuid4()
    )
    teamless = await repository.get_access(agent.id, user_id=uuid4())

    assert matched is not None and matched.team_member is True
    assert other_team is not None and other_team.team_member is False
    assert teamless is not None and teamless.team_member is False


async def test_unknown_agent_has_no_access_row(agent_session):
    assert (
        await AgentRepository(agent_session).get_access(uuid4(), user_id=uuid4())
        is None
    )


async def test_archived_agents_are_hidden_unless_asked_for(agent_session):
    """`restore` and the permanent delete are the only callers that pass
    `include_archived`; every other gate must treat an archived agent as gone."""
    agent = await _add_agent(agent_session, is_archived=True)
    repository = AgentRepository(agent_session)

    assert await repository.get_access(agent.id, user_id=uuid4()) is None
    assert (
        await repository.get_access(agent.id, user_id=uuid4(), include_archived=True)
        is not None
    )


async def test_costs_one_query(agent_session, statements):
    """The point of `get_access` over a full read: gating an endpoint the
    frontend polls must not drag the detail assembly along."""
    agent = await _add_agent(agent_session)
    team_id = uuid4()
    await _bind_team(agent_session, agent.id, team_id)
    statements.reset()

    await AgentRepository(agent_session).get_access(
        agent.id, user_id=uuid4(), user_team_id=team_id
    )

    assert len(statements) == 1


# ---------------------------------------------------------------------------
# require_permission — the decision
# ---------------------------------------------------------------------------


async def test_owner_holds_every_level(agent_session):
    owner_id = uuid4()
    agent = await _add_agent(agent_session, owner_id=owner_id)

    permission = await AgentService(agent_session).require_permission(
        agent.id,
        at_least=EffectivePermission.admin,
        action="delete this agent",
        user_id=owner_id,
    )

    assert permission is EffectivePermission.owner


async def test_workspace_admin_holds_admin_on_someone_elses_agent(agent_session):
    agent = await _add_agent(agent_session)

    permission = await AgentService(agent_session).require_permission(
        agent.id,
        at_least=EffectivePermission.admin,
        action="delete this agent",
        user_id=uuid4(),
        user_role=WorkspaceRole.admin,
    )

    assert permission is EffectivePermission.admin


async def test_a_grant_is_checked_against_the_level_asked_for(agent_session):
    agent = await _add_agent(agent_session)
    user_id = uuid4()
    await _grant(agent_session, agent.id, user_id, PermissionLevel.editor)
    service = AgentService(agent_session)

    assert (
        await service.require_permission(
            agent.id,
            at_least=EffectivePermission.editor,
            action="edit this agent",
            user_id=user_id,
        )
        is EffectivePermission.editor
    )
    with pytest.raises(PermissionDeniedError):
        await service.require_permission(
            agent.id,
            at_least=EffectivePermission.admin,
            action="delete this agent",
            user_id=user_id,
        )


async def test_a_team_grant_stops_at_member(agent_session):
    agent = await _add_agent(agent_session)
    team_id = uuid4()
    await _bind_team(agent_session, agent.id, team_id)
    service = AgentService(agent_session)
    caller = {"user_id": uuid4(), "user_team_id": team_id}

    assert (
        await service.require_permission(
            agent.id,
            at_least=EffectivePermission.member,
            action="use this agent",
            **caller,
        )
        is EffectivePermission.member
    )
    with pytest.raises(PermissionDeniedError):
        await service.require_permission(
            agent.id,
            at_least=EffectivePermission.editor,
            action="edit this agent",
            **caller,
        )


async def test_no_relation_at_all_is_denied(agent_session):
    agent = await _add_agent(agent_session)

    with pytest.raises(PermissionDeniedError) as exc_info:
        await AgentService(agent_session).require_permission(
            agent.id,
            at_least=EffectivePermission.member,
            action="use this agent",
            user_id=uuid4(),
        )

    assert exc_info.value.detail == "Not authorized to use this agent"


async def test_an_unknown_agent_is_a_404_not_a_403(agent_session):
    """Order matters: a 403 on an id that does not exist would tell a caller
    that it does."""
    with pytest.raises(NotFoundError):
        await AgentService(agent_session).require_permission(
            uuid4(),
            at_least=EffectivePermission.member,
            action="use this agent",
            user_id=uuid4(),
        )


# ---------------------------------------------------------------------------
# the ordering itself
# ---------------------------------------------------------------------------


def test_covers_is_ordered_by_strength():
    owner = EffectivePermission.owner
    admin = EffectivePermission.admin
    editor = EffectivePermission.editor
    member = EffectivePermission.member

    assert owner.covers(admin) and admin.covers(editor) and editor.covers(member)
    assert not member.covers(editor)
    assert not editor.covers(admin)
    assert not admin.covers(owner)
    assert all(level.covers(level) for level in EffectivePermission)


def test_covers_disagrees_with_string_comparison():
    """Why `covers` exists: `EffectivePermission` is a `str` enum, so `<` and
    `>` compare alphabetically — "admin" < "editor" is True there, which is the
    opposite of what the gate means."""
    assert EffectivePermission.admin < EffectivePermission.editor
    assert EffectivePermission.admin.covers(EffectivePermission.editor)
