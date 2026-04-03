"""Sandbox lifecycle tools for lazy creation and reconnection."""

from __future__ import annotations

from datetime import timedelta

from langchain_core.tools import tool
from opensandbox import SandboxSync
from opensandbox.config import ConnectionConfigSync

from app.sandbox.backend import OpenSandbox
from app.sandbox.lazy import LazySandboxBackend
from app.sandbox.settings import sandbox_settings


def _get_connection_config() -> ConnectionConfigSync:
    return ConnectionConfigSync(
        api_key=sandbox_settings.api_key,
        domain=sandbox_settings.domain,
        use_server_proxy=sandbox_settings.use_server_proxy,
    )


def create_sandbox_tools(lazy_backend: LazySandboxBackend) -> list:
    """Create sandbox management tools bound to a lazy backend."""

    @tool
    def create_sandbox(timeout_minutes: int = 30) -> str:
        """Create a new sandbox for code execution. Returns the sandbox ID.

        Call this before running any code. If a sandbox was already created
        in this conversation, use connect_sandbox with the existing ID instead.
        """
        sandbox = SandboxSync.create(
            sandbox_settings.default_image,
            timeout=timedelta(minutes=timeout_minutes),
            connection_config=_get_connection_config()
        )

        backend = OpenSandbox(
            sandbox=sandbox,
            default_packages=list(sandbox_settings.default_packages) or None,
            timeout=sandbox_settings.timeout,
        )

        lazy_backend.connect(sandbox, backend)

        info = sandbox.get_info()
        return f"Sandbox created (ID: {info.id}, TTL: {timeout_minutes}min). You can now execute code."

    @tool
    def connect_sandbox(sandbox_id: str) -> str:
        """Reconnect to an existing sandbox by ID. Use this when a sandbox
        was already created earlier in this conversation.

        Renews the TTL for another 30 minutes on success.
        """
        try:
            sandbox = SandboxSync.connect(
                sandbox_id,
                connection_config=_get_connection_config(),
            )
            sandbox.renew(timeout=timedelta(minutes=30))

            backend = OpenSandbox(
                sandbox=sandbox,
                timeout=sandbox_settings.timeout,
            )

            lazy_backend.connect(sandbox, backend)

            return f"Reconnected to sandbox {sandbox_id}. TTL renewed for 30 minutes."
        except Exception as e:
            return f"Failed to reconnect to sandbox {sandbox_id}: {e}. Create a new sandbox instead."

    return [create_sandbox, connect_sandbox]
