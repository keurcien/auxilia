"""OpenSandbox lifecycle: create / connect with TTL renewal."""

from __future__ import annotations

import logging
from datetime import timedelta
from pathlib import Path

from opensandbox import SandboxSync
from opensandbox.config import ConnectionConfigSync
from opensandbox.models.sandboxes import Host, Volume

from app.sandbox.opensandbox.backend import OpenSandbox
from app.sandbox.provider import BaseSandboxProvider
from app.sandbox.schemas import OpenSandboxConfig


logger = logging.getLogger(__name__)


class OpenSandboxProvider(BaseSandboxProvider):
    """Sandbox lifecycle on the OpenSandbox API (create / connect + TTL renew)."""

    config: OpenSandboxConfig

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

    def _created_message(self, backend: OpenSandbox, timeout_minutes: int) -> str:
        return (
            f"Sandbox created (ID: {backend.id}, TTL: {timeout_minutes}min). "
            "You can now execute code."
        )

    def connect(self, sandbox_id: str) -> tuple[OpenSandbox, str]:
        sandbox = SandboxSync.connect(
            sandbox_id, connection_config=self._connection_config()
        )
        sandbox.renew(timeout=timedelta(minutes=30))
        backend = OpenSandbox(sandbox=sandbox, timeout=self.config.timeout)
        return backend, (
            f"Reconnected to sandbox {sandbox_id}. TTL renewed for 30 minutes."
        )

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
