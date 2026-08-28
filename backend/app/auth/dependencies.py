from collections.abc import Callable
from typing import Literal
from uuid import UUID

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.auth.settings import auth_settings
from app.auth.tokens.repository import PersonalAccessTokenRepository
from app.auth.tokens.service import TOKEN_PREFIX
from app.auth.utils import decode_access_token
from app.database import get_db
from app.users.models import UserDB, WorkspaceRole


ROLE_HIERARCHY: dict[WorkspaceRole, int] = {
    WorkspaceRole.member: 0,
    WorkspaceRole.editor: 1,
    WorkspaceRole.admin: 2,
}


async def _resolve_user_by_id(db: AsyncSession, user_id: UUID) -> UserDB | None:
    result = await db.execute(select(UserDB).where(UserDB.id == user_id))
    return result.scalar_one_or_none()


def _extract_bearer_token(request: Request) -> str | None:
    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.startswith("Bearer "):
        return auth_header[7:]
    return None


async def _resolve_from_bearer(token: str, db: AsyncSession) -> UserDB | None:
    """Resolve a Bearer token to a user — supports PATs and JWTs."""
    if token.startswith(TOKEN_PREFIX):
        repo = PersonalAccessTokenRepository(db)
        pat = await repo.get_by_token(token)
        if pat is None:
            return None
        return await _resolve_user_by_id(db, pat.user_id)

    # Fall back to JWT
    user_id = decode_access_token(token)
    if user_id is None:
        return None
    return await _resolve_user_by_id(db, user_id)


async def _resolve_request_user(request: Request, db: AsyncSession) -> UserDB | None:
    """Resolve the request's user: JWT cookie first, then a Bearer token (PAT or JWT).

    The single resolver for both dependencies below. They used to implement this
    separately and had drifted: the optional one returned the cookie lookup
    directly, so a *stale* cookie (one that decodes but whose user no longer
    exists) plus a valid PAT authenticated on required endpoints and read as
    anonymous on optional ones. `detect_auth_method` documents the same
    fall-through and must keep matching this order.
    """
    cookie_token = request.cookies.get(auth_settings.COOKIE_NAME)
    if cookie_token:
        user_id = decode_access_token(cookie_token)
        if user_id is not None:
            user = await _resolve_user_by_id(db, user_id)
            if user is not None:
                return user

    bearer_token = _extract_bearer_token(request)
    if bearer_token:
        return await _resolve_from_bearer(bearer_token, db)

    return None


async def get_current_user(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> UserDB:
    """Required auth: the current user from a JWT cookie or Bearer token.

    Raises 401 if not authenticated.
    """
    user = await _resolve_request_user(request, db)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )
    return user


async def get_current_user_optional(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> UserDB | None:
    """Optional auth: the current user if the request carries valid credentials,
    otherwise None (never raises)."""
    return await _resolve_request_user(request, db)


def require_role(minimum_role: WorkspaceRole) -> Callable:
    """Factory that returns a FastAPI dependency requiring a minimum workspace role."""

    async def dependency(
        current_user: UserDB = Depends(get_current_user),
    ) -> UserDB:
        if ROLE_HIERARCHY[current_user.role] < ROLE_HIERARCHY[minimum_role]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"{minimum_role.value} access required",
            )
        return current_user

    return dependency


require_admin = require_role(WorkspaceRole.admin)
require_editor = require_role(WorkspaceRole.editor)


def detect_auth_method(
    request: Request, current_user: UserDB
) -> Literal["cookie", "bearer"]:
    """Return how the current request was authenticated.

    Mirrors the precedence in ``get_current_user``: cookie wins only when the
    cookie decodes to the authenticated user. A cookie that merely *decodes* is
    not enough — if its user_id no longer exists in the DB, ``get_current_user``
    falls through to bearer and the resolved user comes from the bearer token.
    We must do the same comparison, otherwise a stale cookie + valid bearer
    gets misclassified as cookie auth.
    """
    cookie_token = request.cookies.get(auth_settings.COOKIE_NAME)
    if cookie_token:
        cookie_user_id = decode_access_token(cookie_token)
        if cookie_user_id == current_user.id:
            return "cookie"
    return "bearer"
