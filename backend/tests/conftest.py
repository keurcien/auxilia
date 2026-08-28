import os

from pydantic import ValidationError


# Must run before anything imports `app.main`. `app/mcp/servers/settings.py`
# constructs `MCPServerSettings()` at module scope and its `require_salt`
# validator raises without SALT, so on a checkout with no .env the suite fails to
# *collect*, not merely to pass.
#
# Ask pydantic whether a salt is already configured rather than guessing: it reads
# the shell environment *and* the repo .env, and env vars outrank .env. A plain
# `os.environ.setdefault` would therefore override a developer's .env-only SALT
# with the dummy — silently running the encryption tests against a different key
# than the one their deployment uses.
try:
    import app.mcp.servers.settings
except ValidationError:
    # Genuinely unset (a cold clone, or CI). A failed module init is dropped from
    # sys.modules, so the real import below re-executes with this in place.
    os.environ["SALT"] = "test-salt-not-a-real-secret"

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.auth.dependencies import (
    get_current_user,
    require_admin,
    require_editor,
)
from app.database import get_db
from app.main import app
from app.users.models import UserDB, WorkspaceRole


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
        password_hash="hashed_password",
    )
    app.dependency_overrides[get_current_user] = lambda: user
    yield user
    app.dependency_overrides.clear()


@pytest.fixture
def editor_user():
    """Create an editor user and override get_current_user and require_editor."""
    user = UserDB(
        id=uuid4(),
        name="Editor User",
        email="editor@test.com",
        role=WorkspaceRole.editor,
        password_hash="hashed_password",
    )
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[require_editor] = lambda: user
    yield user
    app.dependency_overrides.clear()


@pytest.fixture
def admin_user():
    """Create an admin user and override get_current_user, require_editor, and require_admin."""
    user = UserDB(
        id=uuid4(),
        name="Admin User",
        email="admin@test.com",
        role=WorkspaceRole.admin,
        password_hash="hashed_password",
    )
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[require_editor] = lambda: user
    app.dependency_overrides[require_admin] = lambda: user
    yield user
    app.dependency_overrides.clear()
