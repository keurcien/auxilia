"""An in-memory `BaseSandbox` for tests: a real deepagents sandbox backend
(all file tools route through `execute`) with a tiny shell that understands
the few commands the runtime issues, plus recorded uploads."""

from __future__ import annotations

import shlex

from deepagents.backends.protocol import (
    ExecuteResponse,
    FileDownloadResponse,
    FileUploadResponse,
)
from deepagents.backends.sandbox import BaseSandbox


class StubSandbox(BaseSandbox):
    def __init__(self, sandbox_id: str = "sbx-stub") -> None:
        self._id = sandbox_id
        self.files: dict[str, bytes] = {}
        self.commands: list[str] = []
        self.uploads: list[list[tuple[str, bytes]]] = []
        self.fail_uploads = False
        self.persisted = 0

    @property
    def id(self) -> str:
        return self._id

    def execute(self, command: str, *, timeout: int | None = None) -> ExecuteResponse:
        self.commands.append(command)
        for part in command.split("&&"):
            argv = shlex.split(part.replace("2>/dev/null", ""))
            match argv:
                case ["rm", "-rf", root]:
                    self.files = {
                        p: c for p, c in self.files.items() if not p.startswith(root)
                    }
                case ["mkdir", "-p", *_]:
                    pass
                case ["cat", path]:
                    if path not in self.files:
                        return ExecuteResponse(output="", exit_code=1)
                    return ExecuteResponse(
                        output=self.files[path].decode(), exit_code=0
                    )
                case _:
                    return ExecuteResponse(
                        output=f"unsupported: {command}", exit_code=127
                    )
        return ExecuteResponse(output="", exit_code=0)

    def upload_files(self, files: list[tuple[str, bytes]]) -> list[FileUploadResponse]:
        self.uploads.append(list(files))
        if self.fail_uploads:
            return [
                FileUploadResponse(path=p, error="permission_denied") for p, _ in files
            ]
        for path, content in files:
            self.files[path] = content
        return [FileUploadResponse(path=p) for p, _ in files]

    def download_files(self, paths: list[str]) -> list[FileDownloadResponse]:
        return [
            FileDownloadResponse(path=p, content=self.files[p])
            if p in self.files
            else FileDownloadResponse(path=p, error="file_not_found")
            for p in paths
        ]

    def persist(self) -> None:
        self.persisted += 1
