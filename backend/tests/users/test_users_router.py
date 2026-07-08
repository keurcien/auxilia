from datetime import datetime
from unittest.mock import MagicMock
from uuid import uuid4

from fastapi.testclient import TestClient

from app.teams.models import TeamDB
from app.users.models import UserDB, WorkspaceRole


def test_create_user(client: TestClient, mock_db, admin_user):
    """Test creating a new user (admin only)."""
    user_data = {
        "name": "Test User",
        "email": "test@example.com",
        "password_hash": "hashed_password",
        "role": "member",
    }

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    mock_db.execute.return_value = mock_result

    async def mock_refresh(obj):
        obj.id = uuid4()
        obj.created_at = datetime.now()
        obj.updated_at = datetime.now()

    mock_db.refresh = mock_refresh

    response = client.post("/users/", json=user_data)

    assert response.status_code == 201
    data = response.json()
    assert data["name"] == user_data["name"]
    assert data["email"] == user_data["email"]
    assert data["role"] == user_data["role"]
    assert "id" in data
    assert "created_at" in data
    assert "updated_at" in data


def test_create_user_duplicate_email(client: TestClient, mock_db, admin_user):
    """Test creating a user with duplicate email fails."""
    user_data = {
        "name": "Test User",
        "email": "duplicate@example.com",
        "password_hash": "hashed_password",
    }

    existing_user = UserDB(
        id=uuid4(),
        name="Existing User",
        email=user_data["email"],
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = existing_user
    mock_db.execute.return_value = mock_result

    response = client.post("/users/", json=user_data)
    assert response.status_code == 409
    assert response.json()["detail"] == "Email already registered"


def test_get_users(client: TestClient, mock_db, current_user):
    """Test getting all users (requires authentication)."""
    user1 = UserDB(
        id=uuid4(),
        name="User 1",
        email="user1@example.com",
        role=WorkspaceRole.member,
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )
    user2 = UserDB(
        id=uuid4(),
        name="User 2",
        email="user2@example.com",
        role=WorkspaceRole.admin,
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )

    count_result = MagicMock()
    count_result.scalar_one.return_value = 2
    rows_result = MagicMock()
    rows_result.scalars.return_value.all.return_value = [user1, user2]
    mock_db.execute.side_effect = [count_result, rows_result]

    response = client.get("/users/")
    assert response.status_code == 200
    data = response.json()
    assert len(data["items"]) == 2
    assert data["total"] == 2
    assert data["limit"] == 50
    assert data["offset"] == 0


def test_get_users_echoes_page_params(client: TestClient, mock_db, current_user):
    """limit/offset are echoed in the envelope; total is the unpaginated count."""
    count_result = MagicMock()
    count_result.scalar_one.return_value = 7
    rows_result = MagicMock()
    rows_result.scalars.return_value.all.return_value = []
    mock_db.execute.side_effect = [count_result, rows_result]

    response = client.get("/users/", params={"limit": 5, "offset": 5, "search": "ali"})
    assert response.status_code == 200
    assert response.json() == {"items": [], "total": 7, "limit": 5, "offset": 5}


def test_count_users_by_role(client: TestClient, mock_db, current_user):
    """Role counts are aggregated into the UserRoleCounts shape."""
    mock_result = MagicMock()
    mock_result.all.return_value = [
        (WorkspaceRole.member, 3),
        (WorkspaceRole.admin, 1),
    ]
    mock_db.execute.return_value = mock_result

    response = client.get("/users/role-counts")
    assert response.status_code == 200
    assert response.json() == {"total": 4, "member": 3, "editor": 0, "admin": 1}


def test_get_user(client: TestClient, mock_db, current_user):
    """Test getting a single user by ID."""
    user_id = uuid4()
    user = UserDB(
        id=user_id,
        name="Test User",
        email="getuser@example.com",
        role=WorkspaceRole.member,
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = user
    mock_db.execute.return_value = mock_result

    response = client.get(f"/users/{user_id}")
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == str(user_id)
    assert data["email"] == user.email


def test_get_user_not_found(client: TestClient, mock_db, current_user):
    """Test getting a non-existent user returns 404."""
    fake_id = uuid4()

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    mock_db.execute.return_value = mock_result

    response = client.get(f"/users/{fake_id}")
    assert response.status_code == 404
    assert response.json()["detail"] == "User not found"


def test_get_user_by_email(client: TestClient, mock_db, current_user):
    """Test getting a user by email."""
    user = UserDB(
        id=uuid4(),
        name="Test User",
        email="byemail@example.com",
        role=WorkspaceRole.member,
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = user
    mock_db.execute.return_value = mock_result

    response = client.get(f"/users/email/{user.email}")
    assert response.status_code == 200
    data = response.json()
    assert data["email"] == user.email
    assert data["name"] == user.name


def test_get_user_by_email_not_found(client: TestClient, mock_db, current_user):
    """Test getting a non-existent user by email returns 404."""
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    mock_db.execute.return_value = mock_result

    response = client.get("/users/email/nonexistent@example.com")
    assert response.status_code == 404
    assert response.json()["detail"] == "User not found"


def test_update_user(client: TestClient, mock_db, admin_user):
    """Test updating a user (admin only)."""
    user_id = uuid4()
    user = UserDB(
        id=user_id,
        name="Original Name",
        email="original@example.com",
        role=WorkspaceRole.member,
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = user
    mock_db.execute.return_value = mock_result

    update_data = {
        "name": "Updated Name",
    }

    response = client.patch(f"/users/{user_id}", json=update_data)
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == str(user_id)
    assert data["name"] == update_data["name"]


def test_update_user_role(client: TestClient, mock_db, admin_user):
    """Test updating a user's role (admin only)."""
    user_id = uuid4()
    user = UserDB(
        id=user_id,
        name="Test User",
        email="test@example.com",
        role=WorkspaceRole.member,
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = user
    mock_db.execute.return_value = mock_result

    response = client.patch(f"/users/{user_id}/role", json={"role": "admin"})
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == str(user_id)
    assert data["role"] == "admin"


def test_update_user_role_not_found(client: TestClient, mock_db, admin_user):
    """Test updating role of a non-existent user returns 404."""
    fake_id = uuid4()

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    mock_db.execute.return_value = mock_result

    response = client.patch(f"/users/{fake_id}/role", json={"role": "admin"})
    assert response.status_code == 404
    assert response.json()["detail"] == "User not found"


def test_update_user_duplicate_email(client: TestClient, mock_db, admin_user):
    """Test updating a user with an email that already exists fails."""
    user_id = uuid4()
    user = UserDB(
        id=user_id,
        name="User 2",
        email="user2@example.com",
        role=WorkspaceRole.member,
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )

    existing_user = UserDB(
        id=uuid4(),
        name="User 1",
        email="user1@example.com",
        role=WorkspaceRole.member,
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )

    # First call returns the user to update, second call returns existing user with target email
    mock_result1 = MagicMock()
    mock_result1.scalar_one_or_none.return_value = user
    mock_result2 = MagicMock()
    mock_result2.scalar_one_or_none.return_value = existing_user
    mock_db.execute.side_effect = [mock_result1, mock_result2]

    update_data = {"email": "user1@example.com"}
    response = client.patch(f"/users/{user_id}", json=update_data)
    assert response.status_code == 409
    assert response.json()["detail"] == "Email already registered"


def test_update_user_not_found(client: TestClient, mock_db, admin_user):
    """Test updating a non-existent user returns 404."""
    fake_id = uuid4()

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    mock_db.execute.return_value = mock_result

    update_data = {"name": "Updated Name"}
    response = client.patch(f"/users/{fake_id}", json=update_data)
    assert response.status_code == 404
    assert response.json()["detail"] == "User not found"


def test_delete_user(client: TestClient, mock_db, admin_user):
    """Test deleting a user."""
    user_id = uuid4()
    user = UserDB(
        id=user_id,
        name="Test User",
        email="delete@example.com",
        role=WorkspaceRole.member,
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = user
    mock_db.execute.return_value = mock_result

    response = client.delete(f"/users/{user_id}")
    assert response.status_code == 204
    mock_db.delete.assert_called_once()


def test_delete_user_not_found(client: TestClient, mock_db, admin_user):
    """Test deleting a non-existent user returns 404."""
    fake_id = uuid4()

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    mock_db.execute.return_value = mock_result

    response = client.delete(f"/users/{fake_id}")
    assert response.status_code == 404
    assert response.json()["detail"] == "User not found"


def test_update_user_team(client: TestClient, mock_db, admin_user):
    """Admin can assign a user to an existing team."""
    user_id = uuid4()
    team_id = uuid4()
    user = UserDB(
        id=user_id,
        name="Test User",
        email="teamuser@example.com",
        role=WorkspaceRole.member,
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )
    team = TeamDB(
        id=team_id,
        name="Marketing",
        color=None,
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )

    user_result = MagicMock()
    user_result.scalar_one_or_none.return_value = user
    team_result = MagicMock()
    team_result.scalar_one_or_none.return_value = team
    mock_db.execute.side_effect = [user_result, team_result]

    response = client.patch(f"/users/{user_id}/team", json={"team_id": str(team_id)})

    assert response.status_code == 200
    assert response.json()["team_id"] == str(team_id)


def test_update_user_team_unassign(client: TestClient, mock_db, admin_user):
    """Passing a null team_id clears the user's team."""
    user_id = uuid4()
    user = UserDB(
        id=user_id,
        name="Test User",
        email="teamuser@example.com",
        role=WorkspaceRole.member,
        team_id=uuid4(),
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )
    user_result = MagicMock()
    user_result.scalar_one_or_none.return_value = user
    mock_db.execute.return_value = user_result

    response = client.patch(f"/users/{user_id}/team", json={"team_id": None})

    assert response.status_code == 200
    assert response.json()["team_id"] is None


def test_update_user_team_team_not_found(client: TestClient, mock_db, admin_user):
    """Assigning a non-existent team returns 404."""
    user_id = uuid4()
    user = UserDB(
        id=user_id,
        name="Test User",
        email="teamuser@example.com",
        role=WorkspaceRole.member,
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )
    user_result = MagicMock()
    user_result.scalar_one_or_none.return_value = user
    team_result = MagicMock()
    team_result.scalar_one_or_none.return_value = None
    mock_db.execute.side_effect = [user_result, team_result]

    response = client.patch(f"/users/{user_id}/team", json={"team_id": str(uuid4())})

    assert response.status_code == 404
    assert response.json()["detail"] == "Team not found"


def test_update_user_team_requires_admin(client: TestClient, mock_db):
    """The team endpoint is admin-gated."""
    response = client.patch(f"/users/{uuid4()}/team", json={"team_id": None})
    assert response.status_code in (401, 403)
