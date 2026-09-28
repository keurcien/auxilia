"""Langfuse adapter for the provider-neutral run tracing contract."""

from contextlib import AbstractContextManager
from dataclasses import dataclass

from langchain_core.callbacks import BaseCallbackHandler
from langfuse import propagate_attributes
from langfuse.langchain import CallbackHandler

from app.integrations.langfuse.callback import (
    flush_langfuse,
    get_langfuse_callback_handler,
)


@dataclass(frozen=True)
class LangfuseTracing:
    handler: CallbackHandler

    @property
    def callbacks(self) -> list[BaseCallbackHandler]:
        return [self.handler]

    def run_context(self, *, session_id: str, user_id: str) -> AbstractContextManager:
        # Metadata on the root callback alone loses these attributes across
        # async boundaries. Session costs require them on each generation.
        return propagate_attributes(session_id=session_id, user_id=user_id)

    def flush(self) -> None:
        flush_langfuse()


def create_tracing() -> LangfuseTracing | None:
    handler = get_langfuse_callback_handler()
    return LangfuseTracing(handler) if handler is not None else None
