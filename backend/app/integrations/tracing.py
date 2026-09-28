"""Optional run tracing, selected here rather than in the agent runtime.

Providers supply callbacks and a fresh context for each run. The context must
be entered by the task driving the graph, before it creates child tasks; a
callback's executor thread cannot propagate attributes back to that task.
"""

import logging
from contextlib import AbstractContextManager, nullcontext
from typing import Protocol

from langchain_core.callbacks import BaseCallbackHandler


logger = logging.getLogger(__name__)


class RunTracing(Protocol):
    @property
    def callbacks(self) -> list[BaseCallbackHandler]: ...

    def run_context(
        self, *, session_id: str, user_id: str
    ) -> AbstractContextManager: ...

    def flush(self) -> None: ...


class NoOpTracing:
    @property
    def callbacks(self) -> list[BaseCallbackHandler]:
        return []

    def run_context(self, *, session_id: str, user_id: str) -> AbstractContextManager:
        return nullcontext()

    def flush(self) -> None:
        pass


_tracing: RunTracing | None = None


def get_tracing() -> RunTracing:
    """Resolve once, without importing a provider SDK unless configured."""
    global _tracing
    if _tracing is not None:
        return _tracing

    _tracing = NoOpTracing()
    try:
        from app.integrations.langfuse.settings import langfuse_settings

        if (
            langfuse_settings.langfuse_base_url
            and langfuse_settings.langfuse_public_key
            and langfuse_settings.langfuse_secret_key
        ):
            from app.integrations.langfuse.tracing import create_tracing

            _tracing = create_tracing() or _tracing
    except Exception:
        # A missing SDK or invalid optional configuration must not stop runs.
        logger.exception("Could not initialize tracing; continuing without it")
    return _tracing


def flush_tracing() -> None:
    # Shutdown must not initialize an integration that no run ever used.
    if _tracing is None:
        return
    try:
        _tracing.flush()
    except Exception:  # noqa: BLE001 — telemetry must not fail shutdown
        logger.warning("Flushing tracing failed", exc_info=True)
