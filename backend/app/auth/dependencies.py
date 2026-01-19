from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.auth.settings import auth_settings
from app.auth.utils import decode_access_token
from app.database import get_db
from app.users.models import UserDB


async def get_current_user(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> UserDB:
    """
    Extract and validate the current user from the JWT cookie.
    Raises 401 if not authenticated.
    """
    token = request.cookies.get(auth_settings.COOKIE_NAME)

    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )

    user_id = decode_access_token(token)
    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        )

    result = await db.execute(select(UserDB).where(UserDB.id == user_id))
    user = result.scalar_one_or_none()

    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
        )

    return user


async def get_current_user_optional(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> UserDB | None:
    """
    Extract the current user from the JWT cookie if present.
    Returns None if not authenticated (doesn't raise).
    """
    token = request.cookies.get(auth_settings.COOKIE_NAME)

    if not token:
        return None

    user_id = decode_access_token(token)
    if user_id is None:
        return None

    result = await db.execute(select(UserDB).where(UserDB.id == user_id))
    return result.scalar_one_or_none()


async def get_current_superuser(
    current_user: UserDB = Depends(get_current_user),
) -> UserDB:
    """
    Require the current user to be a superuser.
    Raises 403 if not a superuser.
    """
    if not current_user.is_superuser:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Superuser access required",
        )
    return current_user
