from uuid import UUID

from sqlalchemy import delete, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.model_providers.models import ModelDB, ModelProviderCredentialDB
from app.repository import BaseRepository
from app.utils.encryption import decrypt_value, encrypt_value


class ModelRepository(BaseRepository[ModelDB]):
    def __init__(self, db: AsyncSession, workspace_id: UUID | None = None):
        super().__init__(ModelDB, db)
        self.workspace_id = workspace_id

    async def list_all(self) -> list[ModelDB]:
        stmt = select(ModelDB)
        if self.workspace_id is not None:
            stmt = stmt.where(ModelDB.workspace_id == self.workspace_id)
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def get_by_provider_and_model_id(
        self, provider: str, model_id: str, *, for_update: bool = False
    ) -> ModelDB | None:
        stmt = select(ModelDB).where(
            ModelDB.provider == provider,
            ModelDB.model_id == model_id,
        )
        if self.workspace_id is not None:
            stmt = stmt.where(ModelDB.workspace_id == self.workspace_id)
        if for_update:
            stmt = stmt.with_for_update()
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_default(self, *, for_update: bool = False) -> ModelDB | None:
        stmt = select(ModelDB).where(ModelDB.is_default)
        if self.workspace_id is not None:
            stmt = stmt.where(ModelDB.workspace_id == self.workspace_id)
        if for_update:
            stmt = stmt.with_for_update()
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()


class ModelProviderCredentialRepository:
    def __init__(self, db: AsyncSession, workspace_id: UUID | None = None):
        self.db = db
        self.workspace_id = workspace_id

    async def list_api_keys(self) -> dict[str, str]:
        stmt = select(ModelProviderCredentialDB)
        if self.workspace_id is not None:
            stmt = stmt.where(
                ModelProviderCredentialDB.workspace_id == self.workspace_id
            )
        result = await self.db.execute(stmt)
        return {
            row.provider: decrypt_value(row.api_key_encrypted)
            for row in result.scalars().all()
        }

    async def get_api_key(self, provider: str) -> str | None:
        stmt = select(ModelProviderCredentialDB).where(
            ModelProviderCredentialDB.provider == provider
        )
        if self.workspace_id is not None:
            stmt = stmt.where(
                ModelProviderCredentialDB.workspace_id == self.workspace_id
            )
        result = await self.db.execute(stmt)
        row = result.scalar_one_or_none()
        return decrypt_value(row.api_key_encrypted) if row else None

    async def set_api_key(self, provider: str, api_key: str) -> None:
        if self.workspace_id is None:
            raise RuntimeError("workspace_id is required to store credentials")
        encrypted = encrypt_value(api_key)
        update_stmt = (
            update(ModelProviderCredentialDB)
            .where(
                ModelProviderCredentialDB.workspace_id == self.workspace_id,  # type: ignore[arg-type]
                ModelProviderCredentialDB.provider == provider,  # type: ignore[arg-type]
            )
            .values(api_key_encrypted=encrypted)
        )
        result = await self.db.execute(update_stmt)
        if result.rowcount == 0:  # type: ignore[attr-defined]
            try:
                async with self.db.begin_nested():
                    self.db.add(
                        ModelProviderCredentialDB(
                            workspace_id=self.workspace_id,
                            provider=provider,
                            api_key_encrypted=encrypted,
                        )
                    )
                    await self.db.flush()
            except IntegrityError:
                await self.db.execute(update_stmt)
        await self.db.flush()

    async def delete_api_key(self, provider: str) -> None:
        stmt = delete(ModelProviderCredentialDB).where(
            ModelProviderCredentialDB.provider == provider,  # type: ignore[arg-type]
        )
        if self.workspace_id is not None:
            stmt = stmt.where(
                ModelProviderCredentialDB.workspace_id == self.workspace_id  # type: ignore[arg-type]
            )
        await self.db.execute(stmt)
        await self.db.flush()
