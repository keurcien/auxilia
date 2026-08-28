"""Tests for the auth dependencies, deliberately WITHOUT dependency overrides.

Every other router test in the suite overrides `get_current_user` /
`require_editor` / `require_admin`, so before this file no test ever executed a
role gate (backend design review §6.2, gap 1). These drive the real dependencies
against a real FastAPI app, with only the DB session faked.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from app.auth.dependencies import (
    ROLE_HIERARCHY,
    detect_auth_method,
    get_current_user,
    get_current_user_optional,
    require_admin,
    require_editor,
)
from app.auth.settings import auth_settings
from app.auth.tokens.service import TOKEN_PREFIX
from app.auth.utils import create_access_token
from app.database import get_db
from app.users.models import UserDB, WorkspaceRole


def make_user(role: WorkspaceRole = WorkspaceRole.member, **kwargs) -> UserDB:
    return UserDB(
        id=kwargs.pop("id", uuid4()),
        email=kwargs.pop("email", "a@b.io"),
        name=kwargs.pop("name", "Ada"),
        role=role,
        **kwargs,
    )


@pytest.fixture
def auth_app():
    """A tiny app exposing one endpoint per gate, with a stub DB session.

    `db.users` is the set of users the fake DB will resolve by id; `db.pats` maps
    a plaintext PAT to the user id it belongs to.
    """
    app = FastAPI()
    state = SimpleNamespace(users={}, pats={})

    @app.get("/required")
    async def required(user: UserDB = Depends(get_current_user)):
        return {"id": str(user.id), "role": user.role.value}

    @app.get("/optional")
    async def optional(user: UserDB | None = Depends(get_current_user_optional)):
        return {"id": str(user.id) if user else None}

    @app.get("/editor")
    async def editor_only(user: UserDB = Depends(require_editor)):
        return {"id": str(user.id)}

    @app.get("/admin")
    async def admin_only(user: UserDB = Depends(require_admin)):
        return {"id": str(user.id)}

    async def fake_db():
        db = AsyncMock()

        async def execute(stmt):
            # The only query the dependencies run is `select(UserDB).where(id == ...)`.
            wanted = stmt.whereclause.right.value
            result = AsyncMock()
            result.scalar_one_or_none = lambda: state.users.get(wanted)
            return result

        db.execute = execute
        yield db

    app.dependency_overrides[get_db] = fake_db
    with TestClient(app) as client:
        yield client, state


def get(client, path, *, cookie_token=None, headers=None):
    """GET `path`, optionally carrying a cookie and/or headers.

    Cookies are set on the client (TestClient deprecates per-request cookies) and
    cleared each call so one test's cookie can't authenticate the next.
    """
    client.cookies.clear()
    if cookie_token is not None:
        client.cookies.set(auth_settings.COOKIE_NAME, cookie_token)
    return client.get(path, headers=headers or {})


def token_for(user_id) -> str:
    return create_access_token(user_id)


# ---------------------------------------------------------------------------
# get_current_user
# ---------------------------------------------------------------------------


def test_no_credentials_is_401(auth_app):
    client, _ = auth_app

    assert get(client, "/required").status_code == 401


def test_valid_cookie_authenticates(auth_app):
    client, state = auth_app
    user = make_user()
    state.users[user.id] = user

    response = get(client, "/required", cookie_token=token_for(user.id))

    assert response.status_code == 200
    assert response.json()["id"] == str(user.id)


def test_cookie_for_a_deleted_user_is_401(auth_app):
    """The token decodes, but its user is gone — that is not authenticated."""
    client, _ = auth_app

    response = get(client, "/required", cookie_token=token_for(uuid4()))

    assert response.status_code == 401


def test_forged_cookie_is_401(auth_app):
    client, state = auth_app
    user = make_user()
    state.users[user.id] = user

    response = get(client, "/required", cookie_token="garbage")

    assert response.status_code == 401


def test_bearer_jwt_authenticates(auth_app):
    client, state = auth_app
    user = make_user()
    state.users[user.id] = user

    response = get(
        client,
        "/required",
        headers={"Authorization": f"Bearer {create_access_token(user.id)}"},
    )

    assert response.status_code == 200
    assert response.json()["id"] == str(user.id)


def test_a_non_bearer_authorization_header_is_ignored(auth_app):
    client, state = auth_app
    user = make_user()
    state.users[user.id] = user

    response = get(
        client,
        "/required",
        headers={"Authorization": f"Basic {create_access_token(user.id)}"},
    )

    assert response.status_code == 401


# ---------------------------------------------------------------------------
# required vs optional precedence  (backend design review §5.9)
# ---------------------------------------------------------------------------


def test_stale_cookie_plus_valid_bearer_resolves_the_bearer_user(auth_app):
    """A cookie that decodes but whose user is gone must fall through to the
    Bearer token — on BOTH dependencies. They used to disagree: required
    authenticated, optional read as anonymous."""
    client, state = auth_app
    user = make_user()
    state.users[user.id] = user
    headers = {"Authorization": f"Bearer {create_access_token(user.id)}"}
    stale = create_access_token(uuid4())

    required = get(client, "/required", cookie_token=stale, headers=headers)
    optional = get(client, "/optional", cookie_token=stale, headers=headers)

    assert required.status_code == 200
    assert required.json()["id"] == str(user.id)
    assert optional.json()["id"] == str(user.id)


def test_optional_is_anonymous_without_credentials(auth_app):
    client, _ = auth_app

    response = get(client, "/optional")

    assert response.status_code == 200
    assert response.json()["id"] is None


def test_optional_and_required_agree_on_a_valid_cookie(auth_app):
    client, state = auth_app
    user = make_user()
    state.users[user.id] = user

    required = get(client, "/required", cookie_token=token_for(user.id))
    optional = get(client, "/optional", cookie_token=token_for(user.id))

    assert required.json()["id"] == optional.json()["id"] == str(user.id)


# ---------------------------------------------------------------------------
# role gates — executed for real, not overridden
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("role", "editor_status", "admin_status"),
    [
        (WorkspaceRole.member, 403, 403),
        (WorkspaceRole.editor, 200, 403),
        (WorkspaceRole.admin, 200, 200),
    ],
)
def test_role_gates_enforce_the_hierarchy(auth_app, role, editor_status, admin_status):
    client, state = auth_app
    user = make_user(role=role)
    state.users[user.id] = user
    token = token_for(user.id)

    assert get(client, "/editor", cookie_token=token).status_code == editor_status
    assert get(client, "/admin", cookie_token=token).status_code == admin_status


def test_role_gates_401_before_403_when_unauthenticated(auth_app):
    client, _ = auth_app

    assert get(client, "/editor").status_code == 401
    assert get(client, "/admin").status_code == 401


def test_role_hierarchy_covers_every_workspace_role():
    """A new role must be given an explicit rank — `ROLE_HIERARCHY[role]` raises
    KeyError inside the gate otherwise, turning a missing rank into a 500."""
    assert set(ROLE_HIERARCHY) == set(WorkspaceRole)


def test_role_hierarchy_is_strictly_ordered():
    ranks = [
        ROLE_HIERARCHY[r]
        for r in (
            WorkspaceRole.member,
            WorkspaceRole.editor,
            WorkspaceRole.admin,
        )
    ]

    assert ranks == sorted(ranks) and len(set(ranks)) == len(ranks)


# ---------------------------------------------------------------------------
# PAT resolution
# ---------------------------------------------------------------------------


def test_pat_bearer_token_resolves_its_user(auth_app, monkeypatch):
    client, state = auth_app
    user = make_user()
    state.users[user.id] = user
    plaintext = f"{TOKEN_PREFIX}abc123"

    import app.auth.dependencies as deps

    async def fake_get_by_token(self, token):
        return SimpleNamespace(user_id=user.id) if token == plaintext else None

    monkeypatch.setattr(
        deps.PersonalAccessTokenRepository, "get_by_token", fake_get_by_token
    )

    response = get(
        client, "/required", headers={"Authorization": f"Bearer {plaintext}"}
    )

    assert response.status_code == 200
    assert response.json()["id"] == str(user.id)


def test_unknown_pat_is_401(auth_app, monkeypatch):
    client, _ = auth_app
    import app.auth.dependencies as deps

    async def fake_get_by_token(self, token):
        return None

    monkeypatch.setattr(
        deps.PersonalAccessTokenRepository, "get_by_token", fake_get_by_token
    )

    response = get(
        client, "/required", headers={"Authorization": f"Bearer {TOKEN_PREFIX}nope"}
    )

    assert response.status_code == 401


# ---------------------------------------------------------------------------
# detect_auth_method
# ---------------------------------------------------------------------------


def test_detect_auth_method_reports_cookie_when_the_cookie_is_the_authenticated_user():
    user = make_user()
    request = SimpleNamespace(
        cookies={auth_settings.COOKIE_NAME: create_access_token(user.id)}
    )

    assert detect_auth_method(request, user) == "cookie"


def test_detect_auth_method_reports_bearer_for_a_stale_cookie():
    """Mirrors the fall-through in `_resolve_request_user`: a cookie belonging to
    a different user means the request was authenticated by its bearer token."""
    user = make_user()
    request = SimpleNamespace(
        cookies={auth_settings.COOKIE_NAME: create_access_token(uuid4())}
    )

    assert detect_auth_method(request, user) == "bearer"


def test_detect_auth_method_reports_bearer_with_no_cookie():
    assert detect_auth_method(SimpleNamespace(cookies={}), make_user()) == "bearer"
