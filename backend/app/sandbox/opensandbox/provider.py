"""OpenSandbox lifecycle: create / connect with TTL renewal."""

from __future__ import annotations

import logging
from datetime import timedelta
from pathlib import Path

from opensandbox import SandboxSync
from opensandbox.config import ConnectionConfigSync
from opensandbox.models.sandboxes import Host, Volume

from app.sandbox.opensandbox.backend import OpenSandbox
from app.sandbox.provider import install_default_packages
from app.sandbox.settings import sandbox_settings


logger = logging.getLogger(__name__)


class OpenSandboxProvider:
    """Sandbox lifecycle on the OpenSandbox API (create / connect + TTL renew)."""

    def create(self, *, timeout_minutes: int) -> tuple[OpenSandbox, str]:
        settings = sandbox_settings.opensandbox
        sandbox = SandboxSync.create(
            settings.default_image,
            timeout=timedelta(minutes=timeout_minutes),
            volumes=_parse_volume_mounts() or None,
            connection_config=_connection_config(),
        )
        backend = OpenSandbox(sandbox=sandbox, timeout=settings.timeout)
        try:
            install_default_packages(backend, list(settings.default_packages))
        except Exception:
            # Don't leak a running sandbox the caller never got an ID for.
            try:
                sandbox.kill()
            except Exception:
                logger.warning("Failed to kill sandbox after install failure")
            raise

        info = sandbox.get_info()
        return backend, (
            f"Sandbox created (ID: {info.id}, TTL: {timeout_minutes}min). "
            "You can now execute code."
        )

    def connect(self, sandbox_id: str) -> tuple[OpenSandbox, str]:
        sandbox = SandboxSync.connect(
            sandbox_id, connection_config=_connection_config()
        )
        sandbox.renew(timeout=timedelta(minutes=30))
        backend = OpenSandbox(
            sandbox=sandbox, timeout=sandbox_settings.opensandbox.timeout
        )
        return backend, (
            f"Reconnected to sandbox {sandbox_id}. TTL renewed for 30 minutes."
        )


def _parse_volume_mounts() -> list[Volume]:
    """Parse volume mount specs from settings.

    Each entry has the format ``host_path:sandbox_path`` with an optional
    ``:ro`` suffix for read-only mounts.
    """
    volumes: list[Volume] = []
    for i, entry in enumerate(sandbox_settings.opensandbox.parsed_volume_mounts):
        parts = entry.split(":")
        if len(parts) < 2:
            logger.warning(
                "Ignoring invalid volume mount %r — expected host_path:sandbox_path[:ro]",
                entry,
            )
            continue

        read_only = parts[-1] == "ro"
        if read_only:
            parts = parts[:-1]

        host_path = str(Path(parts[0]).expanduser())
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


def _connection_config() -> ConnectionConfigSync:
    settings = sandbox_settings.opensandbox
    return ConnectionConfigSync(
        api_key=settings.api_key,
        domain=settings.domain,
        use_server_proxy=settings.use_server_proxy,
    )
