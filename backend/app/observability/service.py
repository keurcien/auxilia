from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
from uuid import UUID

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.exceptions import DomainValidationError
from app.observability.repository import WorkspaceObservabilityRepository
from app.observability.schemas import (
    WorkspaceObservabilityResponse,
    WorkspaceObservabilityUpdate,
)


@dataclass(frozen=True)
class ObservabilityRuntimeConfig:
    base_url: str
    public_key: str
    secret_key: str
    timeout_seconds: int
    revision: datetime

    @property
    def fingerprint(self) -> str:
        raw = (
            f"{self.base_url}\0{self.public_key}\0{self.secret_key}\0"
            f"{self.timeout_seconds}\0{self.revision.isoformat()}"
        )
        return sha256(raw.encode()).hexdigest()


class WorkspaceObservabilityService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.repository = WorkspaceObservabilityRepository(db)

    async def get_runtime_config(
        self, workspace_id: UUID
    ) -> ObservabilityRuntimeConfig | None:
        row = await self.repository.get_settings(workspace_id)
        credentials = await self.repository.get_credentials(workspace_id)
        if row is None or credentials is None:
            return None
        return ObservabilityRuntimeConfig(
            base_url=row.base_url,
            public_key=credentials[0],
            secret_key=credentials[1],
            timeout_seconds=row.timeout_seconds,
            revision=row.updated_at,
        )

    async def get_response(self, workspace_id: UUID) -> WorkspaceObservabilityResponse:
        row = await self.repository.get_settings(workspace_id)
        credentials = await self.repository.get_credentials(workspace_id)
        public_key = credentials[0] if credentials else None
        return WorkspaceObservabilityResponse(
            enabled=bool(row and row.enabled),
            is_configured=credentials is not None,
            base_url=row.base_url if row else "https://cloud.langfuse.com",
            timeout_seconds=row.timeout_seconds if row else 15,
            public_key_last4=public_key[-4:] if public_key else None,
            public_key_length=len(public_key) if public_key else None,
            has_secret_key=credentials is not None,
        )

    async def update(
        self, workspace_id: UUID, data: WorkspaceObservabilityUpdate
    ) -> WorkspaceObservabilityResponse:
        existing = await self.repository.get_settings(workspace_id)
        has_existing_pair = bool(
            existing and existing.public_key_encrypted and existing.secret_key_encrypted
        )
        public_key = data.public_key.strip() if data.public_key is not None else None
        secret_key = data.secret_key.strip() if data.secret_key is not None else None
        if (public_key is None) != (secret_key is None):
            raise DomainValidationError(
                "Langfuse public key and secret key must be updated together"
            )
        if public_key is not None and not public_key:
            raise DomainValidationError("Langfuse credentials cannot be empty")
        if secret_key is not None and not secret_key:
            raise DomainValidationError("Langfuse credentials cannot be empty")
        if data.enabled and not has_existing_pair and public_key is None:
            raise DomainValidationError("Langfuse credentials are required")
        await self.repository.save(
            workspace_id=workspace_id,
            enabled=data.enabled,
            base_url=str(data.base_url).rstrip("/"),
            timeout_seconds=data.timeout_seconds,
            public_key=public_key,
            secret_key=secret_key,
        )
        return await self.get_response(workspace_id)

    async def clear(self, workspace_id: UUID) -> WorkspaceObservabilityResponse:
        await self.repository.clear(workspace_id)
        return await self.get_response(workspace_id)


def get_workspace_observability_service(
    db: AsyncSession = Depends(get_db),
) -> WorkspaceObservabilityService:
    return WorkspaceObservabilityService(db)
