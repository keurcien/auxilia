from collections.abc import Callable
from uuid import UUID

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.auth.settings import auth_settings
from app.auth.tokens.repository import TOKEN_PREFIX, PersonalAccessTokenRepository
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


async def _resolve_from_bearer(
    token: str, db: AsyncSession
) -> UserDB | None:
    """Resolve a Bearer token to a user — supports PATs and JWTs."""
    if token.startswith(TOKEN_PREFIX):
        repo = PersonalAccessTokenRepository(db)
        pat = await repo.resolve_token(token)
        if pat is None:
            return None
        return await _resolve_user_by_id(db, pat.user_id)

    # Fall back to JWT
    user_id = decode_access_token(token)
    if user_id is None:
        return None
    return await _resolve_user_by_id(db, user_id)


async def get_current_user(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> UserDB:
    """
    Extract and validate the current user from JWT cookie or Bearer token.
    Raises 401 if not authenticated.
    """
    # 1. Try JWT cookie
    cookie_token = request.cookies.get(auth_settings.COOKIE_NAME)
    if cookie_token:
        user_id = decode_access_token(cookie_token)
        if user_id is not None:
            user = await _resolve_user_by_id(db, user_id)
            if user is not None:
                return user

    # 2. Try Bearer token (PAT or JWT)
    bearer_token = _extract_bearer_token(request)
    if bearer_token:
        user = await _resolve_from_bearer(bearer_token, db)
        if user is not None:
            return user

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Not authenticated",
    )


async def get_current_user_optional(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> UserDB | None:
    """
    Extract the current user if present.
    Returns None if not authenticated (doesn't raise).
    """
    cookie_token = request.cookies.get(auth_settings.COOKIE_NAME)
    if cookie_token:
        user_id = decode_access_token(cookie_token)
        if user_id is not None:
            return await _resolve_user_by_id(db, user_id)

    bearer_token = _extract_bearer_token(request)
    if bearer_token:
        return await _resolve_from_bearer(bearer_token, db)

    return None


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
