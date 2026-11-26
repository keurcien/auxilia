import asyncio
import builtins
import hashlib
import logging
import mimetypes
import re
import shlex
from pathlib import PurePosixPath
from uuid import NAMESPACE_URL, UUID, uuid5

import httpx
from deepagents.backends.sandbox import BaseSandbox
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.artifacts.files import (
    PPTX_MIME,
    SandboxFileMissingError,
    SandboxReadError,
    detect_mime,
    is_text_mime,
    read_bytes,
)
from app.artifacts.google_slides import find_export, slides_url, upload_as_slides
from app.artifacts.models import GALLERY_ORIGIN, ArtifactDB
from app.artifacts.repository import ArtifactRepository
from app.artifacts.schemas import ArtifactResponse, PresentFile
from app.artifacts.settings import artifact_settings
from app.artifacts.storage import (
    ObjectMissingError,
    ObjectTooLargeError,
    build_store,
)
from app.database import get_db
from app.exceptions import (
    DomainError,
    DomainValidationError,
    NotFoundError,
    StaleRevisionError,
)
from app.runtime.runs.repository import RunRepository
from app.sandbox.provider import SandboxGoneError, build_provider
from app.sandbox.repository import SandboxRepository
from app.service import BaseService
from app.threads.repository import ThreadRepository
from app.workspaces.dependencies import get_active_workspace_id


logger = logging.getLogger(__name__)


def describe(row: ArtifactDB) -> ArtifactResponse:
    return ArtifactResponse(
        id=row.id,
        thread_id=row.thread_id,
        origin=row.origin,
        tool_call_id=row.tool_call_id,
        title=row.title,
        filename=row.filename,
        mime_type=row.mime_type,
        size=row.size,
        sha256=row.sha256,
        temporary=row.storage_kind == "sandbox",
        created_at=row.created_at,
    )


class ArtifactGoneError(NotFoundError):
    def body(self):
        return {"error": "artifact_gone", "detail": str(self)}


# Inside the execution sandbox (not the Auxilia host).
SNAPSHOT_ROOT = "/tmp/.auxilia-artifacts"  # nosec B108
# Persistent thread files are restored here inside the execution sandbox.
ATTACHMENTS_ROOT = "/workspace/files"


def attachment_filename(name: str) -> str:
    """Make a browser-supplied name safe as one sandbox path segment."""
    name = PurePosixPath(name.replace("\\", "/")).name
    name = re.sub(r"[\x00-\x1f\x7f]", "_", name).strip()
    # Filesystems limit a path segment in bytes, not Unicode code points.
    # Keep the tail so a filename extension survives truncation.
    name = name.encode("utf-8")[-200:].decode("utf-8", errors="ignore")
    return "file" if name in ("", ".", "..") else name


def free_path(filename: str, taken: set[str]) -> str:
    stem = PurePosixPath(filename).stem
    suffix = PurePosixPath(filename).suffix
    path = f"{ATTACHMENTS_ROOT}/{filename}"
    number = 1
    while path in taken:
        number += 1
        path = f"{ATTACHMENTS_ROOT}/{stem}-{number}{suffix}"
    return path


def attachment_mime(filename: str, data: bytes) -> str:
    """Best-effort MIME detection; arbitrary user files remain attachable."""
    try:
        mime_type = detect_mime(filename, data)
    except DomainValidationError:
        mime_type = "application/octet-stream"
    if mime_type == "application/octet-stream":
        guessed = mimetypes.guess_type(filename)[0]
        if guessed and not is_text_mime(guessed):
            mime_type = guessed
    return mime_type


def missing_on_disk(backend: BaseSandbox, paths: builtins.list[str]) -> set[str]:
    """Create the thread-file folder and return paths absent from the disk."""
    script = f"mkdir -p -- {shlex.quote(ATTACHMENTS_ROOT)} 2>/dev/null || true"
    if paths:
        script += (
            "; for p in "
            + " ".join(shlex.quote(path) for path in paths)
            + '; do [ -f "$p" ] || printf \'%s\\n\' "$p"; done'
        )
    result = backend.execute(script)  # nosemgrep — sandbox shell, paths are quoted
    if result.exit_code != 0:
        raise RuntimeError(f"Could not list thread files: {result.output[:2000]}")
    return set(result.output.splitlines()) & set(paths)


