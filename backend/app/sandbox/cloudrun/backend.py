"""Cloud Run sandbox backend implementation for deepagents.

Cloud Run sandboxes are gVisor sandboxes managed by the `sandbox` CLI on a
`--sandbox-launcher` service. All CLI access goes through a transport
(app/sandbox/transport.py): subprocess when the CLI is mounted on this
instance, HTTP when it lives on a dedicated gateway service. The sandbox
sees its host container's image read-only; `--write` gives it an ephemeral
tmpfs overlay, which `snapshot()` exports as a tar for GCS persistence
between agent turns.
"""

from __future__ import annotations

import base64
import logging
import re
import shlex
from pathlib import Path

from deepagents.backends.protocol import (
    ExecuteResponse,
    FileDownloadResponse,
    FileUploadResponse,
)
from deepagents.backends.sandbox import BaseSandbox

from app.sandbox.cloudrun import snapshots
from app.sandbox.cloudrun.transport import (
    SandboxTimeoutError,
    SandboxTransport,
    get_transport,
)
from app.sandbox.settings import sandbox_settings


logger = logging.getLogger(__name__)

# Sandbox names reach the CLI as argv; restrict them so a model-supplied id
# can never be parsed as a flag.
_SANDBOX_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")

# Keep each base64 payload embedded in an exec argv well under ARG_MAX.
_UPLOAD_CHUNK_BYTES = 48 * 1024


class CloudRunSandbox(BaseSandbox):
    """Cloud Run sandbox conforming to SandboxBackendProtocol.

    Inherits all file operation methods from BaseSandbox (ls, read, write,
    edit, grep, glob) and implements execute() via `sandbox exec`.
    """

    def __init__(
        self,
        sandbox_id: str,
        *,
        timeout: int = 30 * 60,
        transport: SandboxTransport | None = None,
    ) -> None:
        _validate_sandbox_id(sandbox_id)
        self._id = sandbox_id
        self._default_timeout = timeout
        self._transport = transport if transport is not None else get_transport()

    @property
    def id(self) -> str:
        return self._id

    def execute(
        self,
        command: str,
        *,
        timeout: int | None = None,
    ) -> ExecuteResponse:
        effective_timeout = timeout if timeout is not None else self._default_timeout
        try:
            result = self._transport.exec(
                self._id, ["/bin/bash", "-lc", command], timeout=effective_timeout
            )
        except SandboxTimeoutError:
            return ExecuteResponse(
                output=f"Command timed out after {effective_timeout} seconds",
                exit_code=124,
                truncated=False,
            )

        output = result.stdout.decode(errors="replace") + result.stderr.decode(
            errors="replace"
        )
        return ExecuteResponse(
            output=output,
            exit_code=result.returncode,
            truncated=False,
        )

    def is_alive(self) -> bool:
        """Probe whether the named sandbox still exists."""
        try:
            result = self._transport.exec(self._id, ["/bin/true"], timeout=30)
        except Exception:
            return False
        return result.returncode == 0

    def snapshot(self) -> bytes:
        """Export the writable overlay of the running sandbox as a tar."""
        return self._transport.export_tar(self._id)

    def persist(self) -> None:
        """Snapshot the overlay to GCS so another instance can restore it.

        Best-effort: skipped (with a log) when no snapshot bucket is
        configured — e.g. local dev pointed at a gateway.
        """
        if sandbox_settings.cloudrun.gcs_bucket is None:
            logger.debug("No sandbox snapshot bucket configured — skipping persist")
            return
        snapshots.save_snapshot(self._id, self.snapshot())

    def delete(self) -> None:
        self._transport.delete(self._id)

    def download_files(self, paths: list[str]) -> list[FileDownloadResponse]:
        responses: list[FileDownloadResponse] = []
        for path in paths:
            if not path.startswith("/"):
                responses.append(
                    FileDownloadResponse(path=path, content=None, error="invalid_path")
                )
                continue
            try:
                result = self._transport.exec(
                    self._id, ["/bin/cat", path], timeout=self._default_timeout
                )
            except SandboxTimeoutError:
                responses.append(
                    FileDownloadResponse(
                        path=path, content=None, error="file_not_found"
                    )
                )
                continue
            if result.returncode != 0:
                responses.append(
                    FileDownloadResponse(
                        path=path, content=None, error="file_not_found"
                    )
                )
            else:
                responses.append(
                    FileDownloadResponse(path=path, content=result.stdout, error=None)
                )
        return responses

    def upload_files(self, files: list[tuple[str, bytes]]) -> list[FileUploadResponse]:
        responses: list[FileUploadResponse] = []
        for path, content in files:
            if not path.startswith("/"):
                responses.append(FileUploadResponse(path=path, error="invalid_path"))
                continue
            responses.append(self._upload_file(path, content))
        return responses

    def _upload_file(self, path: str, content: bytes) -> FileUploadResponse:
        """Write file content by embedding base64 chunks in exec commands.

        `sandbox exec` argv passthrough is the only documented input channel
        (stdin piping is not), so content travels inside the command string,
        chunked to stay under argv size limits.
        """
        quoted = shlex.quote(path)
        parent = shlex.quote(str(Path(path).parent))
        encoded = base64.b64encode(content).decode("ascii")
        chunks = [
            encoded[i : i + _UPLOAD_CHUNK_BYTES]
            for i in range(0, len(encoded), _UPLOAD_CHUNK_BYTES)
        ] or [""]

        for i, chunk in enumerate(chunks):
            redirect = ">" if i == 0 else ">>"
            prefix = f"mkdir -p {parent} && " if i == 0 else ""
            # A shell command, not SQL — security analyzers pattern-match on
            # string-built arguments to functions named `execute`. Every
            # interpolation is safe by construction: chunk is base64
            # alphabet, paths are shlex-quoted, and it runs inside the
            # sandbox's own isolation boundary.
            write_command = f"{prefix}printf '%s' '{chunk}' | base64 -d {redirect} {quoted}"  # nosemgrep
            result = self.execute(write_command)  # nosemgrep
            if result.exit_code != 0:
                return FileUploadResponse(path=path, error="permission_denied")
        return FileUploadResponse(path=path, error=None)


def _validate_sandbox_id(sandbox_id: str) -> None:
    if not _SANDBOX_ID_RE.match(sandbox_id):
        raise ValueError(f"Invalid sandbox id: {sandbox_id!r}")
