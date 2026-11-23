from typing import Any
from uuid import UUID

from sqlalchemy import delete, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.model_providers.models import (
    ModelDB,
    ModelProviderCatalogEntryDB,
    ModelProviderCredentialDB,
)
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

    async def get_quick(self, *, for_update: bool = False) -> ModelDB | None:
        stmt = select(ModelDB).where(ModelDB.is_quick)
        if self.workspace_id is not None:
            stmt = stmt.where(ModelDB.workspace_id == self.workspace_id)
        if for_update:
            stmt = stmt.with_for_update()
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def delete_by_provider(self, provider: str) -> None:
        if self.workspace_id is None:
            raise RuntimeError("workspace_id is required to delete provider models")
        stmt = delete(ModelDB).where(
            ModelDB.workspace_id == self.workspace_id,  # type: ignore[arg-type]
            ModelDB.provider == provider,  # type: ignore[arg-type]
        )
        await self.db.execute(stmt)
        await self.db.flush()


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
            if row.api_key_encrypted
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
        return (
            decrypt_value(row.api_key_encrypted)
            if row and row.api_key_encrypted
            else None
        )

    async def get_base_url(self, provider: str) -> str | None:
        stmt = select(ModelProviderCredentialDB.base_url).where(
            ModelProviderCredentialDB.provider == provider
        )
        if self.workspace_id is not None:
            stmt = stmt.where(
                ModelProviderCredentialDB.workspace_id == self.workspace_id
            )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def list_base_urls(self) -> dict[str, str]:
        stmt = select(ModelProviderCredentialDB)
        if self.workspace_id is not None:
            stmt = stmt.where(
                ModelProviderCredentialDB.workspace_id == self.workspace_id
            )
        result = await self.db.execute(stmt)
        return {
            row.provider: row.base_url for row in result.scalars().all() if row.base_url
        }

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
        stmt = (
            update(ModelProviderCredentialDB)
            .where(
                ModelProviderCredentialDB.provider == provider,  # type: ignore[arg-type]
            )
            .values(api_key_encrypted=None)
        )
        if self.workspace_id is not None:
            stmt = stmt.where(
                ModelProviderCredentialDB.workspace_id == self.workspace_id  # type: ignore[arg-type]
            )
        await self.db.execute(stmt)
        await self.db.flush()

    async def set_base_url(self, provider: str, base_url: str) -> None:
        if self.workspace_id is None:
            raise RuntimeError("workspace_id is required to store provider settings")
        update_stmt = (
            update(ModelProviderCredentialDB)
            .where(
                ModelProviderCredentialDB.workspace_id == self.workspace_id,  # type: ignore[arg-type]
                ModelProviderCredentialDB.provider == provider,  # type: ignore[arg-type]
            )
            .values(base_url=base_url)
        )
        result = await self.db.execute(update_stmt)
        if result.rowcount == 0:  # type: ignore[attr-defined]
            try:
                async with self.db.begin_nested():
                    self.db.add(
                        ModelProviderCredentialDB(
                            workspace_id=self.workspace_id,
                            provider=provider,
                            base_url=base_url,
                        )
                    )
                    await self.db.flush()
            except IntegrityError:
                await self.db.execute(update_stmt)
        await self.db.flush()

    async def delete_provider_config(self, provider: str) -> None:
        stmt = delete(ModelProviderCredentialDB).where(
            ModelProviderCredentialDB.provider == provider,  # type: ignore[arg-type]
        )
        if self.workspace_id is not None:
            stmt = stmt.where(
                ModelProviderCredentialDB.workspace_id == self.workspace_id  # type: ignore[arg-type]
            )
        await self.db.execute(stmt)
        await self.db.flush()


class ModelProviderCatalogRepository:
    def __init__(self, db: AsyncSession, workspace_id: UUID | None = None):
        self.db = db
        self.workspace_id = workspace_id

    async def list_all(
        self, provider: str | None = None
    ) -> list[ModelProviderCatalogEntryDB]:
        stmt = select(ModelProviderCatalogEntryDB)
        if self.workspace_id is not None:
            stmt = stmt.where(
                ModelProviderCatalogEntryDB.workspace_id == self.workspace_id
            )
        if provider is not None:
            stmt = stmt.where(ModelProviderCatalogEntryDB.provider == provider)
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def mark_all_unavailable(self, provider: str) -> None:
        if self.workspace_id is None:
            raise RuntimeError("workspace_id is required to update provider models")
        stmt = (
            update(ModelProviderCatalogEntryDB)
            .where(
                ModelProviderCatalogEntryDB.workspace_id == self.workspace_id,  # type: ignore[arg-type]
                ModelProviderCatalogEntryDB.provider == provider,  # type: ignore[arg-type]
            )
            .values(is_available=False)
        )
        await self.db.execute(stmt)

    async def delete_by_provider(self, provider: str) -> None:
        if self.workspace_id is None:
            raise RuntimeError("workspace_id is required to delete provider models")
        stmt = delete(ModelProviderCatalogEntryDB).where(
            ModelProviderCatalogEntryDB.workspace_id == self.workspace_id,  # type: ignore[arg-type]
            ModelProviderCatalogEntryDB.provider == provider,  # type: ignore[arg-type]
        )
        await self.db.execute(stmt)
        await self.db.flush()

    async def upsert(
        self,
        *,
        provider: str,
        model_id: str,
        runtime_model_id: str,
        display_name: str,
        chef: str,
        chef_slug: str,
        multimodal: bool,
        supports_structured_output: bool,
        supports_tools: bool,
    ) -> None:
        if self.workspace_id is None:
            raise RuntimeError("workspace_id is required to update provider models")
        values: dict[str, Any] = {
            "runtime_model_id": runtime_model_id,
            "display_name": display_name,
            "chef": chef,
            "chef_slug": chef_slug,
            "multimodal": multimodal,
            "supports_structured_output": supports_structured_output,
            "supports_tools": supports_tools,
            "is_available": True,
        }
        update_stmt = (
            update(ModelProviderCatalogEntryDB)
            .where(
                ModelProviderCatalogEntryDB.workspace_id == self.workspace_id,  # type: ignore[arg-type]
                ModelProviderCatalogEntryDB.provider == provider,  # type: ignore[arg-type]
                ModelProviderCatalogEntryDB.model_id == model_id,  # type: ignore[arg-type]
            )
            .values(**values)
        )
        result = await self.db.execute(update_stmt)
        if result.rowcount == 0:  # type: ignore[attr-defined]
            try:
                async with self.db.begin_nested():
                    self.db.add(
                        ModelProviderCatalogEntryDB(
                            workspace_id=self.workspace_id,
                            provider=provider,
                            model_id=model_id,
                            **values,
                        )
                    )
                    await self.db.flush()
            except IntegrityError:
                await self.db.execute(update_stmt)
        await self.db.flush()
