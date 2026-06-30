from datetime import datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.exceptions import AlreadyExistsError, NotFoundError
from app.teams.models import TeamDB
from app.teams.schemas import TeamCreate, TeamPatch
from app.teams.service import TeamService


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
    repo.list_all = AsyncMock(return_value=[])
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

    result = await service.create(data)

    mock_repo.get_by_name.assert_awaited_once_with("Marketing")
    mock_repo.create.assert_awaited_once_with(data)
    assert result is team


async def test_create_raises_when_name_taken(service, mock_repo):
    mock_repo.get_by_name.return_value = make_team(name="Marketing")

    with pytest.raises(AlreadyExistsError):
        await service.create(TeamCreate(name="Marketing"))

    mock_repo.create.assert_not_called()


async def test_update_raises_when_renaming_to_taken_name(service, mock_repo):
    team = make_team(name="Old")
    mock_repo.get.return_value = team
    mock_repo.get_by_name.return_value = make_team(name="Taken")

    with pytest.raises(AlreadyExistsError):
        await service.update(team.id, TeamPatch(name="Taken"))

    mock_repo.update.assert_not_called()


async def test_update_allows_same_name(service, mock_repo):
    team = make_team(name="Marketing")
    mock_repo.get.return_value = team

    await service.update(team.id, TeamPatch(name="Marketing", color="#00B894"))

    mock_repo.get_by_name.assert_not_called()
    mock_repo.update.assert_awaited_once()


async def test_update_color_only_skips_name_check(service, mock_repo):
    team = make_team(name="Marketing")
    mock_repo.get.return_value = team

    await service.update(team.id, TeamPatch(color="#00B894"))

    mock_repo.get_by_name.assert_not_called()
    mock_repo.update.assert_awaited_once()


async def test_get_raises_404_when_missing(service, mock_repo):
    mock_repo.get.return_value = None

    with pytest.raises(NotFoundError) as exc_info:
        await service.get(uuid4())

    assert exc_info.value.detail == "Team not found"


async def test_delete_delegates_to_repository(service, mock_repo):
    team = make_team()
    mock_repo.get.return_value = team

    await service.delete(team.id)

    mock_repo.delete.assert_awaited_once_with(team)


async def test_delete_raises_404_when_missing(service, mock_repo):
    mock_repo.get.return_value = None

    with pytest.raises(NotFoundError):
        await service.delete(uuid4())

    mock_repo.delete.assert_not_called()


async def test_list_delegates_to_repository(service, mock_repo):
    teams = [make_team(name="A"), make_team(name="B")]
    mock_repo.list_all.return_value = teams

    result = await service.list()

    assert result == teams
