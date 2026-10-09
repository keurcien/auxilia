from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.observability.models import WorkspaceObservabilityDB
from app.repository import BaseRepository
from app.utils.encryption import decrypt_value, encrypt_value


class WorkspaceObservabilityRepository(BaseRepository[WorkspaceObservabilityDB]):
    def __init__(self, db: AsyncSession):
        super().__init__(WorkspaceObservabilityDB, db)

    async def get_settings(
        self, workspace_id: UUID | None = None
    ) -> WorkspaceObservabilityDB | None:
        stmt = select(WorkspaceObservabilityDB).where(
            WorkspaceObservabilityDB.key == "default"
        )
        if workspace_id is not None:
            stmt = stmt.where(WorkspaceObservabilityDB.workspace_id == workspace_id)
        else:
            stmt = stmt.limit(1)
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_credentials(
        self, workspace_id: UUID | None = None
    ) -> tuple[str, str] | None:
        row = await self.get_settings(workspace_id)
        if (
            row is None
            or not row.enabled
            or not row.public_key_encrypted
            or not row.secret_key_encrypted
        ):
            return None
        return (
            decrypt_value(row.public_key_encrypted),
            decrypt_value(row.secret_key_encrypted),
        )

    async def _get_or_create(self, workspace_id: UUID) -> WorkspaceObservabilityDB:
        row = await self.get_settings(workspace_id)
        if row is not None:
            return row
        try:
            async with self.db.begin_nested():
                row = WorkspaceObservabilityDB(workspace_id=workspace_id)
                self.db.add(row)
                await self.db.flush()
        except IntegrityError:
            row = await self.get_settings(workspace_id)
            if row is None:
                raise
        return row

    async def save(
        self,
        *,
        workspace_id: UUID,
        enabled: bool,
        base_url: str,
        timeout_seconds: int,
        public_key: str | None,
        secret_key: str | None,
    ) -> WorkspaceObservabilityDB:
        row = await self._get_or_create(workspace_id)
        row.enabled = enabled
        row.base_url = base_url
        row.timeout_seconds = timeout_seconds
        if public_key is not None:
            row.public_key_encrypted = encrypt_value(public_key)
        if secret_key is not None:
            row.secret_key_encrypted = encrypt_value(secret_key)
        self.db.add(row)
        await self.db.flush()
        await self.db.refresh(row)
        return row

    async def clear(self, workspace_id: UUID) -> None:
        row = await self.get_settings(workspace_id)
        if row is not None:
            await self.db.delete(row)
        await self.db.flush()
