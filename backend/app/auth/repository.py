from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import delete, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col, select

from app.auth.models import PasswordResetTokenDB, WorkspaceAuthenticationDB
from app.repository import BaseRepository
from app.users.models import UserDB
from app.utils.encryption import decrypt_value, encrypt_value


class WorkspaceAuthenticationRepository(BaseRepository[WorkspaceAuthenticationDB]):
    def __init__(self, db: AsyncSession):
        super().__init__(WorkspaceAuthenticationDB, db)

    async def get_settings(
        self, workspace_id: UUID
    ) -> WorkspaceAuthenticationDB | None:
        stmt = select(WorkspaceAuthenticationDB).where(
            WorkspaceAuthenticationDB.workspace_id == workspace_id,
            WorkspaceAuthenticationDB.key == "default",
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_credentials(self, workspace_id: UUID) -> tuple[str, str] | None:
        row = await self.get_settings(workspace_id)
        if (
            row is None
            or not row.google_client_id_encrypted
            or not row.google_client_secret_encrypted
        ):
            return None
        return (
            decrypt_value(row.google_client_id_encrypted),
            decrypt_value(row.google_client_secret_encrypted),
        )

    async def save(
        self,
        *,
        workspace_id: UUID,
        enabled: bool,
        google_exclusive: bool,
        enforce_two_factor: bool,
        client_id: str | None,
        client_secret: str | None,
    ) -> WorkspaceAuthenticationDB:
        row = await self.get_settings(workspace_id)
        if row is None:
            row = WorkspaceAuthenticationDB(workspace_id=workspace_id)
        row.enabled = enabled
        row.google_exclusive = google_exclusive
        row.enforce_two_factor = enforce_two_factor
        if client_id is not None:
            row.google_client_id_encrypted = encrypt_value(client_id)
        if client_secret is not None:
            row.google_client_secret_encrypted = encrypt_value(client_secret)
        self.db.add(row)
        await self.db.flush()
        await self.db.refresh(row)
        return row

    async def clear_google_credentials(self, workspace_id: UUID) -> None:
        row = await self.get_settings(workspace_id)
        if row is None:
            return
        if row.enforce_two_factor:
            row.enabled = False
            row.google_exclusive = False
            row.google_client_id_encrypted = None
            row.google_client_secret_encrypted = None
            self.db.add(row)
        else:
            await self.db.delete(row)
        await self.db.flush()


class PasswordResetTokenRepository(BaseRepository[PasswordResetTokenDB]):
    def __init__(self, db: AsyncSession):
        super().__init__(PasswordResetTokenDB, db)

    async def get_user_by_email(self, email: str) -> UserDB | None:
        stmt = (
            select(UserDB)
            .where(func.lower(UserDB.email) == email.lower())
            .with_for_update()
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_user(self, user_id: UUID) -> UserDB | None:
        stmt = select(UserDB).where(UserDB.id == user_id)
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def replace_for_user(
        self, token: PasswordResetTokenDB
    ) -> PasswordResetTokenDB:
        await self.delete_for_user(token.user_id)
        return await self.create(token)

    async def has_recent_for_user(self, user_id: UUID, since: datetime) -> bool:
        stmt = (
            select(PasswordResetTokenDB)
            .where(
                col(PasswordResetTokenDB.user_id) == user_id,
                col(PasswordResetTokenDB.created_at) >= since,
            )
            .limit(1)
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none() is not None

    async def get_valid_for_update(
        self, token_hash: str
    ) -> PasswordResetTokenDB | None:
        stmt = (
            select(PasswordResetTokenDB)
            .where(
                PasswordResetTokenDB.token_hash == token_hash,
                PasswordResetTokenDB.expires_at > datetime.now(UTC),
            )
            .with_for_update()
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def delete_for_user(self, user_id: UUID) -> None:
        stmt = delete(PasswordResetTokenDB).where(
            col(PasswordResetTokenDB.user_id) == user_id
        )
        await self.db.execute(stmt)
        await self.db.flush()
