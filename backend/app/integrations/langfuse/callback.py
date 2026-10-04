"""The Langfuse client and LangChain callback handler, built lazily.

Lazily on purpose. These used to be module-level constants, evaluated at import
time — and `app/runtime/agent.py` imports this module, so *any* failure constructing the
client (a malformed base URL, a Langfuse SDK that validates eagerly) took down
every import of the agent runtime, at startup, for an optional integration
(design review §5.10). Now a bad configuration can at worst break tracing.

The result is memoized rather than rebuilt per call: `CallbackHandler` is passed
into every agent run, and a fresh client per run would mean a fresh exporter
thread per run.
"""

import logging
from dataclasses import dataclass

from langfuse import Langfuse
from langfuse.langchain import CallbackHandler

from app.observability.service import ObservabilityRuntimeConfig


logger = logging.getLogger(__name__)


@dataclass
class _ClientEntry:
    client: Langfuse
    handler: CallbackHandler
    leases: int = 0
    retired: bool = False


@dataclass
class LangfuseLease:
    fingerprint: str
    handler: CallbackHandler
    _released: bool = False

    def release(self) -> None:
        if self._released:
            return
        self._released = True
        entry = _clients.get(self.fingerprint)
        if entry is None:
            return
        entry.leases = max(entry.leases - 1, 0)
        if entry.retired and entry.leases == 0:
            _shutdown_entry(self.fingerprint, entry)


_clients: dict[str, _ClientEntry] = {}
_current_fingerprint: str | None = None


def _build_langfuse(
    config: ObservabilityRuntimeConfig,
) -> tuple[Langfuse, CallbackHandler]:
    client = Langfuse(
        public_key=config.public_key,
        secret_key=config.secret_key,
        host=config.base_url,
        timeout=config.timeout_seconds,
    )
    return client, CallbackHandler(public_key=config.public_key)


def _shutdown_entry(fingerprint: str, entry: _ClientEntry) -> None:
    try:
        entry.client.flush()
        entry.client.shutdown()
    except Exception:  # noqa: BLE001 — optional telemetry cleanup is best effort
        logger.warning("Retiring Langfuse client failed", exc_info=True)
    finally:
        _clients.pop(fingerprint, None)


def acquire_langfuse_callback_handler(
    config: ObservabilityRuntimeConfig,
) -> LangfuseLease | None:
    """Lease a handler until the run context exits."""
    global _current_fingerprint

    cached = _clients.get(config.fingerprint)
    if cached is None:
        try:
            client, handler = _build_langfuse(config)
            cached = _ClientEntry(client=client, handler=handler)
            _clients[config.fingerprint] = cached
        except Exception:
            logger.exception("Langfuse is misconfigured; continuing without tracing")
            return None

    if _current_fingerprint != config.fingerprint:
        previous_fingerprint = _current_fingerprint
        _current_fingerprint = config.fingerprint
        cached.retired = False
        if previous_fingerprint is not None:
            previous = _clients.get(previous_fingerprint)
            if previous is not None:
                previous.retired = True
                if previous.leases == 0:
                    _shutdown_entry(previous_fingerprint, previous)

    cached.leases += 1
    return LangfuseLease(config.fingerprint, cached.handler)


def get_langfuse_callback_handler(
    config: ObservabilityRuntimeConfig,
) -> CallbackHandler | None:
    """Compatibility accessor for callers that do not need a run lease."""
    lease = acquire_langfuse_callback_handler(config)
    if lease is None:
        return None
    handler = lease.handler
    lease.release()
    return handler


def flush_langfuse() -> None:
    """Flush buffered traces. Called from the FastAPI lifespan on shutdown.

    Langfuse batches spans and ships them on a background timer. On Cloud Run
    the instance is frozen and killed the moment the last request drains, so
    without this the tail of every scale-to-zero cycle is simply lost — and the
    tail is disproportionately where the interesting runs are.

    Never built here: flushing must not be the thing that constructs a client
    the process never needed.
    """
    global _current_fingerprint

    for fingerprint, entry in list(_clients.items()):
        try:
            entry.client.flush()
            entry.client.shutdown()
        except Exception:  # noqa: BLE001 — a failed flush must not fail shutdown
            logger.warning("Flushing Langfuse traces on shutdown failed", exc_info=True)
        finally:
            _clients.pop(fingerprint, None)
    _current_fingerprint = None
