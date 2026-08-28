"""Sandbox lifecycle tools for lazy creation and reconnection.

The model-facing contract (two tools, their names, and their docstrings) is
defined once here; provider differences live behind ``BaseSandboxProvider``
(see ``app/sandbox/provider.py``). The provider is injected by the caller —
it comes from the sandbox bound to the agent, not from process-wide config.
"""

from __future__ import annotations

from langchain_core.tools import tool

from app.sandbox.lazy import LazySandboxBackend
from app.sandbox.provider import BaseSandboxProvider


def create_sandbox_tools(
    lazy_backend: LazySandboxBackend, provider: BaseSandboxProvider
) -> list:
    """Create sandbox management tools bound to a lazy backend and provider."""

    @tool
    def create_sandbox(timeout_minutes: int = 30) -> str:
        """Create a new sandbox for code execution. Returns the sandbox ID.

        Call this before running any code. If a sandbox was already created
        in this conversation, use connect_sandbox with the existing ID instead.
        """
        backend, message = provider.create(timeout_minutes=timeout_minutes)
        lazy_backend.connect(backend)
        return message

    @tool
    def connect_sandbox(sandbox_id: str) -> str:
        """Reconnect to an existing sandbox by ID. Use this when a sandbox
        was already created earlier in this conversation. Files from the
        previous session are restored where the provider supports it.
        """
        try:
            backend, message = provider.connect(sandbox_id)
        except Exception as e:  # noqa: BLE001 — surfaced to the model as a tool result, never raised
            return (
                f"Failed to reconnect to sandbox {sandbox_id}: {e}. "
                "Create a new sandbox instead."
            )
        lazy_backend.connect(backend)
        return message

    return [create_sandbox, connect_sandbox]
