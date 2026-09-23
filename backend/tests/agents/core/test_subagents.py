"""The subagent verbs on `AgentService` — a join table on the agent aggregate,
with the one rule that matters: one level only, admin-gated on change."""

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.agents.core.service import AgentService
from app.agents.models import AgentSubagentDB
from app.exceptions import DomainValidationError, NotFoundError, PermissionDeniedError
from app.users.models import WorkspaceRole


@pytest.fixture
def mock_repo():
    repo = MagicMock()
    repo.get = AsyncMock(return_value=MagicMock(is_archived=False))
    repo.get_subagent_link = AsyncMock()
    repo.list_subagent_links = AsyncMock(return_value=[])
    repo.create_subagent_link = AsyncMock()
    repo.delete_subagent_link = AsyncMock()
    repo.has_subagents = AsyncMock(return_value=False)
    repo.is_subagent = AsyncMock(return_value=False)
    return repo


@pytest.fixture
def service(mock_repo):
    svc = AgentService(AsyncMock())
    svc.repository = mock_repo
    return svc


def make_link(supervisor_id, subagent_id):
    return AgentSubagentDB(
        id=uuid4(), supervisor_id=supervisor_id, subagent_id=subagent_id
    )


# --- set_subagents -----------------------------------------------------------


async def test_set_subagents_noop_when_set_unchanged(service, mock_repo):
    """An unchanged set passes without the admin gate — an editor saving an
    agent whose subagents they didn't touch must not 403."""
    supervisor_id = uuid4()
    sub_id = uuid4()
    mock_repo.list_subagent_links.return_value = [make_link(supervisor_id, sub_id)]

    await service.set_subagents(supervisor_id, [sub_id], user_role=WorkspaceRole.editor)

    mock_repo.create_subagent_link.assert_not_called()
    mock_repo.delete_subagent_link.assert_not_called()


async def test_set_subagents_denies_non_admin_on_change(service, mock_repo):
    with pytest.raises(PermissionDeniedError):
        await service.set_subagents(uuid4(), [uuid4()], user_role=WorkspaceRole.editor)
    mock_repo.create_subagent_link.assert_not_called()


async def test_set_subagents_denies_none_role_on_change(service, mock_repo):
    supervisor_id = uuid4()
    mock_repo.list_subagent_links.return_value = [make_link(supervisor_id, uuid4())]

    with pytest.raises(PermissionDeniedError):
        await service.set_subagents(supervisor_id, [], user_role=None)

    mock_repo.delete_subagent_link.assert_not_called()


async def test_set_subagents_admin_adds_and_removes(service, mock_repo):
    supervisor_id = uuid4()
    kept_id, dropped_id, added_id = uuid4(), uuid4(), uuid4()
    dropped_link = make_link(supervisor_id, dropped_id)
    mock_repo.list_subagent_links.return_value = [
        make_link(supervisor_id, kept_id),
        dropped_link,
    ]
    mock_repo.get_subagent_link.return_value = dropped_link

    with patch.object(
        service, "create_or_update_subagent", new=AsyncMock()
    ) as mock_create:
        await service.set_subagents(
            supervisor_id, [kept_id, added_id], user_role=WorkspaceRole.admin
        )

    mock_create.assert_awaited_once_with(supervisor_id, added_id)
    mock_repo.get_subagent_link.assert_awaited_once_with(supervisor_id, dropped_id)
    mock_repo.delete_subagent_link.assert_awaited_once_with(dropped_link)


async def test_set_subagents_runs_validations_through_create(service, mock_repo):
    """Additions go through `create_or_update_subagent`, so its validations
    still fire — here, the self-link."""
    supervisor_id = uuid4()
    with pytest.raises(DomainValidationError):
        await service.set_subagents(
            supervisor_id, [supervisor_id], user_role=WorkspaceRole.admin
        )


async def test_set_subagents_deduplicates_input(service, mock_repo):
    supervisor_id = uuid4()
    sub_id = uuid4()

    with patch.object(
        service, "create_or_update_subagent", new=AsyncMock()
    ) as mock_create:
        await service.set_subagents(
            supervisor_id, [sub_id, sub_id], user_role=WorkspaceRole.admin
        )

    mock_create.assert_awaited_once_with(supervisor_id, sub_id)


# --- create_or_update_subagent ------------------------------------------------


async def test_create_rejects_a_supervisor_that_is_itself_a_subagent(
    service, mock_repo
):
    """One level only: an agent used as a subagent cannot have subagents."""
    mock_repo.is_subagent.return_value = True
    with pytest.raises(DomainValidationError, match="already used as a subagent"):
        await service.create_or_update_subagent(uuid4(), uuid4())
    mock_repo.create_subagent_link.assert_not_called()


async def test_create_rejects_a_subagent_that_has_subagents(service, mock_repo):
    mock_repo.has_subagents.return_value = True
    with pytest.raises(DomainValidationError, match="already has subagents"):
        await service.create_or_update_subagent(uuid4(), uuid4())


async def test_create_rejects_an_archived_subagent(service, mock_repo):
    mock_repo.get.side_effect = [
        MagicMock(is_archived=False),  # the supervisor
        MagicMock(is_archived=True),  # the subagent
    ]
    with pytest.raises(NotFoundError, match="Subagent not found"):
        await service.create_or_update_subagent(uuid4(), uuid4())


async def test_create_links_when_the_graph_stays_one_level(service, mock_repo):
    supervisor_id, subagent_id = uuid4(), uuid4()
    await service.create_or_update_subagent(supervisor_id, subagent_id)
    mock_repo.create_subagent_link.assert_awaited_once_with(supervisor_id, subagent_id)


# --- delete_subagent ---------------------------------------------------------


async def test_delete_unknown_link_is_not_found(service, mock_repo):
    mock_repo.get_subagent_link.return_value = None
    with pytest.raises(NotFoundError):
        await service.delete_subagent(uuid4(), uuid4())
