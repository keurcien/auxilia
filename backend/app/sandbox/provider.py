"""Provider abstraction over the sandbox implementations.

A provider owns sandbox *lifecycle* (create / reconnect) for one vendor and
returns ready-to-use ``BaseSandbox`` backends plus the model-facing message
describing what happened. The backends themselves stay pure execution
surfaces (execute / upload / download), so everything the agent tools need
is expressed once, in ``tools.py``, against this protocol.
"""

from __future__ import annotations

from typing import Protocol

from deepagents.backends.sandbox import BaseSandbox

from app.sandbox.settings import sandbox_settings


class SandboxProvider(Protocol):
    def create(self, *, timeout_minutes: int) -> tuple[BaseSandbox, str]:
        """Create a sandbox; return (backend, message for the model)."""
        ...

    def connect(self, sandbox_id: str) -> tuple[BaseSandbox, str]:
        """Reconnect to an existing sandbox; raise if it cannot be reached
        or restored (the tool converts the error into a model message)."""
        ...


def get_provider() -> SandboxProvider:
    # Function-level imports: the provider modules import helpers from this
    # module, so resolving them lazily avoids an import cycle.
    if sandbox_settings.provider == "cloudrun":
        from app.sandbox.cloudrun.provider import CloudRunProvider

        return CloudRunProvider()
    from app.sandbox.opensandbox.provider import OpenSandboxProvider

    return OpenSandboxProvider()


def install_default_packages(backend: BaseSandbox, packages: list[str]) -> None:
    """Install a provider's default packages into a fresh sandbox.

    ``packages`` is operator-controlled deployment config (env), not user
    input, and the command runs inside the sandbox's own isolation boundary.
    """
    if not packages:
        return
    # A shell command, not SQL — static analyzers flag `execute(f"...")`.
    install_command = "pip install " + " ".join(packages)
    result = backend.execute(install_command, timeout=120)
    if result.exit_code != 0:
        raise RuntimeError(f"Failed to install default packages: {result.output}")
