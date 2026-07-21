"""Lazy sandbox backend that defers to a real backend once connected."""

from __future__ import annotations

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
from opensandbox import SandboxSync

from app.sandbox.backend import OpenSandbox


NOT_CONNECTED_MSG = (
    "No sandbox connected. Call create_sandbox or connect_sandbox first."
)


class LazySandboxBackend(BaseSandbox):
    """A sandbox backend that starts disconnected and connects lazily.

    All BaseSandbox file operations (ls, read, write, edit, grep, glob)
    route through execute(), so connecting the inner backend is sufficient.

    While disconnected, the file operations return their protocol error
    results instead of raising: deepagents calls them OUTSIDE any tool-call
    wrapper — large-tool-result eviction and conversation-history eviction
    both `backend.write()` from middleware hooks — so a raise there escapes
    ToolErrorMiddleware and kills the whole run, while an error result makes
    deepagents skip the eviction and carry on. Only `execute` (always reached
    through the `execute` tool, whose exceptions ToolErrorMiddleware converts
    to error ToolMessages) still raises.
    """

    def __init__(self) -> None:
        self._sandbox: SandboxSync | None = None
        self._backend: OpenSandbox | None = None

    @property
    def connected(self) -> bool:
        return self._backend is not None

    def connect(self, sandbox: SandboxSync, backend: OpenSandbox) -> None:
        self._sandbox = sandbox
        self._backend = backend

    @property
    def _inner(self) -> OpenSandbox:
        if self._backend is None:
            raise RuntimeError(NOT_CONNECTED_MSG)
        return self._backend

    @property
    def id(self) -> str:
        return self._inner.id

    def execute(self, command: str, *, timeout: int | None = None) -> ExecuteResponse:
        return self._inner.execute(command, timeout=timeout)

    def download_files(self, paths: list[str]) -> list[FileDownloadResponse]:
        return self._inner.download_files(paths)

    def upload_files(self, files: list[tuple[str, bytes]]) -> list[FileUploadResponse]:
        return self._inner.upload_files(files)

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
        return self._backend.read(file_path, offset=offset, limit=limit)

    def write(self, file_path: str, content: str) -> WriteResult:
        if self._backend is None:
            return WriteResult(error=NOT_CONNECTED_MSG)
        return self._backend.write(file_path, content)

    def edit(
        self,
        file_path: str,
        old_string: str,
        new_string: str,
        replace_all: bool = False,  # noqa: FBT001, FBT002 - protocol signature
    ) -> EditResult:
        if self._backend is None:
            return EditResult(error=NOT_CONNECTED_MSG)
        return self._backend.edit(
            file_path, old_string, new_string, replace_all=replace_all
        )

    def glob(self, pattern: str, path: str = "/") -> GlobResult:
        if self._backend is None:
            return GlobResult(error=NOT_CONNECTED_MSG)
        return self._backend.glob(pattern, path=path)

    def grep(
        self,
        pattern: str,
        path: str | None = None,
        glob: str | None = None,
    ) -> GrepResult:
        if self._backend is None:
            return GrepResult(error=NOT_CONNECTED_MSG)
        return self._backend.grep(pattern, path=path, glob=glob)
