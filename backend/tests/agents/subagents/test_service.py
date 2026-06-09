from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.agents.subagents.service import SubagentService
from app.exceptions import PermissionDeniedError
from app.users.models import WorkspaceRole


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_db():
    db = AsyncMock()
    db.add = MagicMock()
    db.execute = AsyncMock()
    return db


@pytest.fixture
def service(mock_db):
    svc = SubagentService(mock_db)
    svc.repository = MagicMock()
    svc.repository.list_for_supervisor = AsyncMock(return_value=[])
    svc.create_or_update = AsyncMock()
    svc.delete = AsyncMock()
    return svc


def make_link(supervisor_id, subagent_id):
    link = MagicMock()
    link.supervisor_id = supervisor_id
    link.subagent_id = subagent_id
    return link


# ---------------------------------------------------------------------------
# set_for_supervisor
# ---------------------------------------------------------------------------


async def test_set_for_supervisor_noop_when_unchanged_for_non_admin(service):
    supervisor_id = uuid4()
    subagent_id = uuid4()
    service.repository.list_for_supervisor.return_value = [
        make_link(supervisor_id, subagent_id)
    ]

    await service.set_for_supervisor(
        supervisor_id, [subagent_id], user_role=WorkspaceRole.member
    )

    service.create_or_update.assert_not_awaited()
    service.delete.assert_not_awaited()


async def test_set_for_supervisor_raises_403_for_non_admin_change(service):
    with pytest.raises(PermissionDeniedError):
        await service.set_for_supervisor(
            uuid4(), [uuid4()], user_role=WorkspaceRole.editor
        )

    service.create_or_update.assert_not_awaited()
    service.delete.assert_not_awaited()


async def test_set_for_supervisor_adds_and_removes_for_admin(service):
    supervisor_id = uuid4()
    kept_id = uuid4()
    removed_id = uuid4()
    added_id = uuid4()
    service.repository.list_for_supervisor.return_value = [
        make_link(supervisor_id, kept_id),
        make_link(supervisor_id, removed_id),
    ]

    await service.set_for_supervisor(
        supervisor_id, [kept_id, added_id], user_role=WorkspaceRole.admin
    )

    service.create_or_update.assert_awaited_once_with(supervisor_id, added_id)
    service.delete.assert_awaited_once_with(supervisor_id, removed_id)
