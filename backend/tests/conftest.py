import pytest
from uuid import uuid4
from unittest.mock import AsyncMock, MagicMock
from fastapi.testclient import TestClient
from app.database import get_db
from app.main import app
from app.users.models import UserDB, WorkspaceRole
from app.auth.dependencies import get_current_user, require_admin


@pytest.fixture
def mock_db():
    """Create a mock database session."""
    db = AsyncMock()
    db.add = MagicMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    db.delete = AsyncMock()
    db.execute = AsyncMock()
    return db


@pytest.fixture
def client(mock_db):
    """Create a test client with mocked database dependency."""

    async def override_get_db():
        yield mock_db

    app.dependency_overrides[get_db] = override_get_db
    client = TestClient(app)
    yield client
    app.dependency_overrides.clear()


@pytest.fixture
def current_user():
    """Create a test user and override the get_current_user dependency."""
    user = UserDB(
        id=uuid4(),
        name="Test User",
        email="test@test.com",
        role=WorkspaceRole.member,
        hashed_password="hashed_password"
    )
    app.dependency_overrides[get_current_user] = lambda: user
    yield user
    app.dependency_overrides.clear()


@pytest.fixture
def admin_user():
    """Create an admin user and override both get_current_user and require_admin."""
    user = UserDB(
        id=uuid4(),
        name="Admin User",
        email="admin@test.com",
        role=WorkspaceRole.admin,
        hashed_password="hashed_password"
    )
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[require_admin] = lambda: user
    yield user
    app.dependency_overrides.clear()
