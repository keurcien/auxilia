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

import asyncio
import logging
from abc import ABC, abstractmethod
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from deepagents.backends.sandbox import BaseSandbox

from app.exceptions import SandboxUnavailableError
from app.sandbox.models import SandboxDB, SandboxProviderType
from app.sandbox.schemas import SandboxConfigBase, validate_config
from app.utils.encryption import decrypt_value


logger = logging.getLogger(__name__)

# Lifetime asked of providers that have a TTL (OpenSandbox). Every run of a
# thread reconnects and renews, so this only bounds an abandoned thread.
DEFAULT_TIMEOUT_MINUTES = 30


class SandboxGoneError(RuntimeError):
    """The sandbox no longer exists and cannot be restored.

    Providers raise it from ``connect`` for the one failure the runtime can
    recover from by creating a fresh sandbox. Anything else (network, quota,
    credentials) propagates and fails the run.
    """


@runtime_checkable
class SupportsPersist(Protocol):
    """Backends that persist their state for cross-instance reconnects."""

    def persist(self) -> None: ...


@dataclass
class SandboxSession:
    """A live sandbox for one run."""

    backend: BaseSandbox
    sandbox_id: str
    # True when the thread's previous sandbox was gone and this is its
    # replacement — the model is told, since its files did not survive.
    replaced: bool = False

    def persist(self) -> None:
        if isinstance(self.backend, SupportsPersist):
            self.backend.persist()


def open_sandbox(
    provider: BaseSandboxProvider, sandbox_id: str | None
) -> SandboxSession:
    """Reconnect the thread's sandbox, or create one.

    Runs at the start of every run of an agent bound to a sandbox — the
    lifecycle belongs to the runtime, never to the model. A sandbox that is
    gone and has no snapshot is replaced; any other failure raises.
    """
    replaced = False
    if sandbox_id is not None:
        try:
            backend, _ = provider.connect(sandbox_id)
            return SandboxSession(backend=backend, sandbox_id=sandbox_id)
        except SandboxGoneError as exc:
            logger.warning("Replacing sandbox %s: %s", sandbox_id, exc)
            replaced = True
        except Exception as exc:
            raise provider.unavailable(f"reconnect failed: {_reason(exc)}") from exc
    try:
        backend, _ = provider.create(timeout_minutes=DEFAULT_TIMEOUT_MINUTES)
    except Exception as exc:
        raise provider.unavailable(f"create failed: {_reason(exc)}") from exc
    return SandboxSession(backend=backend, sandbox_id=backend.id, replaced=replaced)


def _reason(exc: BaseException) -> str:
    return str(exc) or type(exc).__name__


async def ensure_sandboxes_available(rows: Iterable[SandboxDB]) -> None:
    """Pre-flight for a run: every sandbox the agent graph is bound to must
    answer a cheap health probe, else `SandboxUnavailableError`.

    Sits behind `RunService.create` (like the model gate) and `is-ready`, so an
    outage blocks the composer and 409s a launch instead of failing a run the
    model would then see. Rows are deduped by id; probes are sync SDK calls,
    run off the loop.
    """
    seen: set = set()
    for row in rows:
        if row.id in seen:
            continue
        seen.add(row.id)
        try:
            provider = build_provider(row)
        except Exception as exc:
            raise SandboxUnavailableError(
                str(row.id), row.name, f"invalid configuration: {_reason(exc)}"
            ) from exc
        await asyncio.to_thread(provider.check_available)


class BaseSandboxProvider(ABC):
    """Template for a sandbox vendor: subclasses implement backend creation,
    cleanup and reconnect; the create → install-default-packages → describe
    choreography lives here once."""

    def __init__(
        self,
        config: SandboxConfigBase,
        *,
        sandbox_id: str | None = None,
        name: str | None = None,
    ) -> None:
        self.config = config
        # The workspace row this provider was built from — for error bodies.
        self.sandbox_id = sandbox_id
        self.name = name

    def unavailable(self, reason: str) -> SandboxUnavailableError:
        return SandboxUnavailableError(self.sandbox_id, self.name, reason)

    def check_available(self) -> None:
        """Raise `SandboxUnavailableError` unless the provider answers a cheap
        probe. Any failure counts: unreachable, refusing, misconfigured."""
        try:
            self._probe()
        except Exception as exc:
            raise self.unavailable(_reason(exc)) from exc

    @abstractmethod
    def _probe(self) -> None:
        """The cheapest call that proves the provider can serve sandboxes."""

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
        """Reconnect to an existing sandbox. Raise ``SandboxGoneError`` when
        it no longer exists and cannot be restored; anything else propagates."""
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
    return providers[sandbox.provider](
        config, sandbox_id=str(sandbox.id), name=sandbox.name
    )


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
