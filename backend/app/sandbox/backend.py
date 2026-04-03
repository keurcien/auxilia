"""OpenSandbox backend implementation for deepagents."""

from __future__ import annotations

import time

from deepagents.backends.protocol import (
    ExecuteResponse,
    FileDownloadResponse,
    FileUploadResponse,
)
from deepagents.backends.sandbox import BaseSandbox
from opensandbox import SandboxSync
from opensandbox.models.execd import RunCommandOpts


class OpenSandbox(BaseSandbox):
    """OpenSandbox implementation conforming to SandboxBackendProtocol.

    Inherits all file operation methods from BaseSandbox (ls, read, write,
    edit, grep, glob) and implements execute() using the OpenSandbox API.
    """

    def __init__(
        self,
        *,
        sandbox: SandboxSync,
        timeout: int = 30 * 60,
        poll_interval: float = 0.1,
        default_packages: list[str] | None = None,
    ) -> None:
        self._sandbox = sandbox
        self._default_timeout = timeout
        self._poll_interval = poll_interval

        if default_packages:
            pkgs = " ".join(default_packages)
            result = self.execute(f"pip install {pkgs}", timeout=120)
            if result.exit_code != 0:
                raise RuntimeError(
                    f"Failed to install default packages: {result.output}"
                )

    @property
    def id(self) -> str:
        info = self._sandbox.get_info()
        return info.id

    def execute(
        self,
        command: str,
        *,
        timeout: int | None = None,
    ) -> ExecuteResponse:
        effective_timeout = timeout if timeout is not None else self._default_timeout

        execution = self._sandbox.commands.run(
            command,
            opts=RunCommandOpts(background=True),
        )
        execution_id = execution.id

        started_at = time.monotonic()

        while True:
            elapsed = time.monotonic() - started_at
            if effective_timeout and elapsed >= effective_timeout:
                try:
                    self._sandbox.commands.interrupt(execution_id)
                except Exception:
                    pass
                return ExecuteResponse(
                    output=f"Command timed out after {effective_timeout} seconds",
                    exit_code=124,
                    truncated=False,
                )

            status = self._sandbox.commands.get_command_status(execution_id)
            if not status.running and status.exit_code is not None:
                break

            time.sleep(self._poll_interval)

        logs = self._sandbox.commands.get_background_command_logs(execution_id)
        output = logs.content or ""

        return ExecuteResponse(
            output=output,
            exit_code=status.exit_code,
            truncated=False,
        )

    def download_files(self, paths: list[str]) -> list[FileDownloadResponse]:
        responses: list[FileDownloadResponse] = []
        for path in paths:
            if not path.startswith("/"):
                responses.append(
                    FileDownloadResponse(path=path, content=None, error="invalid_path")
                )
                continue
            try:
                content = self._sandbox.files.read_bytes(path)
                responses.append(
                    FileDownloadResponse(path=path, content=content, error=None)
                )
            except Exception:
                responses.append(
                    FileDownloadResponse(
                        path=path, content=None, error="file_not_found"
                    )
                )
        return responses

    def upload_files(
        self, files: list[tuple[str, bytes]]
    ) -> list[FileUploadResponse]:
        responses: list[FileUploadResponse] = []
        for path, content in files:
            if not path.startswith("/"):
                responses.append(FileUploadResponse(path=path, error="invalid_path"))
                continue
            try:
                self._sandbox.files.write_file(path, content)
                responses.append(FileUploadResponse(path=path, error=None))
            except Exception:
                responses.append(
                    FileUploadResponse(path=path, error="permission_denied")
                )
        return responses
