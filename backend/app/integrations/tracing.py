"""Optional run tracing, selected here rather than in the agent runtime.

Providers supply callbacks and a fresh context for each run. The context must
be entered by the task driving the graph, before it creates child tasks; a
callback's executor thread cannot propagate attributes back to that task.
"""

import logging
from contextlib import AbstractContextManager, nullcontext
from typing import Protocol

from langchain_core.callbacks import BaseCallbackHandler

from app.observability.service import ObservabilityRuntimeConfig


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


def get_tracing(config: ObservabilityRuntimeConfig | None) -> RunTracing:
    """Resolve tracing for one DB configuration revision."""
    if config is None:
        return NoOpTracing()
    try:
        from app.integrations.langfuse.tracing import create_tracing

        return create_tracing(config) or NoOpTracing()
    except Exception:
        logger.exception("Could not initialize tracing; continuing without it")
        return NoOpTracing()


def flush_tracing() -> None:
    try:
        from app.integrations.langfuse.callback import flush_langfuse

        flush_langfuse()
    except Exception:  # noqa: BLE001 — telemetry must not fail shutdown
        logger.warning("Flushing tracing failed", exc_info=True)
