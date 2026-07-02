from datetime import datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.exceptions import (
    AlreadyExistsError,
    DomainValidationError,
    NotFoundError,
)
from app.tags.models import TagDB
from app.tags.schemas import TagCreate, TagPatch
from app.tags.service import TagService


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
    svc = TagService(mock_db)
    svc.repository = mock_repo
    return svc


def make_tag(**kwargs):
    defaults = {
        "id": uuid4(),
        "name": "Data",
        "created_at": datetime.now(),
        "updated_at": datetime.now(),
    }
    return TagDB(**{**defaults, **kwargs})


async def test_create_delegates_to_repository(service, mock_repo):
    tag = make_tag()
    mock_repo.create.return_value = tag
    data = TagCreate(name="Data")

    result = await service.create(data)

    mock_repo.get_by_name.assert_awaited_once_with("Data")
    mock_repo.create.assert_awaited_once_with(data)
    assert result is tag


async def test_create_raises_when_name_taken(service, mock_repo):
    mock_repo.get_by_name.return_value = make_tag(name="Data")

    with pytest.raises(AlreadyExistsError):
        await service.create(TagCreate(name="Data"))

    mock_repo.create.assert_not_called()


async def test_update_raises_when_renaming_to_taken_name(service, mock_repo):
    tag = make_tag(name="Old")
    mock_repo.get.return_value = tag
    mock_repo.get_by_name.return_value = make_tag(name="Taken")

    with pytest.raises(AlreadyExistsError):
        await service.update(tag.id, TagPatch(name="Taken"))

    mock_repo.update.assert_not_called()


async def test_update_allows_same_name(service, mock_repo):
    tag = make_tag(name="Data")
    mock_repo.get.return_value = tag

    await service.update(tag.id, TagPatch(name="Data"))

    mock_repo.get_by_name.assert_not_called()
    mock_repo.update.assert_awaited_once()


async def test_update_rejects_empty_name(service, mock_repo):
    tag = make_tag(name="Data")
    mock_repo.get.return_value = tag

    with pytest.raises(DomainValidationError):
        await service.update(tag.id, TagPatch(name="   "))

    mock_repo.update.assert_not_called()


async def test_create_rejects_empty_name(service, mock_repo):
    with pytest.raises(DomainValidationError):
        await service.create(TagCreate(name="  "))

    mock_repo.create.assert_not_called()


async def test_create_stores_trimmed_name(service, mock_repo):
    """ " Data " must dedupe against "Data", not slip past the unique index."""
    mock_repo.create.return_value = make_tag(name="Data")

    await service.create(TagCreate(name="  Data  "))

    mock_repo.get_by_name.assert_awaited_once_with("Data")
    assert mock_repo.create.call_args[0][0].name == "Data"


async def test_update_stores_trimmed_name(service, mock_repo):
    tag = make_tag(name="Old")
    mock_repo.get.return_value = tag

    await service.update(tag.id, TagPatch(name="  Data  "))

    mock_repo.get_by_name.assert_awaited_once_with("Data")
    assert mock_repo.update.call_args[0][1].name == "Data"


async def test_get_raises_404_when_missing(service, mock_repo):
    mock_repo.get.return_value = None

    with pytest.raises(NotFoundError) as exc_info:
        await service.get(uuid4())

    assert exc_info.value.detail == "Tag not found"


async def test_delete_delegates_to_repository(service, mock_repo):
    tag = make_tag()
    mock_repo.get.return_value = tag

    await service.delete(tag.id)

    mock_repo.delete.assert_awaited_once_with(tag)


async def test_delete_raises_404_when_missing(service, mock_repo):
    mock_repo.get.return_value = None

    with pytest.raises(NotFoundError):
        await service.delete(uuid4())

    mock_repo.delete.assert_not_called()


async def test_list_delegates_to_repository(service, mock_repo):
    tags = [make_tag(name="A"), make_tag(name="B")]
    mock_repo.list_all.return_value = tags

    result = await service.list()

    assert result == tags
