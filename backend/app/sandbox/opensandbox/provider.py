"""OpenSandbox lifecycle: create / connect with TTL renewal."""

from __future__ import annotations

from datetime import timedelta

from opensandbox import SandboxSync
from opensandbox.config import ConnectionConfigSync

from app.sandbox.opensandbox.backend import OpenSandbox
from app.sandbox.provider import install_default_packages
from app.sandbox.settings import sandbox_settings


class OpenSandboxProvider:
    """Sandbox lifecycle on the OpenSandbox API (create / connect + TTL renew)."""

    def create(self, *, timeout_minutes: int) -> tuple[OpenSandbox, str]:
        settings = sandbox_settings.opensandbox
        sandbox = SandboxSync.create(
            settings.default_image,
            timeout=timedelta(minutes=timeout_minutes),
            connection_config=_connection_config(),
        )
        backend = OpenSandbox(sandbox=sandbox, timeout=settings.timeout)
        install_default_packages(backend, list(settings.default_packages))

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


def _connection_config() -> ConnectionConfigSync:
    settings = sandbox_settings.opensandbox
    return ConnectionConfigSync(
        api_key=settings.api_key,
        domain=settings.domain,
        use_server_proxy=settings.use_server_proxy,
    )
