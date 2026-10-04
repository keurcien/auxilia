from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.auth.models import WorkspaceAuthenticationDB
from app.repository import BaseRepository
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
            or not row.enabled
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
        client_id: str | None,
        client_secret: str | None,
    ) -> WorkspaceAuthenticationDB:
        row = await self.get_settings(workspace_id)
        if row is None:
            row = WorkspaceAuthenticationDB(workspace_id=workspace_id)
        row.enabled = enabled
        row.google_exclusive = google_exclusive
        if client_id is not None:
            row.google_client_id_encrypted = encrypt_value(client_id)
        if client_secret is not None:
            row.google_client_secret_encrypted = encrypt_value(client_secret)
        self.db.add(row)
        await self.db.flush()
        await self.db.refresh(row)
        return row

    async def clear(self, workspace_id: UUID) -> None:
        row = await self.get_settings(workspace_id)
        if row is not None:
            await self.db.delete(row)
        await self.db.flush()