def put_on_disk(backend: BaseSandbox, files: builtins.list[tuple[str, bytes]]) -> None:
    directories = {str(PurePosixPath(path).parent) for path, _ in files}
    created = backend.execute(  # nosemgrep — sandbox shell, paths are quoted
        "mkdir -p -- " + " ".join(shlex.quote(path) for path in sorted(directories))
    )
    if created.exit_code != 0:
        raise RuntimeError(
            f"Could not create thread file directories: {created.output[:2000]}"
        )
    result = backend.upload_files(files)
    failed = [item.path for item in result if item.error]
    if len(result) != len(files) or failed:
        raise RuntimeError(f"Could not place thread files on the sandbox: {failed}")


class ArtifactService(BaseService[ArtifactDB, ArtifactRepository]):
    not_found_message = "Artifact not found"

    def __init__(self, db: AsyncSession, workspace_id: UUID):
        super().__init__(db, ArtifactRepository(db, workspace_id))
        self.workspace_id = workspace_id
        # Objects this service put in the bucket, so an aborted batch can remove them.
        self.uploaded: list[str] = []
        # Objects an update in place superseded, removed once the update commits.
        self.replaced: list[str] = []

    async def list(
        self, thread_id: str, after: UUID | None = None
    ) -> list[ArtifactResponse]:
        return [
            describe(row)
            for row in await self.repository.list_for_thread(thread_id, after)
        ]

    async def attachment_metadata(
        self, thread_id: str, attachment_ids: builtins.list[UUID]
    ) -> builtins.list[dict[str, str]]:
        rows = await self.repository.attachments_by_ids(thread_id, attachment_ids)
        if len(rows) != len(attachment_ids):
            raise DomainValidationError(
                "An attachment does not belong to this conversation"
            )
        return [
            {
                "id": str(row.id),
                "filename": row.filename,
                "media_type": row.mime_type,
            }
            for row in rows
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
        # One artifact per sandbox path: presenting the path again updates it.
        row = await self.repository.at_path(thread_id, file.path)
        if row is not None and row.tool_call_id == tool_call_id:
            return describe(row)  # tool replay
        cfg = artifact_settings
        try:
            data = await asyncio.to_thread(
                read_bytes,
                backend,
                file.path,
                [*cfg.allowed_roots, ATTACHMENTS_ROOT],
                cfg.max_bytes,
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
        if row is None:
            row = ArtifactDB(
                # Stable across tool replay.
                id=uuid5(
                    NAMESPACE_URL, f"auxilia:{thread_id}:{tool_call_id}:{file.path}"
                ),
                workspace_id=self.workspace_id,
                thread_id=thread_id,
                source_path=file.path,
                title=file.title or filename,
                tool_call_id=tool_call_id,
                filename=filename,
                mime_type=mime_type,
                size=0,
                sha256="",
                storage_kind="",
                storage_key="",
            )
        row.tool_call_id = tool_call_id  # the card moves to the latest call
        row.title = file.title or row.title
        row.mime_type = mime_type
        row.sandbox_source_id = sandbox_source_id
        row.sandbox_id = backend.id
        await self._store(row, data, backend)
        return describe(await self.repository.save(row))

    async def publish_gallery_image(
        self,
        *,
        thread_id: str,
        tool_call_id: str,
        position: int,
        title: str,
        filename: str,
        mime_type: str,
        data: bytes,
    ) -> ArtifactDB:
        """Store one image of a chat gallery. Gallery images are served through
        the thread's artifact routes but stay out of its file list and sandbox."""
        if not artifact_settings.provider:
            raise DomainValidationError(
                "Image galleries need a configured object store"
            )
        if len(data) > artifact_settings.max_bytes:
            raise DomainValidationError("Image exceeds the size limit")
        artifact_id = uuid5(
            NAMESPACE_URL, f"auxilia:{thread_id}:{tool_call_id}:gallery:{position}"
        )
        row = await self.repository.in_thread(thread_id, artifact_id)
        if row is not None:
            return row  # tool replay
        row = ArtifactDB(
            id=artifact_id,
            workspace_id=self.workspace_id,
            thread_id=thread_id,
            origin=GALLERY_ORIGIN,
            source_path=f"gallery/{tool_call_id}/{position}",
            title=title,
            tool_call_id=tool_call_id,
            filename=filename,
            mime_type=mime_type,
            size=0,
            sha256="",
            storage_kind="",
            storage_key="",
        )
        await self._store(row, data, None)
        return await self.repository.save(row)

    async def attach(
        self, thread_id: str, filename: str, data: bytes
    ) -> ArtifactResponse:
        """Store a user attachment as a persistent thread file."""
        if not artifact_settings.provider:
            raise DomainValidationError("Attachments need a configured object store")
        if len(data) > artifact_settings.max_bytes:
            raise DomainValidationError("Attachment exceeds the size limit")
        safe_filename = attachment_filename(filename)
        thread = await ThreadRepository(self.db, self.workspace_id).lock(thread_id)
        if thread is None:
            raise NotFoundError("Thread not found")
        path = free_path(
            safe_filename, await self.repository.paths_in_thread(thread_id)
        )
        row = ArtifactDB(
            workspace_id=self.workspace_id,
            thread_id=thread_id,
            origin="attachment",
            source_path=path,
            title=safe_filename,
            filename=PurePosixPath(path).name,
            mime_type=await asyncio.to_thread(attachment_mime, safe_filename, data),
            size=0,
            sha256="",
            storage_kind="",
            storage_key="",
        )
        await self._store(row, data, None)
        return describe(await self.repository.save(row))

    async def restore(
        self,
        thread_id: str,
        backend: BaseSandbox,
        sandbox_source_id: UUID | None,
        *,
        current_attachment_ids: set[str] | None = None,
        visible_attachment_ids: set[str] | None = None,
    ) -> builtins.list[ArtifactDB]:
        """Restore visible thread files and return the ones to announce."""
        cfg = artifact_settings
        rows = (
            await self.repository.list_stored_in(
                thread_id,
                cfg.provider,
                cfg.storage_name,
                cfg.endpoint,
            )
            if cfg.provider
            else []
        )
        current_ids = current_attachment_ids or set()
        if current_ids:
            try:
                current_uuids = [UUID(attachment_id) for attachment_id in current_ids]
            except ValueError as exc:
                raise DomainValidationError("Invalid attachment reference") from exc
            current_rows = await self.repository.attachments_by_ids(
                thread_id, current_uuids
            )
            if len(current_rows) != len(current_ids):
                raise DomainValidationError(
                    "An attachment does not belong to this conversation"
                )
            location = (cfg.provider, cfg.storage_name, cfg.endpoint)
            if any(
                (row.storage_kind, row.storage_bucket, row.storage_endpoint) != location
                for row in current_rows
            ):
                raise DomainValidationError(
                    "An attachment's storage configuration is no longer available"
                )
            # The file attached to this turn wins if another artifact later reused
            # the same sandbox path while this prompt was waiting in the queue.
            by_path = {row.source_path: row for row in rows}
            by_path.update((row.source_path, row) for row in current_rows)
            rows = list(by_path.values())
        if visible_attachment_ids is not None:
            rows = [
                row
                for row in rows
                if row.origin != "attachment" or str(row.id) in visible_attachment_ids
            ]
        missing = await asyncio.to_thread(
            missing_on_disk, backend, [row.source_path for row in rows]
        )
        if not rows:
            return []
        restored = [
            row
            for row in rows
            if row.source_path in missing
            or (row.origin == "attachment" and str(row.id) in current_ids)
        ]
        for row in restored:
            _, data = await self.content(thread_id, row.id)
            await asyncio.to_thread(put_on_disk, backend, [(row.source_path, data)])
        for row in rows:
            row.sandbox_id = backend.id
            row.sandbox_source_id = sandbox_source_id
        await self.db.flush()
        announced = {row.id: row for row in restored}
        announced.update(
            (row.id, row)
            for row in rows
            if row.origin == "attachment" and str(row.id) in current_ids
        )
        return list(announced.values())

    async def replace_content(
        self, thread_id: str, artifact_id: UUID, data: bytes, revision: str
    ) -> ArtifactResponse:
        """Save a user's edit of a presentation over the artifact, and over the
        agent's working file in the sandbox so its next turn starts from it."""
        # Run creation takes the same transaction-scoped advisory lock. Holding
        # it through this request's commit prevents a turn from starting after
        # the guard but before the edited bytes reach the sandbox.
        runs = RunRepository(self.db, self.workspace_id)
        await runs.lock_thread_runs(thread_id)
        # Locked until the commit, so two saves from the same revision serialize
        # and the second one sees the first's digest.
        row = await self.repository.in_thread(thread_id, artifact_id, for_update=True)
        if row is None:
            raise NotFoundError(self.not_found_message)
        if row.mime_type != PPTX_MIME:
            raise DomainValidationError("Only PowerPoint files can be edited")
        if await runs.get_active_for_thread(thread_id):
            raise StaleRevisionError(
                "This presentation cannot be edited while an agent run is active."
            )
        if revision != row.sha256:
            raise StaleRevisionError(
                "This file changed since you opened it. Reload it to edit the latest version."
            )
        if len(data) > artifact_settings.max_bytes:
            raise DomainValidationError("Artifact exceeds the size limit")
        if await asyncio.to_thread(detect_mime, row.filename, data) != PPTX_MIME:
            raise DomainValidationError("Invalid PowerPoint presentation")
        if row.storage_kind == "sandbox" or not artifact_settings.provider:
            backend = await self._connect(row)
        else:
            try:
                backend = await self._connect(row)
            except ArtifactGoneError:
                backend = None  # the edit is saved; there is no agent copy to update
        if backend is not None:
            # Before storing: a failed write-back then leaves nothing to clean up,
            # and the artifact never shows an edit the agent's file lacks.
            # shortcut: a turn running right now can overwrite this, the panel
            # only allows edits between turns; add a server-side guard if needed.
            result = await asyncio.to_thread(
                backend.upload_files, [(row.source_path, data)]
            )
            if not result or result[0].error:
                raise DomainError("Could not write the edit back to the sandbox")
        await self._store(row, data, backend)
        return describe(await self.repository.save(row))

    async def _store(
        self, row: ArtifactDB, data: bytes, backend: BaseSandbox | None
    ) -> None:
        """Put `data` where the current configuration keeps artifacts and point
        `row` at it. Keys carry the digest, so a new version never overwrites
        the object a committed row still references."""
        cfg = artifact_settings
        digest = hashlib.sha256(data).hexdigest()
        kind = cfg.provider or "sandbox"
        location = (cfg.provider, cfg.storage_name, cfg.endpoint)
        in_bucket = (
            row.storage_kind not in ("", "sandbox")
            and (row.storage_kind, row.storage_bucket, row.storage_endpoint) == location
        )
        old_key = row.storage_key
        if kind != "sandbox":
            workspace_key = uuid5(NAMESPACE_URL, str(self.workspace_id))
            thread_key = uuid5(NAMESPACE_URL, f"{self.workspace_id}:{row.thread_id}")
            key = (
                f"{cfg.prefix.strip('/')}/workspaces/{workspace_key}/threads/"
                f"{thread_key}/{row.id}/{digest}/{row.filename}"
            )
            # Same bytes already in this bucket: nothing to upload.
            if not (in_bucket and key == old_key):
                store = await asyncio.to_thread(build_store, cfg)
                await asyncio.to_thread(store.put, key, data, row.mime_type)
                self.uploaded.append(key)
        else:
            if backend is None:
                raise ArtifactGoneError(
                    "This temporary file's execution environment is no longer available."
                )
            key = f"{SNAPSHOT_ROOT}/{row.id}/{digest}"
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
        # Superseded bucket objects only; sandbox snapshots expire with the sandbox.
        if in_bucket and old_key != key:
            self.replaced.append(old_key)
        row.size = len(data)
        row.sha256 = digest
        row.storage_kind = kind
        row.storage_key = key
        row.storage_bucket = cfg.storage_name
        row.storage_endpoint = cfg.endpoint

    async def purge_replaced(self) -> None:
        """Best-effort delete of superseded objects. Call only after the commit:
        before it, a rollback would leave rows pointing at deleted bytes."""
        if not self.replaced:
            return
        try:
            store = await asyncio.to_thread(build_store, artifact_settings)
        except Exception:  # noqa: BLE001 — the update is committed; never fail it here
            logger.warning("Could not reach artifact storage to purge", exc_info=True)
            self.replaced.clear()
            return
        for key in self.replaced:
            try:
                await asyncio.to_thread(store.delete, key)
            except Exception:  # noqa: BLE001 — an orphaned object is harmless
                logger.warning(
                    "Could not delete superseded artifact object %s", key, exc_info=True
                )
        self.replaced.clear()

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
                cfg.storage_name,
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
            backend = await self._connect(row)
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

    async def _connect(self, row: ArtifactDB) -> BaseSandbox:
        """The sandbox the artifact was published from."""
        source = (
            await SandboxRepository(self.db).get_scoped(
                row.sandbox_source_id, self.workspace_id
            )
            if row.sandbox_source_id
            else None
        )
        if source is None or row.sandbox_id is None:
            raise ArtifactGoneError(
                "This temporary file's execution environment is no longer available."
            )
        provider = build_provider(source)
        try:
            # Never open_sandbox: must not create a replacement environment.
            return await asyncio.to_thread(provider.connect, row.sandbox_id)
        except SandboxGoneError as exc:
            raise ArtifactGoneError(
                "This temporary file expired with its execution environment."
            ) from exc

    async def export_to_slides(
        self, thread_id: str, artifact_id: UUID, access_token: str
    ) -> str:
        """Open this artifact's Google Slides copy in the user's Drive, creating
        it on first export. Returns the Slides URL."""
        row = await self.repository.in_thread(thread_id, artifact_id)
        if row is None:
            raise NotFoundError(self.not_found_message)
        if row.mime_type != PPTX_MIME:
            raise DomainValidationError(
                "Only PowerPoint files can be exported to Google Slides"
            )
        async with httpx.AsyncClient(
            headers={"Authorization": f"Bearer {access_token}"}, timeout=60
        ) as client:
            try:
                file_id = await find_export(client, row.id)
                if file_id is None:
                    # Read the bytes only when there is no copy to reopen.
                    _, data = await self.content(thread_id, artifact_id)
                    file_id = await upload_as_slides(
                        client,
                        row.id,
                        row.title.removesuffix(".pptx"),
                        data,
                        row.mime_type,
                    )
            except httpx.HTTPStatusError as exc:
                # e.g. the Drive API is not enabled on the OAuth client's project.
                logger.warning("Google Drive export failed: %s", exc.response.text)
                raise DomainError(
                    f"Google Drive refused the export ({exc.response.status_code})"
                ) from exc
            except httpx.RequestError as exc:  # timeout, DNS, connection reset
                logger.warning("Google Drive export failed: %r", exc)
                raise DomainError("Google Drive could not be reached") from exc
        return slides_url(file_id)


def get_artifact_service(
    db: AsyncSession = Depends(get_db),
    workspace_id: UUID = Depends(get_active_workspace_id),
) -> ArtifactService:
    return ArtifactService(db, workspace_id)
