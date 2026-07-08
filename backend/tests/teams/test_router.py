from datetime import datetime
from unittest.mock import MagicMock
from uuid import uuid4

from fastapi.testclient import TestClient

from app.teams.models import TeamDB


def test_create_team_as_admin(client: TestClient, mock_db, admin_user):
    """Admin can create a team."""
    name_lookup = MagicMock()
    name_lookup.scalar_one_or_none.return_value = None  # name available
    mock_db.execute.return_value = name_lookup

    async def mock_refresh(obj):
        obj.id = uuid4()
        obj.created_at = datetime.now()
        obj.updated_at = datetime.now()

    mock_db.refresh = mock_refresh

    response = client.post("/teams/", json={"name": "Marketing", "color": "#6C5CE7"})

    assert response.status_code == 201
    data = response.json()
    assert data["name"] == "Marketing"
    assert data["color"] == "#6C5CE7"
    assert "id" in data


def test_create_team_rejects_invalid_color(client: TestClient, mock_db, admin_user):
    response = client.post("/teams/", json={"name": "X", "color": "#123456"})
    assert response.status_code == 422


def test_create_team_duplicate_name(client: TestClient, mock_db, admin_user):
    existing = TeamDB(
        id=uuid4(),
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
        name="Alpha",
        color="#6C5CE7",
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )
    team2 = TeamDB(
        id=uuid4(),
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
