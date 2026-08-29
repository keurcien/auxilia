"""The Langfuse client and LangChain callback handler, built lazily.

Lazily on purpose. These used to be module-level constants, evaluated at import
time — and `runtime.py` imports this module, so *any* failure constructing the
client (a malformed base URL, a Langfuse SDK that validates eagerly) took down
every import of the agent runtime, at startup, for an optional integration
(design review §5.10). Now a bad configuration can at worst break tracing.

The result is memoized rather than rebuilt per call: `CallbackHandler` is passed
into every agent run, and a fresh client per run would mean a fresh exporter
thread per run.
"""

import logging

from langfuse import Langfuse
from langfuse.langchain import CallbackHandler

from app.integrations.langfuse.settings import langfuse_settings


logger = logging.getLogger(__name__)

_client: Langfuse | None = None
_handler: CallbackHandler | None = None
_built = False


def _build_langfuse() -> tuple[Langfuse | None, CallbackHandler | None]:
    if not (
        langfuse_settings.langfuse_base_url
        and langfuse_settings.langfuse_public_key
        and langfuse_settings.langfuse_secret_key
    ):
        return None, None

    client = Langfuse(
        public_key=langfuse_settings.langfuse_public_key,
        secret_key=langfuse_settings.langfuse_secret_key,
        host=langfuse_settings.langfuse_base_url,
        timeout=langfuse_settings.langfuse_timeout,
    )
    return client, CallbackHandler()


def _ensure_built() -> None:
    """Build the client once, tolerating failure.

    Tracing is optional; the agent runtime is not. A construction error is
    logged and remembered as "no tracing" rather than retried per run.
    """
    global _client, _handler, _built
    if _built:
        return
    _built = True
    try:
        _client, _handler = _build_langfuse()
    except Exception:
        # Tracing must never break a run.
        logger.exception("Langfuse is misconfigured; continuing without tracing")
        _client, _handler = None, None


def get_langfuse_callback_handler() -> CallbackHandler | None:
    """The handler to attach to a run's callbacks, or None when unconfigured."""
    _ensure_built()
    return _handler


def flush_langfuse() -> None:
    """Flush buffered traces. Called from the FastAPI lifespan on shutdown.

    Langfuse batches spans and ships them on a background timer. On Cloud Run
    the instance is frozen and killed the moment the last request drains, so
    without this the tail of every scale-to-zero cycle is simply lost — and the
    tail is disproportionately where the interesting runs are.

    Never built here: flushing must not be the thing that constructs a client
    the process never needed.
    """
    if _client is None:
        return
    try:
        _client.flush()
    except Exception:  # noqa: BLE001 — a failed flush must not fail shutdown
        logger.warning("Flushing Langfuse traces on shutdown failed", exc_info=True)
