from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.agents.models import AgentSubagentDB
from app.agents.subagents.service import SubagentService
from app.exceptions import DomainValidationError, PermissionDeniedError
from app.users.models import WorkspaceRole


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_db():
    db = AsyncMock()
    db.add = MagicMock()
    db.execute = AsyncMock()
    db.flush = AsyncMock()
    return db


@pytest.fixture
def mock_repo():
    repo = MagicMock()
    repo.get = AsyncMock()
    repo.list_for_supervisor = AsyncMock(return_value=[])
    repo.create_or_update = AsyncMock()
    repo.delete = AsyncMock()
    repo.has_subagents = AsyncMock(return_value=False)
    repo.is_subagent = AsyncMock(return_value=False)
    return repo


@pytest.fixture
def service(mock_db, mock_repo):
    svc = SubagentService(mock_db)
    svc.repository = mock_repo
    return svc


def make_link(supervisor_id, subagent_id):
    return AgentSubagentDB(
        id=uuid4(), supervisor_id=supervisor_id, subagent_id=subagent_id
    )


# ---------------------------------------------------------------------------
# set_for_supervisor
# ---------------------------------------------------------------------------


async def test_set_for_supervisor_noop_when_set_unchanged(service, mock_repo):
    """An unchanged set passes without the admin gate — an editor saving an
    agent whose subagents they didn't touch must not 403."""
    supervisor_id = uuid4()
    sub_id = uuid4()
    mock_repo.list_for_supervisor.return_value = [make_link(supervisor_id, sub_id)]

    await service.set_for_supervisor(
        supervisor_id, [sub_id], user_role=WorkspaceRole.editor
    )

    mock_repo.create_or_update.assert_not_called()
    mock_repo.delete.assert_not_called()


async def test_set_for_supervisor_denies_non_admin_on_change(service, mock_repo):
    supervisor_id = uuid4()
    mock_repo.list_for_supervisor.return_value = []

    with pytest.raises(PermissionDeniedError):
        await service.set_for_supervisor(
            supervisor_id, [uuid4()], user_role=WorkspaceRole.editor
        )

    mock_repo.create_or_update.assert_not_called()


async def test_set_for_supervisor_denies_none_role_on_change(service, mock_repo):
    supervisor_id = uuid4()
    existing = make_link(supervisor_id, uuid4())
    mock_repo.list_for_supervisor.return_value = [existing]

    with pytest.raises(PermissionDeniedError):
        await service.set_for_supervisor(supervisor_id, [], user_role=None)

    mock_repo.delete.assert_not_called()


async def test_set_for_supervisor_admin_adds_and_removes(service, mock_repo):
    supervisor_id = uuid4()
    kept_id, dropped_id, added_id = uuid4(), uuid4(), uuid4()
    dropped_link = make_link(supervisor_id, dropped_id)
    mock_repo.list_for_supervisor.return_value = [
        make_link(supervisor_id, kept_id),
        dropped_link,
    ]

    with patch.object(service, "create_or_update", new=AsyncMock()) as mock_create:
        await service.set_for_supervisor(
            supervisor_id, [kept_id, added_id], user_role=WorkspaceRole.admin
        )

    mock_create.assert_awaited_once_with(supervisor_id, added_id, validate_skills=True)
    mock_repo.get.assert_awaited_once_with(supervisor_id, dropped_id)


async def test_set_for_supervisor_runs_validations_through_create(service, mock_repo):
    """Additions go through create_or_update, so its validations still fire."""
    supervisor_id = uuid4()
    mock_repo.list_for_supervisor.return_value = []

    with pytest.raises(DomainValidationError):
        await service.set_for_supervisor(
            supervisor_id, [supervisor_id], user_role=WorkspaceRole.admin
        )


async def test_set_for_supervisor_deduplicates_input(service, mock_repo):
    supervisor_id = uuid4()
    sub_id = uuid4()
    mock_repo.list_for_supervisor.return_value = []

    with patch.object(service, "create_or_update", new=AsyncMock()) as mock_create:
        await service.set_for_supervisor(
            supervisor_id, [sub_id, sub_id], user_role=WorkspaceRole.admin
        )

    mock_create.assert_awaited_once_with(supervisor_id, sub_id, validate_skills=True)


async def test_replacing_a_subagent_with_a_same_named_skill_is_one_save(agent_session):
    """The P3 from review: `set_for_supervisor` added before removing, so the
    skill-name check saw the sibling this very save was dropping. Swapping A
    for B failed whenever both carried a skill of the same name, even though
    the requested graph holds only B."""
    from uuid import uuid4

    from app.agents.subagents.service import SubagentService
    from app.users.models import WorkspaceRole
    from tests.skills.conftest import attach, seed_agent, seed_skill

    service = SubagentService(agent_session)
    supervisor = await seed_agent(agent_session)
    old = await seed_agent(agent_session)
    new = await seed_agent(agent_session)
    for member in (old, new):
        await attach(
            agent_session,
            member.id,
            (await seed_skill(agent_session, owner_id=uuid4(), name="report")).id,
        )
    await service.set_for_supervisor(
        supervisor.id, [old.id], user_role=WorkspaceRole.admin
    )

    # One save, not two: the departing subagent leaves before the arriving one
    # is judged against the graph.
    await service.set_for_supervisor(
        supervisor.id, [new.id], user_role=WorkspaceRole.admin
    )

    links = await service.repository.list_for_supervisor(supervisor.id)
    assert [link.subagent_id for link in links] == [new.id]
