"""An in-memory `BaseSandbox` for tests: records commands and uploads."""

from __future__ import annotations

from deepagents.backends.protocol import (
    ExecuteResponse,
    FileDownloadResponse,
    FileUploadResponse,
)
from deepagents.backends.sandbox import BaseSandbox


class StubSandbox(BaseSandbox):
    def __init__(self, sandbox_id: str = "sbx-test", *, exit_code: int = 0) -> None:
        self._id = sandbox_id
        self.exit_code = exit_code
        self.commands: list[str] = []
        self.files: dict[str, bytes] = {}
        self.fail_uploads: set[str] = set()
        self.persisted = 0
        # Optional scripted stdout per command prefix (e.g. a `cat` of a marker).
        self.outputs: dict[str, str] = {}

    @property
    def id(self) -> str:
        return self._id

    def execute(self, command: str, *, timeout: int | None = None) -> ExecuteResponse:
        self.commands.append(command)
        for prefix, output in self.outputs.items():
            if command.startswith(prefix):
                return ExecuteResponse(output=output, exit_code=0)
        output = "" if self.exit_code == 0 else "Permission denied"
        return ExecuteResponse(output=output, exit_code=self.exit_code)

    def upload_files(self, files: list[tuple[str, bytes]]) -> list[FileUploadResponse]:
        responses = []
        for path, content in files:
            if path in self.fail_uploads:
                responses.append(
                    FileUploadResponse(path=path, error="permission_denied")
                )
                continue
            self.files[path] = content
            responses.append(FileUploadResponse(path=path, error=None))
        return responses

    def download_files(self, paths: list[str]) -> list[FileDownloadResponse]:
        return [
            FileDownloadResponse(
                path=path,
                content=self.files.get(path),
                error=None if path in self.files else "file_not_found",
            )
            for path in paths
        ]

    def persist(self) -> None:
        self.persisted += 1
