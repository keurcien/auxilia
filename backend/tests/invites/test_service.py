from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.invites.models import InviteCreateDB, InviteDB, InviteStatus
from app.invites.service import InviteService


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
    repo.create = AsyncMock()
    repo.revoke_pending_by_email = AsyncMock()
    return repo


@pytest.fixture
def service(mock_db, mock_repo):
    svc = InviteService(mock_db)
    svc.repository = mock_repo
    return svc


def make_invite(**kwargs):
    defaults = {
        "id": uuid4(),
        "email": "new@test.com",
        "role": "member",
        "token": "tok",
        "status": InviteStatus.pending,
        "invited_by": uuid4(),
        "expires_at": datetime.now(UTC) + timedelta(days=7),
        "team_id": None,
        "created_at": datetime.now(UTC),
        "updated_at": datetime.now(UTC),
    }
    return InviteDB(**{**defaults, **kwargs})


async def test_create_persists_team_id(service, mock_db, mock_repo):
    team_id = uuid4()
    no_user = MagicMock()
    no_user.scalar_one_or_none.return_value = None
    mock_db.execute.return_value = no_user
    mock_repo.create.return_value = make_invite(team_id=team_id)

    await service.create(
        email="new@test.com", role="member", invited_by=uuid4(), team_id=team_id
    )

    data = mock_repo.create.call_args[0][0]
    assert isinstance(data, InviteCreateDB)
    assert data.team_id == team_id


async def test_create_defaults_team_id_to_none(service, mock_db, mock_repo):
    no_user = MagicMock()
    no_user.scalar_one_or_none.return_value = None
    mock_db.execute.return_value = no_user
    mock_repo.create.return_value = make_invite()

    await service.create(email="new@test.com", role="member", invited_by=uuid4())

    data = mock_repo.create.call_args[0][0]
    assert data.team_id is None


def test_to_response_includes_team_id(service):
    team_id = uuid4()
    invite = make_invite(team_id=team_id)

    response = service._to_response(invite)

    assert response.team_id == team_id
