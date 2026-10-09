from datetime import datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.exceptions import (
    AlreadyExistsError,
    DomainValidationError,
    NotFoundError,
)
from app.teams.models import TeamDB
from app.teams.schemas import TeamCreate, TeamPatch
from app.teams.service import TeamService
from tests.conftest import TEST_WORKSPACE_ID


@pytest.fixture
def mock_db():
    db = AsyncMock()
    db.add = MagicMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    db.delete = AsyncMock()
    db.execute = AsyncMock()
    db.flush = AsyncMock()
    return db


@pytest.fixture
def mock_repo():
    repo = MagicMock()
    repo.get = AsyncMock()
    repo.create = AsyncMock()
    repo.update = AsyncMock()
    repo.delete = AsyncMock()
    repo.get_in_workspace = AsyncMock()
    repo.get_in_workspace_for_update = repo.get_in_workspace
    repo.is_used_for_resource_visibility = AsyncMock(return_value=False)
    repo.list_with_member_counts = AsyncMock(return_value=[])
    repo.get_by_name = AsyncMock(return_value=None)
    return repo


@pytest.fixture
def service(mock_db, mock_repo):
    svc = TeamService(mock_db)
    svc.repository = mock_repo
    return svc


def make_team(**kwargs):
    defaults = {
        "id": uuid4(),
        "workspace_id": TEST_WORKSPACE_ID,
        "name": "Marketing",
        "color": "#6C5CE7",
        "created_at": datetime.now(),
        "updated_at": datetime.now(),
    }
    return TeamDB(**{**defaults, **kwargs})


async def test_create_delegates_to_repository(service, mock_repo):
    team = make_team()
    mock_repo.create.return_value = team
    data = TeamCreate(name="Marketing", color="#6C5CE7")

    result = await service.create(data, TEST_WORKSPACE_ID)

    mock_repo.get_by_name.assert_awaited_once_with(TEST_WORKSPACE_ID, "Marketing")
    created = mock_repo.create.await_args.args[0]
    assert created.workspace_id == TEST_WORKSPACE_ID
    assert created.name == data.name
    assert created.color == data.color
    assert result is team


async def test_create_raises_when_name_taken(service, mock_repo):
    mock_repo.get_by_name.return_value = make_team(name="Marketing")

    with pytest.raises(AlreadyExistsError):
        await service.create(TeamCreate(name="Marketing"), TEST_WORKSPACE_ID)

    mock_repo.create.assert_not_called()


async def test_update_raises_when_renaming_to_taken_name(service, mock_repo):
    team = make_team(name="Old")
    mock_repo.get_in_workspace.return_value = team
    mock_repo.get_by_name.return_value = make_team(name="Taken")

    with pytest.raises(AlreadyExistsError):
        await service.update(team.id, TEST_WORKSPACE_ID, TeamPatch(name="Taken"))

    mock_repo.update.assert_not_called()


async def test_update_allows_same_name(service, mock_repo):
    team = make_team(name="Marketing")
    mock_repo.get_in_workspace.return_value = team

    await service.update(
        team.id,
        TEST_WORKSPACE_ID,
        TeamPatch(name="Marketing", color="#00B894"),
    )

    mock_repo.get_by_name.assert_not_called()
    mock_repo.update.assert_awaited_once()


async def test_update_color_only_skips_name_check(service, mock_repo):
    team = make_team(name="Marketing")
    mock_repo.get_in_workspace.return_value = team

    await service.update(team.id, TEST_WORKSPACE_ID, TeamPatch(color="#00B894"))

    mock_repo.get_by_name.assert_not_called()
    mock_repo.update.assert_awaited_once()


async def test_update_rejects_empty_name(service, mock_repo):
    team = make_team(name="Marketing")
    mock_repo.get_in_workspace.return_value = team

    with pytest.raises(DomainValidationError):
        await service.update(team.id, TEST_WORKSPACE_ID, TeamPatch(name="   "))

    mock_repo.update.assert_not_called()


async def test_create_rejects_empty_name(service, mock_repo):
    with pytest.raises(DomainValidationError):
        await service.create(TeamCreate(name="  "), TEST_WORKSPACE_ID)

    mock_repo.create.assert_not_called()


async def test_get_raises_404_when_missing(service, mock_repo):
    mock_repo.get_in_workspace.return_value = None

    with pytest.raises(NotFoundError) as exc_info:
        await service.get(uuid4(), TEST_WORKSPACE_ID)

    assert exc_info.value.detail == "Team not found"


async def test_delete_delegates_to_repository(service, mock_repo):
    team = make_team()
    mock_repo.get_in_workspace.return_value = team

    await service.delete(team.id, TEST_WORKSPACE_ID)

    mock_repo.delete.assert_awaited_once_with(team)


async def test_delete_raises_404_when_missing(service, mock_repo):
    mock_repo.get_in_workspace.return_value = None

    with pytest.raises(NotFoundError):
        await service.delete(uuid4(), TEST_WORKSPACE_ID)

    mock_repo.delete.assert_not_called()


async def test_list_projects_member_counts(service, mock_repo):
    teams = [make_team(name="A"), make_team(name="B")]
    mock_repo.list_with_member_counts.return_value = [(teams[0], 3), (teams[1], 0)]

    result = await service.list(TEST_WORKSPACE_ID)

    assert [(r.name, r.member_count) for r in result] == [("A", 3), ("B", 0)]
