"""Lazy sandbox backend that defers to a real backend once connected."""

from __future__ import annotations

import asyncio
import logging
import shlex
from pathlib import PurePosixPath
from typing import Protocol, runtime_checkable

from deepagents.backends.protocol import (
    EditResult,
    ExecuteResponse,
    FileDownloadResponse,
    FileUploadResponse,
    GlobResult,
    GrepResult,
    LsResult,
    ReadResult,
    WriteResult,
)
from deepagents.backends.sandbox import BaseSandbox
from deepagents.backends.utils import slice_read_response

from app.skills.schemas import MAX_BUNDLE_BYTES


logger = logging.getLogger(__name__)


NOT_CONNECTED_MSG = (
    "No sandbox connected. Call create_sandbox or connect_sandbox first."
)


@runtime_checkable
class SupportsPersist(Protocol):
    """Backends that persist their state for cross-instance reconnects."""

    def persist(self) -> None: ...


class LazySandboxBackend(BaseSandbox):
    """A sandbox backend that starts disconnected and connects lazily.

    All BaseSandbox file operations (ls, read, write, edit, delete, grep, glob)
    route through execute(), so connecting the inner backend is sufficient.

    While disconnected, the file operations and `execute` do not raise:
    deepagents calls the backend OUTSIDE any tool-call wrapper —
    large-tool-result eviction and conversation-history eviction both write
    from middleware hooks — so a raise there escapes ToolErrorMiddleware and
    kills the whole run, while an error result makes deepagents skip the
    eviction and carry on. `ls`/`read`/`write`/`edit`/`glob`/`grep` return
    their protocol error results with a clear message, and `execute` returns
    a failed `ExecuteResponse`, so any BaseSandbox helper reaching it (0.7's
    write preflight, the inherited `delete`, future ones) degrades the same
    way; the `execute` tool shows that response to the model as an ordinary
    failed command. `id`, `upload_files` and `download_files` still raise:
    nothing reaches them outside a connected tool path.
    """

    def __init__(self) -> None:
        self._backend: BaseSandbox | None = None
        self.skill_files: list[tuple[str, bytes]] = []

    @property
    def connected(self) -> bool:
        return self._backend is not None

    def connect(self, backend: BaseSandbox) -> None:
        if self.skill_files:
            directories = sorted(
                {str(PurePosixPath(path).parent) for path, _ in self.skill_files}
            )
            created = backend.execute(
                "mkdir -p " + " ".join(shlex.quote(path) for path in directories)
            )
            if created.exit_code != 0:
                raise RuntimeError(
                    "Failed to create sandbox skill directories "
                    f"(exit code {created.exit_code}): {created.output[:2000]}"
                )
            results = backend.upload_files(self.skill_files)
            if len(results) != len(self.skill_files) or any(r.error for r in results):
                raise RuntimeError("Failed to materialize skill files in sandbox")
            downloaded = backend.download_files([path for path, _ in self.skill_files])
            expected = dict(self.skill_files)
            if len(downloaded) != len(expected) or any(
                r.error or r.content != expected.get(r.path) for r in downloaded
            ):
                raise RuntimeError("Sandbox skill verification failed")
        self._backend = backend

    def persist(self) -> None:
        """Persist sandbox state for cross-instance reconnects.

        No-op unless the connected backend supports it (CloudRunSandbox
        snapshots its overlay to GCS; OpenSandbox needs nothing — it lives
        server-side under its own TTL).
        """
        if isinstance(self._backend, SupportsPersist):
            self._backend.persist()

    @property
    def _inner(self) -> BaseSandbox:
        if self._backend is None:
            raise RuntimeError(NOT_CONNECTED_MSG)
        return self._backend

    @property
    def id(self) -> str:
        return self._inner.id

    def execute(self, command: str, *, timeout: int | None = None) -> ExecuteResponse:
        if self._backend is None:
            return ExecuteResponse(output=NOT_CONNECTED_MSG, exit_code=1)
        return self._backend.execute(command, timeout=timeout)

    # File operations return protocol error results while disconnected (the
    # async variants inherit this: BackendProtocol's a* defaults delegate to
    # the sync methods via asyncio.to_thread).

    def ls(self, path: str) -> LsResult:
        if self._backend is None:
            return LsResult(error=NOT_CONNECTED_MSG)
        return self._backend.ls(path)

    def read(self, file_path: str, offset: int = 0, limit: int = 2000) -> ReadResult:
        if self._backend is None:
            return ReadResult(error=NOT_CONNECTED_MSG)
        result = self._backend.read(file_path, offset=offset, limit=limit)
        return self._recover_skill_read(result, file_path, offset, limit)

    async def aread(
        self, file_path: str, offset: int = 0, limit: int = 2000
    ) -> ReadResult:
        # BaseSandbox.aread calls aexecute directly, bypassing our read method.
        return await asyncio.to_thread(self.read, file_path, offset, limit)

    def _recover_skill_read(
        self, result: ReadResult, file_path: str, offset: int, limit: int
    ) -> ReadResult:
        if (
            not result.error
            or "unexpected server response" not in result.error
            or not any(path == file_path for path, _ in self.skill_files)
        ):
            return result
        # The helper wraps content in JSON on stdout. Some remote command
        # responses cannot be parsed, even though upload verification succeeds.
        # Fetch the current bytes through the independent file-transfer channel;
        # never repair guessed escapes or serve the originally uploaded copy.
        try:
            downloads = self._inner.download_files([file_path])
            if len(downloads) != 1:
                return result
            file = downloads[0]
            if (
                file.path != file_path
                or file.error
                or file.content is None
                or len(file.content) > MAX_BUNDLE_BYTES
            ):
                return result
            content = file.content.decode("utf-8")
        except UnicodeDecodeError:
            return result  # Keep the normal backend handling for binary files.
        except Exception:  # noqa: BLE001 — preserve the original tool error
            logger.warning(
                "Skill read fallback failed for %s", file_path, exc_info=True
            )
            return result
        logger.warning("Recovered malformed sandbox read response for %s", file_path)
        return slice_read_response(
            {"content": content, "encoding": "utf-8"}, offset, limit
        )

    def write(self, file_path: str, content: str) -> WriteResult:
        if self._backend is None:
            return WriteResult(error=NOT_CONNECTED_MSG)
        return self._backend.write(file_path, content)

    def edit(
        self,
        file_path: str,
        old_string: str,
        new_string: str,
        replace_all: bool = False,
    ) -> EditResult:
        if self._backend is None:
            return EditResult(error=NOT_CONNECTED_MSG)
        return self._backend.edit(
            file_path, old_string, new_string, replace_all=replace_all
        )

    def glob(self, pattern: str, path: str | None = None) -> GlobResult:
        if self._backend is None:
            return GlobResult(error=NOT_CONNECTED_MSG)
        return self._backend.glob(pattern, path=path)

    def grep(
        self,
        pattern: str,
        path: str | None = None,
        glob: str | None = None,
        *,
        max_count: int | None = None,
    ) -> GrepResult:
        if self._backend is None:
            return GrepResult(error=NOT_CONNECTED_MSG)
        return self._backend.grep(pattern, path=path, glob=glob, max_count=max_count)

    def download_files(self, paths: list[str]) -> list[FileDownloadResponse]:
        return self._inner.download_files(paths)

    def upload_files(self, files: list[tuple[str, bytes]]) -> list[FileUploadResponse]:
        return self._inner.upload_files(files)
