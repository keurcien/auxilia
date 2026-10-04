from datetime import datetime
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.teams.models import TeamDB
from app.teams.repository import TeamRepository
from tests.conftest import TEST_WORKSPACE_ID


@pytest.fixture(autouse=True)
def mock_team_create(monkeypatch):
    async def create(_self, team):
        team.id = uuid4()
        team.created_at = datetime.now()
        team.updated_at = datetime.now()
        return team

    monkeypatch.setattr(TeamRepository, "create", create)


def test_create_team_as_admin(client: TestClient, mock_db, admin_user):
    """Admin can create a team."""
    name_lookup = MagicMock()
    name_lookup.scalar_one_or_none.return_value = None  # name available
    mock_db.execute.return_value = name_lookup

    response = client.post("/teams/", json={"name": "Marketing", "color": "#6C5CE7"})

    assert response.status_code == 201
    data = response.json()
    assert data["name"] == "Marketing"
    assert data["color"] == "#6C5CE7"
    assert "id" in data


def test_create_team_rejects_invalid_color(client: TestClient, mock_db, admin_user):
    name_lookup = MagicMock()
    name_lookup.scalar_one_or_none.return_value = None
    mock_db.execute.return_value = name_lookup

    response = client.post("/teams/", json={"name": "X", "color": "#12345G"})
    assert response.status_code == 422


def test_create_team_duplicate_name(client: TestClient, mock_db, admin_user):
    existing = TeamDB(
        id=uuid4(),
        workspace_id=TEST_WORKSPACE_ID,
        name="Marketing",
        color=None,
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )
    name_lookup = MagicMock()
    name_lookup.scalar_one_or_none.return_value = existing
    mock_db.execute.return_value = name_lookup

    response = client.post("/teams/", json={"name": "Marketing"})

    assert response.status_code == 409
    assert response.json()["detail"] == "Team name already exists"


def test_create_team_requires_admin(client: TestClient, mock_db):
    """Without an authenticated admin the create endpoint is rejected."""
    response = client.post("/teams/", json={"name": "Marketing"})
    assert response.status_code in (401, 403)


def test_list_teams(client: TestClient, mock_db, current_user):
    team1 = TeamDB(
        id=uuid4(),
        workspace_id=TEST_WORKSPACE_ID,
        name="Alpha",
        color="#6C5CE7",
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )
    team2 = TeamDB(
        id=uuid4(),
        workspace_id=TEST_WORKSPACE_ID,
        name="Beta",
        color=None,
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )
    result = MagicMock()
    result.all.return_value = [(team1, 3), (team2, 0)]
    mock_db.execute.return_value = result

    response = client.get("/teams/")

    assert response.status_code == 200
    data = response.json()
    assert len(data) == 2
    assert data[0]["member_count"] == 3
    assert data[1]["member_count"] == 0


def test_delete_team_as_admin(client: TestClient, mock_db, admin_user):
    team = TeamDB(
        id=uuid4(),
        workspace_id=TEST_WORKSPACE_ID,
        name="Gone",
        color=None,
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )
    result = MagicMock()
    result.scalar_one_or_none.return_value = team
    mock_db.execute.return_value = result

    response = client.delete(f"/teams/{team.id}")

    assert response.status_code == 204
    mock_db.delete.assert_called_once()
