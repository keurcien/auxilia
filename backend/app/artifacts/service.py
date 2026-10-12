import asyncio
import hashlib
import logging
import shlex
from pathlib import PurePosixPath
from uuid import NAMESPACE_URL, UUID, uuid5

from deepagents.backends.sandbox import BaseSandbox
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.artifacts.files import (
    SandboxFileMissingError,
    SandboxReadError,
    detect_mime,
    read_bytes,
)
from app.artifacts.models import ArtifactDB
from app.artifacts.repository import ArtifactRepository
from app.artifacts.schemas import ArtifactResponse, PresentFile
from app.artifacts.settings import artifact_settings
from app.artifacts.storage import (
    ObjectMissingError,
    ObjectTooLargeError,
    build_store,
)
from app.database import get_db
from app.exceptions import DomainValidationError, NotFoundError
from app.sandbox.provider import SandboxGoneError, build_provider
from app.sandbox.repository import SandboxRepository
from app.service import BaseService


logger = logging.getLogger(__name__)


def describe(row: ArtifactDB) -> ArtifactResponse:
    return ArtifactResponse(
        id=row.id,
        thread_id=row.thread_id,
        tool_call_id=row.tool_call_id,
        title=row.title,
        filename=row.filename,
        mime_type=row.mime_type,
        size=row.size,
        temporary=row.storage_kind == "sandbox",
        created_at=row.created_at,
    )


class ArtifactGoneError(NotFoundError):
    def body(self):
        return {"error": "artifact_gone", "detail": str(self)}


# Inside the execution sandbox (not the Auxilia host).
SNAPSHOT_ROOT = "/tmp/.auxilia-artifacts"  # nosec B108


