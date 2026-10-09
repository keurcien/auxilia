"""Langfuse adapter for the provider-neutral run tracing contract."""

from collections.abc import Iterator
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass

from langchain_core.callbacks import BaseCallbackHandler
from langfuse import propagate_attributes

from app.integrations.langfuse.callback import (
    LangfuseLease,
    acquire_langfuse_callback_handler,
    flush_langfuse,
)
from app.observability.service import ObservabilityRuntimeConfig


@dataclass(frozen=True)
class LangfuseTracing:
    lease: LangfuseLease

    @property
    def callbacks(self) -> list[BaseCallbackHandler]:
        return [self.lease.handler]

    def run_context(self, *, session_id: str, user_id: str) -> AbstractContextManager:
        return self._leased_context(session_id=session_id, user_id=user_id)

    @contextmanager
    def _leased_context(self, *, session_id: str, user_id: str) -> Iterator[None]:
        # Metadata on the root callback alone loses these attributes across
        # async boundaries. Session costs require them on each generation.
        try:
            with propagate_attributes(session_id=session_id, user_id=user_id):
                yield
        finally:
            self.lease.release()

    def flush(self) -> None:
        flush_langfuse()


def create_tracing(
    config: ObservabilityRuntimeConfig,
) -> LangfuseTracing | None:
    lease = acquire_langfuse_callback_handler(config)
    return LangfuseTracing(lease) if lease is not None else None
