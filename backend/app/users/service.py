# These functions are decoupled from FastAPI so they can be called
# from route handlers, integrations (Slack, etc.), background tasks,
# or tests — just pass a db session explicitly.

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.users.models import UserDB


async def get_user_by_email(email: str, db: AsyncSession) -> UserDB | None:
    """Look up a user by email. Returns None if not found."""
    result = await db.execute(select(UserDB).where(UserDB.email == email))
    return result.scalar_one_or_none()
