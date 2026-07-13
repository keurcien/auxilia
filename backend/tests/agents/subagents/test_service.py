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

    mock_create.assert_awaited_once_with(supervisor_id, added_id)
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

    mock_create.assert_awaited_once_with(supervisor_id, sub_id)
