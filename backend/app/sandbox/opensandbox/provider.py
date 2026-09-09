"""OpenSandbox lifecycle: create / connect with TTL renewal."""

from __future__ import annotations

import logging
from datetime import timedelta
from pathlib import Path

from opensandbox import SandboxSync
from opensandbox.config import ConnectionConfigSync
from opensandbox.exceptions.sandbox import (
    SandboxApiException,
    SandboxReadyTimeoutException,
    SandboxUnhealthyException,
)
from opensandbox.models.sandboxes import Host, SandboxFilter, Volume
from opensandbox.sync.manager import SandboxManagerSync

from app.sandbox.opensandbox.backend import OpenSandbox
from app.sandbox.provider import BaseSandboxProvider, SandboxGoneError
from app.sandbox.schemas import OpenSandboxConfig


logger = logging.getLogger(__name__)


class OpenSandboxProvider(BaseSandboxProvider):
    """Sandbox lifecycle on the OpenSandbox API (create / connect + TTL renew)."""

    config: OpenSandboxConfig

    def _probe(self) -> None:
        # One page of one sandbox: authenticated, cheap, proves the API is up.
        manager = SandboxManagerSync.create(connection_config=self._connection_config())
        try:
            manager.list_sandbox_infos(SandboxFilter(page_size=1))
        finally:
            manager.close()

    def _create_backend(self, *, timeout_minutes: int) -> OpenSandbox:
        sandbox = SandboxSync.create(
            self.config.default_image,
            timeout=timedelta(minutes=timeout_minutes),
            volumes=_parse_volume_mounts(self.config.volume_mounts) or None,
            connection_config=self._connection_config(),
        )
        return OpenSandbox(sandbox=sandbox, timeout=self.config.timeout)

    def _destroy_backend(self, backend: OpenSandbox) -> None:
        backend.kill()

    def connect(self, sandbox_id: str) -> OpenSandbox:
        try:
            sandbox = SandboxSync.connect(
                sandbox_id, connection_config=self._connection_config()
            )
        except SandboxApiException as exc:
            # Expired (TTL) or deleted sandboxes come back as 404 from the API;
            # that is the one failure the runtime recovers from by creating a
            # fresh one. Auth, quota and 5xx errors propagate and fail the run.
            if exc.status_code == 404:
                raise SandboxGoneError(
                    f"sandbox {sandbox_id} no longer exists"
                ) from exc
            raise
        except (SandboxUnhealthyException, SandboxReadyTimeoutException) as exc:
            # It exists but never became usable: nothing to restore from.
            raise SandboxGoneError(
                f"sandbox {sandbox_id} is not usable: {exc}"
            ) from exc
        sandbox.renew(timeout=timedelta(minutes=30))
        return OpenSandbox(sandbox=sandbox, timeout=self.config.timeout)

    def _connection_config(self) -> ConnectionConfigSync:
        return ConnectionConfigSync(
            api_key=self.config.secret,
            domain=self.config.url,
            use_server_proxy=self.config.use_server_proxy,
        )


def _parse_volume_mounts(entries: list[str]) -> list[Volume]:
    """Parse volume mount specs from the sandbox config.

    Each entry has the format ``host_path:sandbox_path`` with an optional
    ``:ro`` suffix for read-only mounts.
    """
    volumes: list[Volume] = []
    for i, entry in enumerate(entries):
        parts = entry.split(":")
        read_only = parts[-1] == "ro"
        if read_only:
            parts = parts[:-1]

        # Re-check after stripping the ro suffix: "/data:ro" would otherwise
        # pass a pre-strip length check and crash on parts[1].
        if len(parts) < 2:
            logger.warning(
                "Ignoring invalid volume mount %r — expected host_path:sandbox_path[:ro]",
                entry,
            )
            continue

        # Host.path requires an absolute path; resolve relative entries.
        host_path = str(Path(parts[0]).expanduser().resolve())
        sandbox_path = parts[1]

        if not Path(host_path).exists():
            logger.warning(
                "Volume mount host path %s does not exist — skipping", host_path
            )
            continue

        volumes.append(
            Volume(
                name=f"vol-{i}",
                host=Host(path=host_path),
                mount_path=sandbox_path,
                read_only=read_only,
            )
        )
    return volumes