class ArtifactService(BaseService[ArtifactDB, ArtifactRepository]):
    not_found_message = "Artifact not found"

    def __init__(self, db: AsyncSession):
        super().__init__(db, ArtifactRepository(db))
        # Objects this service put in the bucket, so an aborted batch can remove them.
        self.uploaded: list[str] = []

    async def list(
        self, thread_id: str, after: UUID | None = None
    ) -> list[ArtifactResponse]:
        return [
            describe(row)
            for row in await self.repository.list_for_thread(thread_id, after)
        ]

    async def publish(
        self,
        *,
        thread_id: str,
        tool_call_id: str,
        file: PresentFile,
        backend: BaseSandbox,
        sandbox_source_id: UUID,
    ) -> ArtifactResponse:
        existing = await self.repository.published(thread_id, tool_call_id, file.path)
        if existing:
            return describe(existing)
        cfg = artifact_settings
        try:
            data = await asyncio.to_thread(
                read_bytes, backend, file.path, cfg.allowed_roots, cfg.max_bytes
            )
        except SandboxFileMissingError as exc:
            raise DomainValidationError(
                "The file does not exist in the sandbox"
            ) from exc
        except SandboxReadError as exc:
            raise DomainValidationError(
                "The sandbox could not be reached to read the file"
            ) from exc
        filename = PurePosixPath(file.path).name
        # Zip parsing / UTF-8 decoding of up to max_bytes: keep it off the loop.
        mime_type = await asyncio.to_thread(detect_mime, filename, data)
        # Stable across tool replay. New tool calls publish new immutable versions.
        artifact_id = uuid5(
            NAMESPACE_URL, f"auxilia:{thread_id}:{tool_call_id}:{file.path}"
        )
        digest = hashlib.sha256(data).hexdigest()
        key = f"{cfg.prefix.strip('/')}/threads/{uuid5(NAMESPACE_URL, thread_id)}/{artifact_id}/{digest}/{filename}"
        kind = cfg.provider or "sandbox"
        if kind != "sandbox":
            store = await asyncio.to_thread(build_store, cfg)
            await asyncio.to_thread(store.put, key, data, mime_type)
            self.uploaded.append(key)
        else:
            key = f"{SNAPSHOT_ROOT}/{artifact_id}/{digest}"
            directory = str(PurePosixPath(key).parent)
            mkdir = await asyncio.to_thread(
                backend.execute, f"mkdir -p -- {shlex.quote(directory)}", timeout=10
            )
            if mkdir.exit_code != 0:
                raise DomainValidationError(
                    "Could not create artifact snapshot directory"
                )
            result = await asyncio.to_thread(backend.upload_files, [(key, data)])
            if not result or result[0].error:
                raise DomainValidationError("Could not snapshot the temporary artifact")
        row = ArtifactDB(
            id=artifact_id,
            thread_id=thread_id,
            tool_call_id=tool_call_id,
            source_path=file.path,
            title=file.title or filename,
            filename=filename,
            mime_type=mime_type,
            size=len(data),
            sha256=digest,
            storage_kind=kind,
            storage_key=key,
            storage_bucket=cfg.bucket_name or None,
            storage_endpoint=cfg.endpoint,
            sandbox_source_id=sandbox_source_id,
            sandbox_id=backend.id,
        )
        row = await self.repository.insert(row)
        return describe(row)

    async def discard_uploads(self) -> None:
        """Best-effort delete of this batch's bucket objects after a rollback."""
        if not self.uploaded:
            return
        store = await asyncio.to_thread(build_store, artifact_settings)
        for key in self.uploaded:
            try:
                await asyncio.to_thread(store.delete, key)
            except Exception:  # noqa: BLE001 — cleanup must not mask the publish failure
                logger.warning(
                    "Could not delete orphaned artifact object %s", key, exc_info=True
                )
        self.uploaded.clear()

    async def content(
        self, thread_id: str, artifact_id: UUID
    ) -> tuple[ArtifactDB, bytes]:
        row = await self.repository.in_thread(thread_id, artifact_id)
        if row is None:
            raise NotFoundError(self.not_found_message)
        cfg = artifact_settings
        if row.storage_kind != "sandbox":
            if (row.storage_kind, row.storage_bucket, row.storage_endpoint) != (
                cfg.provider,
                cfg.bucket_name,
                cfg.endpoint,
            ):
                raise DomainValidationError(
                    "This artifact's storage configuration is no longer available"
                )
            store = await asyncio.to_thread(build_store, cfg)
            try:
                data = await asyncio.to_thread(
                    store.get, row.storage_key, cfg.max_bytes
                )
            except ObjectMissingError as exc:
                raise ArtifactGoneError(
                    "This saved file has been removed from storage."
                ) from exc
            except ObjectTooLargeError as exc:
                raise ArtifactGoneError(
                    "This saved file exceeds the current download size limit."
                ) from exc
        else:
            source = (
                await SandboxRepository(self.db).get(row.sandbox_source_id)
                if row.sandbox_source_id
                else None
            )
            if source is None or row.sandbox_id is None:
                raise ArtifactGoneError(
                    "This temporary file's execution environment is no longer available."
                )
            provider = build_provider(source)
            try:
                # Never open_sandbox: reads must not create a replacement environment.
                backend = await asyncio.to_thread(provider.connect, row.sandbox_id)
            except SandboxGoneError as exc:
                raise ArtifactGoneError(
                    "This temporary file expired with its execution environment."
                ) from exc
            try:
                data = await asyncio.to_thread(
                    read_bytes,
                    backend,
                    row.storage_key,
                    [SNAPSHOT_ROOT],
                    cfg.max_bytes,
                )
            except SandboxFileMissingError as exc:
                raise ArtifactGoneError(
                    "This temporary artifact has been removed from its execution environment."
                ) from exc
            except SandboxReadError as exc:
                raise ArtifactGoneError(
                    "This temporary file's execution environment is not reachable."
                ) from exc
        if hashlib.sha256(data).hexdigest() != row.sha256:
            raise ArtifactGoneError(
                "This artifact's original bytes are no longer available."
            )
        return row, data


def get_artifact_service(db: AsyncSession = Depends(get_db)) -> ArtifactService:
    return ArtifactService(db)
