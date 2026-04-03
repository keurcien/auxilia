"""Lazy sandbox backend that defers to a real backend once connected."""

from __future__ import annotations

from deepagents.backends.protocol import (
    ExecuteResponse,
    FileDownloadResponse,
    FileUploadResponse,
)
from deepagents.backends.sandbox import BaseSandbox
from opensandbox import SandboxSync

from app.sandbox.backend import OpenSandbox


NOT_CONNECTED_MSG = "No sandbox connected. Call create_sandbox or connect_sandbox first."


class LazySandboxBackend(BaseSandbox):
    """A sandbox backend that starts disconnected and connects lazily.

    All BaseSandbox file operations (ls, read, write, edit, grep, glob)
    route through execute(), so connecting the inner backend is sufficient.
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
