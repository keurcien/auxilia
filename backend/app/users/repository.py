from uuid import UUID

from sqlalchemy import delete, func, or_, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.pagination import PageParams
from app.repository import BaseRepository
from app.users.models import UserDB, UserImageDB, UserTwoFactorDB, WorkspaceRole
from app.workspaces.models import WorkspaceMembershipDB


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


class UserRepository(BaseRepository[UserDB]):
    def __init__(self, db: AsyncSession):
        super().__init__(UserDB, db)

    async def list_by_ids(self, user_ids: list[UUID]) -> list[UserDB]:
        if not user_ids:
            return []
        stmt = select(UserDB).where(UserDB.id.in_(user_ids))
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def get_by_email(self, email: str) -> UserDB | None:
        stmt = select(UserDB).where(UserDB.email == email)
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_for_update(self, user_id: UUID) -> UserDB | None:
        stmt = select(UserDB).where(UserDB.id == user_id).with_for_update()
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_in_workspace(
        self, user_id: UUID, workspace_id: UUID
    ) -> tuple[UserDB, WorkspaceMembershipDB] | None:
        stmt = (
            select(UserDB, WorkspaceMembershipDB)
            .join(
                WorkspaceMembershipDB,
                WorkspaceMembershipDB.user_id == UserDB.id,
            )
            .where(
                UserDB.id == user_id,
                WorkspaceMembershipDB.workspace_id == workspace_id,
            )
        )
        result = await self.db.execute(stmt)
        return result.one_or_none()

    async def get_image(self, user_id: UUID) -> UserImageDB | None:
        stmt = select(UserImageDB).where(UserImageDB.user_id == user_id)
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def set_image(
        self,
        user_id: UUID,
        *,
        data: bytes,
        media_type: str,
        sha256: str,
        revision: UUID,
    ) -> None:
        await self.get_for_update(user_id)
        image = await self.get_image(user_id)
        if image is None:
            image = UserImageDB(
                user_id=user_id,
                data=data,
                media_type=media_type,
                sha256=sha256,
            )
        else:
            image.data = data
            image.media_type = media_type
            image.sha256 = sha256
        self.db.add(image)
        stmt = (
            update(UserDB).where(UserDB.id == user_id).values(image_revision=revision)
        )
        await self.db.execute(stmt)
        await self.db.flush()

    async def delete_image(self, user_id: UUID) -> None:
        await self.get_for_update(user_id)
        stmt = delete(UserImageDB).where(UserImageDB.user_id == user_id)
        await self.db.execute(stmt)
        stmt = update(UserDB).where(UserDB.id == user_id).values(image_revision=None)
        await self.db.execute(stmt)
        await self.db.flush()

    async def get_two_factor(
        self, user_id: UUID, *, for_update: bool = False
    ) -> UserTwoFactorDB | None:
        stmt = select(UserTwoFactorDB).where(UserTwoFactorDB.user_id == user_id)
        if for_update:
            stmt = stmt.with_for_update()
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def set_two_factor(
        self,
        user_id: UUID,
        *,
        secret_encrypted: str,
        backup_code_hashes: list[str],
        last_used_totp_counter: int,
    ) -> None:
        existing = await self.get_two_factor(user_id)
        if existing is None:
            existing = UserTwoFactorDB(
                user_id=user_id,
                secret_encrypted=secret_encrypted,
                backup_code_hashes=backup_code_hashes,
                last_used_totp_counter=last_used_totp_counter,
            )
        else:
            existing.secret_encrypted = secret_encrypted
            existing.backup_code_hashes = backup_code_hashes
            existing.last_used_totp_counter = last_used_totp_counter
        self.db.add(existing)
        stmt = (
            update(UserDB).where(UserDB.id == user_id).values(two_factor_enabled=True)
        )
        await self.db.execute(stmt)
        await self.db.flush()

    async def disable_two_factor(self, user_id: UUID) -> None:
        stmt = delete(UserTwoFactorDB).where(UserTwoFactorDB.user_id == user_id)
        await self.db.execute(stmt)
        stmt = (
            update(UserDB).where(UserDB.id == user_id).values(two_factor_enabled=False)
        )
        await self.db.execute(stmt)
        await self.db.flush()

    async def set_backup_code_hashes(
        self, two_factor: UserTwoFactorDB, hashes: list[str]
    ) -> None:
        two_factor.backup_code_hashes = hashes
        self.db.add(two_factor)
        await self.db.flush()

    async def list(
        self,
        workspace_id: UUID,
        page: PageParams,
        role: WorkspaceRole | None = None,
        search: str | None = None,
        team_id: UUID | None = None,
    ) -> tuple[list[tuple[UserDB, WorkspaceMembershipDB]], int]:
        stmt = (
            select(UserDB, WorkspaceMembershipDB)
            .join(
                WorkspaceMembershipDB,
                WorkspaceMembershipDB.user_id == UserDB.id,
            )
            .where(WorkspaceMembershipDB.workspace_id == workspace_id)
            .order_by(UserDB.created_at.desc(), UserDB.id)
        )
        if role is not None:
            stmt = stmt.where(WorkspaceMembershipDB.role == role)
        if team_id is not None:
            stmt = stmt.where(WorkspaceMembershipDB.team_id == team_id)
        if search:
            pattern = f"%{_escape_like(search)}%"
            stmt = stmt.where(
                or_(
                    UserDB.name.ilike(pattern, escape="\\"),
                    UserDB.email.ilike(pattern, escape="\\"),
                )
            )
        result, total = await self.paginate(stmt, page)
        return list(result.all()), total

    async def count_by_role(self, workspace_id: UUID) -> dict[WorkspaceRole, int]:
        stmt = (
            select(WorkspaceMembershipDB.role, func.count())
            .where(WorkspaceMembershipDB.workspace_id == workspace_id)
            .group_by(WorkspaceMembershipDB.role)
        )
        result = await self.db.execute(stmt)
        return dict(result.all())
