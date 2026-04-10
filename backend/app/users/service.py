from uuid import UUID

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.exceptions import AlreadyExistsError, NotFoundError
from app.users.models import UserDB, WorkspaceRole
from app.users.repository import UserRepository
from app.users.schemas import UserCreate, UserPatch, UserRolePatch


class UserService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.repository = UserRepository(db)

    async def create_user(self, data: UserCreate) -> UserDB:
        if data.email:
            existing = await self.repository.get_by_email(data.email)
            if existing:
                raise AlreadyExistsError("Email already registered")
        user = await self.repository.create(data)
        await self.db.commit()
        return user

    async def get_user(self, user_id: UUID) -> UserDB:
        user = await self.repository.get(user_id)
        if not user:
            raise NotFoundError("User not found")
        return user

    async def get_user_by_email(self, email: str) -> UserDB:
        user = await self.repository.get_by_email(email)
        if not user:
            raise NotFoundError("User not found")
        return user

    async def list_users(self, role: WorkspaceRole | None = None) -> list[UserDB]:
        return await self.repository.list(role=role)

    async def update_user(self, user_id: UUID, data: UserPatch) -> UserDB:
        user = await self.repository.get(user_id)
        if not user:
            raise NotFoundError("User not found")
        update_data = data.model_dump(exclude_unset=True)
        if "email" in update_data and update_data["email"] != user.email:
            existing = await self.repository.get_by_email(update_data["email"])
            if existing:
                raise AlreadyExistsError("Email already registered")
        result = await self.repository.update(user, data)
        await self.db.commit()
        return result

    async def update_user_role(self, user_id: UUID, data: UserRolePatch) -> UserDB:
        user = await self.repository.get(user_id)
        if not user:
            raise NotFoundError("User not found")
        result = await self.repository.update(user, data)
        await self.db.commit()
        return result

    async def delete_user(self, user_id: UUID) -> None:
        user = await self.repository.get(user_id)
        if not user:
            raise NotFoundError("User not found")
        await self.repository.delete(user)
        await self.db.commit()


def get_user_service(db: AsyncSession = Depends(get_db)) -> UserService:
    return UserService(db)


# Standalone helper for backward compatibility (Slack integration, auth)
async def get_user_by_email(email: str, db: AsyncSession) -> UserDB | None:
    """Look up a user by email. Returns None if not found."""
    return await UserRepository(db).get_by_email(email)
