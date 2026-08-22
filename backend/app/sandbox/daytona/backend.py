"""Daytona sandbox backend implementation for deepagents.

Wraps one Daytona SDK ``Sandbox``: `execute` goes through
``sandbox.process.exec`` and file transfer through ``sandbox.fs``. All
BaseSandbox file helpers (ls, read, write, edit, grep, glob) come from the
base class and route through `execute`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from deepagents.backends.protocol import (
    ExecuteResponse,
    FileDownloadResponse,
    FileUploadResponse,
)
from deepagents.backends.sandbox import BaseSandbox


if TYPE_CHECKING:
    from daytona import Sandbox


class DaytonaSandbox(BaseSandbox):
    def __init__(self, sandbox: Sandbox, *, timeout: int = 30 * 60) -> None:
        self._sandbox = sandbox
        self._default_timeout = timeout

    @property
    def id(self) -> str:
        return self._sandbox.id

    def execute(
        self,
        command: str,
        *,
        timeout: int | None = None,
    ) -> ExecuteResponse:
        effective_timeout = timeout if timeout is not None else self._default_timeout
        response = self._sandbox.process.exec(command, timeout=effective_timeout)
        exit_code = response.exit_code
        return ExecuteResponse(
            output=response.result or "",
            exit_code=int(exit_code) if exit_code is not None else None,
            truncated=False,
        )

    def delete(self) -> None:
        """Terminate the sandbox (create-path cleanup)."""
        self._sandbox.delete()

    def download_files(self, paths: list[str]) -> list[FileDownloadResponse]:
        responses: list[FileDownloadResponse] = []
        for path in paths:
            if not path.startswith("/"):
                responses.append(
                    FileDownloadResponse(path=path, content=None, error="invalid_path")
                )
                continue
            try:
                content = self._sandbox.fs.download_file(path)
            except Exception:
                content = None
            responses.append(
                FileDownloadResponse(
                    path=path,
                    content=content,
                    error=None if content is not None else "file_not_found",
                )
            )
        return responses

    def upload_files(self, files: list[tuple[str, bytes]]) -> list[FileUploadResponse]:
        responses: list[FileUploadResponse] = []
        for path, content in files:
            if not path.startswith("/"):
                responses.append(FileUploadResponse(path=path, error="invalid_path"))
                continue
            try:
                self._sandbox.fs.upload_file(content, path)
                responses.append(FileUploadResponse(path=path, error=None))
            except Exception:
                responses.append(
                    FileUploadResponse(path=path, error="permission_denied")
                )
        return responses
