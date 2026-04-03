"""Factory for creating sandbox instances with the right volumes and packages."""

from __future__ import annotations

import logging
from pathlib import Path

from opensandbox import SandboxSync
from opensandbox.config import ConnectionConfigSync
from opensandbox.models.sandboxes import Host, Volume

from app.sandbox.backend import OpenSandbox
from app.sandbox.settings import sandbox_settings


logger = logging.getLogger(__name__)


def _parse_volume_mounts() -> list[Volume]:
    """Parse volume mount specs from settings.

    Each entry has the format ``host_path:sandbox_path`` with an optional
    ``:ro`` suffix for read-only mounts.
    """
    volumes: list[Volume] = []
    for i, entry in enumerate(sandbox_settings.parsed_volume_mounts):
        parts = entry.split(":")
        if len(parts) < 2:
            logger.warning("Ignoring invalid volume mount %r — expected host_path:sandbox_path[:ro]", entry)
            continue

        read_only = parts[-1] == "ro"
        if read_only:
            parts = parts[:-1]

        host_path = str(Path(parts[0]).expanduser())
        sandbox_path = parts[1]

        if not Path(host_path).exists():
            logger.warning("Volume mount host path %s does not exist — skipping", host_path)
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


def create_sandbox_backend() -> tuple[SandboxSync, OpenSandbox]:
    """Create a sandbox and wrap it in an OpenSandbox backend.

    Returns:
        A tuple of (sandbox, backend) — caller must call
        sandbox.kill() when done.
    """
    volumes = _parse_volume_mounts()
    packages = list(sandbox_settings.default_packages)

    connection_config = ConnectionConfigSync(
        api_key=sandbox_settings.api_key,
        domain=sandbox_settings.domain,
        use_server_proxy=sandbox_settings.use_server_proxy,
    )

    sandbox = SandboxSync.create(
        sandbox_settings.default_image,
        volumes=volumes or None,
        connection_config=connection_config,
    )

    backend = OpenSandbox(
        sandbox=sandbox,
        default_packages=packages,
        timeout=sandbox_settings.timeout,
    )

    return sandbox, backend
