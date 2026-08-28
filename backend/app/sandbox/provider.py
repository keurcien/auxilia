"""Provider abstraction over the sandbox implementations.

A provider owns sandbox *lifecycle* (create / reconnect) for one vendor and
returns ready-to-use ``BaseSandbox`` backends plus the model-facing message
describing what happened. The backends themselves stay pure execution
surfaces (execute / upload / download), so everything the agent tools need
is expressed once, in ``tools.py``, against this base class.

Providers are instance-configured: each one is built from a workspace
``sandboxes`` row (see ``build_provider``), never from process-wide settings —
two agents in the same deployment can target different vendors, or two
differently-configured instances of the same vendor.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod

from deepagents.backends.sandbox import BaseSandbox

from app.sandbox.models import SandboxDB, SandboxProviderType
from app.sandbox.schemas import SandboxConfigBase, validate_config
from app.utils.encryption import decrypt_value


logger = logging.getLogger(__name__)


class BaseSandboxProvider(ABC):
    """Template for a sandbox vendor: subclasses implement backend creation,
    cleanup and reconnect; the create → install-default-packages → describe
    choreography lives here once."""

    def __init__(self, config: SandboxConfigBase) -> None:
        self.config = config

    def create(self, *, timeout_minutes: int) -> tuple[BaseSandbox, str]:
        backend = self._create_backend(timeout_minutes=timeout_minutes)
        try:
            install_default_packages(backend, list(self.config.default_packages))
            # Inside the protected block: resolving `backend.id` for the
            # message can itself hit the network (OpenSandbox), and a failure
            # there must not leak a running sandbox either.
            message = self._created_message(backend, timeout_minutes)
        except Exception:
            # Don't leak a running sandbox the caller never got an ID for.
            try:
                self._destroy_backend(backend)
            except Exception:  # noqa: BLE001 — best-effort cleanup; the original error is re-raised
                logger.warning("Failed to clean up sandbox after create failure")
            raise
        return backend, message

    @abstractmethod
    def _create_backend(self, *, timeout_minutes: int) -> BaseSandbox: ...

    @abstractmethod
    def _destroy_backend(self, backend: BaseSandbox) -> None: ...

    @abstractmethod
    def connect(self, sandbox_id: str) -> tuple[BaseSandbox, str]:
        """Reconnect to an existing sandbox; raise if it cannot be reached
        or restored (the tool converts the error into a model message)."""
        ...

    def _created_message(self, backend: BaseSandbox, timeout_minutes: int) -> str:
        return f"Sandbox created (ID: {backend.id}). You can now execute code."


def build_provider(sandbox: SandboxDB) -> BaseSandboxProvider:
    """Build the vendor provider for one workspace sandbox row.

    Decrypts the stored credential and re-validates the row through the
    typed config union, so a provider never sees an unvalidated config.
    """
    # Function-level imports: the provider modules import helpers from this
    # module, so resolving them lazily avoids an import cycle.
    from app.sandbox.cloudrun.provider import CloudRunProvider
    from app.sandbox.daytona.provider import DaytonaProvider
    from app.sandbox.opensandbox.provider import OpenSandboxProvider

    providers: dict[SandboxProviderType, type[BaseSandboxProvider]] = {
        SandboxProviderType.opensandbox: OpenSandboxProvider,
        SandboxProviderType.cloudrun: CloudRunProvider,
        SandboxProviderType.daytona: DaytonaProvider,
    }
    secret = (
        decrypt_value(sandbox.encrypted_secret) if sandbox.encrypted_secret else None
    )
    config = validate_config(
        sandbox.provider, url=sandbox.url, secret=secret, config=sandbox.config
    )
    return providers[sandbox.provider](config)


def install_default_packages(backend: BaseSandbox, packages: list[str]) -> None:
    """Install a provider's default packages into a fresh sandbox.

    ``packages`` is admin-controlled workspace config, not user input, and
    the command runs inside the sandbox's own isolation boundary.
    """
    if not packages:
        return
    # A shell command, not SQL — security analyzers pattern-match on
    # string-built arguments to functions named `execute`.
    install_command = "pip install " + " ".join(packages)  # nosemgrep
    result = backend.execute(install_command, timeout=120)  # nosemgrep
    if result.exit_code != 0:
        raise RuntimeError(f"Failed to install default packages: {result.output}")
