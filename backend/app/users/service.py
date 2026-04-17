from uuid import UUID

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.exceptions import AlreadyExistsError, NotFoundError
from app.service import BaseService
from app.users.models import UserDB, WorkspaceRole
from app.users.repository import UserRepository
from app.users.schemas import UserCreate, UserPatch, UserRolePatch


class UserService(BaseService[UserDB, UserRepository]):
    not_found_message = "User not found"

    def __init__(self, db: AsyncSession):
        super().__init__(db, UserRepository(db))

    async def _ensure_email_available(self, email: str) -> None:
        if await self.repository.get_by_email(email):
            raise AlreadyExistsError("Email already registered")

    async def create_user(self, data: UserCreate) -> UserDB:
        if data.email:
            await self._ensure_email_available(data.email)
        return await self.repository.create(data)

    async def get_user(self, user_id: UUID) -> UserDB:
        return await self.get_or_404(user_id)

    async def get_user_by_email(self, email: str) -> UserDB:
        user = await self.repository.get_by_email(email)
        if not user:
            raise NotFoundError(self.not_found_message)
        return user

    async def list_users(self, role: WorkspaceRole | None = None) -> list[UserDB]:
        return await self.repository.list(role=role)

    async def update_user(self, user_id: UUID, data: UserPatch) -> UserDB:
        user = await self.get_or_404(user_id)
        update_data = data.model_dump(exclude_unset=True)
        new_email = update_data.get("email")
        if new_email and new_email != user.email:
            await self._ensure_email_available(new_email)
        return await self.repository.update(user, data)

    async def update_user_role(self, user_id: UUID, data: UserRolePatch) -> UserDB:
        user = await self.get_or_404(user_id)
        return await self.repository.update(user, data)

    async def delete_user(self, user_id: UUID) -> None:
        user = await self.get_or_404(user_id)
        await self.repository.delete(user)


def get_user_service(db: AsyncSession = Depends(get_db)) -> UserService:
    return UserService(db)
